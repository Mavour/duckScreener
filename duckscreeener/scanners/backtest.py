import logging
import re
import requests
import time
from datetime import datetime
from duckscreeener.db.database import (
    get_signals, record_outcome, get_signal_stats, get_pattern_analysis,
    store_knowledge,
)
from duckscreeener.config.settings import (
    BACKTEST_SUCCESS_THRESHOLD, BACKTEST_FAILURE_THRESHOLD,
    COINGECKO_API_URL,
)

logger = logging.getLogger(__name__)


def get_current_prices(symbols, token_addresses=None):
    """
    Fetch current prices for symbols with improved accuracy and retry logic.
    Uses CoinGecko for top coins, DexScreener per-token API for memecoins.
    Returns dict keyed by symbol with price and source.
    """
    price_map = {}

    # DexScreener per-token API for addresses FIRST (most accurate for memecoins)
    if token_addresses:
        for addr in token_addresses:
            for attempt in range(3):  # Retry up to 3 times
                try:
                    url = f"https://api.dexscreener.com/latest/dex/tokens/{addr}"
                    resp = requests.get(url, timeout=15)  # Increased timeout
                    if resp.status_code == 200:
                        data = resp.json()
                        pairs = data.get('pairs') or []
                        # Get the pair with highest liquidity
                        if pairs:
                            pair = max(pairs, key=lambda p: float(p.get('liquidity', {}).get('usd', 0) or 0))
                            price = float(pair.get('priceUsd', 0) or 0)
                            if price > 0:
                                base = pair.get('baseToken', {})
                                sym = base.get('symbol', '').upper()
                                if sym:
                                    price_map[sym] = {
                                        'price': price,
                                        'source': 'dexscreener',
                                        'address': addr,
                                    }
                                    break  # Success, exit retry loop
                    elif resp.status_code == 429:  # Rate limit
                        time.sleep(2 ** attempt)  # Exponential backoff
                    else:
                        break  # Don't retry on other HTTP errors
                except Exception as e:
                    if attempt == 2:  # Last attempt
                        logger.warning(f"DexScreener token fetch failed for {addr}: {e}")
                    time.sleep(1)  # Wait before retry

    # CoinGecko for top 1000 coins (CEX coins) - paginate 4 pages of 250
    for page in range(1, 5):
        for attempt in range(3):  # Retry up to 3 times
            try:
                url = f"{COINGECKO_API_URL}/coins/markets"
                params = {
                    'vs_currency': 'usd',
                    'order': 'market_cap_desc',
                    'per_page': 250,
                    'page': page,
                    'sparkline': 'false',
                }
                resp = requests.get(url, params=params, timeout=20)  # Increased timeout
                resp.raise_for_status()
                for coin in resp.json():
                    sym = coin.get('symbol', '').upper()
                    if sym and sym not in price_map:
                        price_map[sym] = {
                            'price': coin.get('current_price', 0),
                            'source': 'coingecko',
                        }
                break  # Success, exit retry loop
            except Exception as e:
                if attempt == 2:  # Last attempt
                    logger.warning(f"CoinGecko page {page} fetch failed: {e}")
                time.sleep(2 ** attempt)  # Exponential backoff
        time.sleep(0.5)

    # DexScreener search fallback for symbols without address
    missing = [s for s in symbols if s not in price_map]
    if missing:
        for sym in missing[:15]:  # Increased from 10 to 15
            for attempt in range(3):  # Retry up to 3 times
                try:
                    url = f"https://api.dexscreener.com/latest/dex/search?q={sym}+solana"
                    resp = requests.get(url, timeout=15)  # Increased timeout
                    if resp.status_code == 200:
                        data = resp.json()
                        pairs = data.get('pairs') or []
                        for pair in pairs:
                            if pair.get('chainId') != 'solana':
                                continue
                            base = pair.get('baseToken', {})
                            if base.get('symbol', '').upper() == sym:
                                price = float(pair.get('priceUsd', 0) or 0)
                                if price > 0:
                                    price_map[sym] = {
                                        'price': price,
                                        'source': 'dexscreener',
                                    }
                                    break  # Found price, exit pair loop
                        if sym in price_map:
                            break  # Found price, exit retry loop
                    elif resp.status_code == 429:  # Rate limit
                        time.sleep(2 ** attempt)  # Exponential backoff
                    else:
                        break  # Don't retry on other HTTP errors
                except Exception as e:
                    if attempt == 2:  # Last attempt
                        logger.warning(f"DexScreener search failed for {sym}: {e}")
                    time.sleep(1)  # Wait before retry

    # Price validation - filter out obviously wrong prices
    validated_map = {}
    for sym, data in price_map.items():
        price = data['price']
        # Basic sanity check: price should be positive and not astronomically high/low
        if price > 0 and price < 1000000:  # Less than $1M per token
            validated_map[sym] = data
        else:
            logger.warning(f"Filtered out invalid price for {sym}: ${price}")

    return validated_map


def extract_entry_price_from_text(text):
    """Fallback: extract entry price from legacy text-based knowledge records"""
    patterns = [
        r'Price:\s*\$([\d.]+(?:e[+-]?\d+)?)',
        r'Entry:\s*\$([\d.]+(?:e[+-]?\d+)?)',
        r'entry\s+price[:\s]*\$?([\d.]+(?:e[+-]?\d+)?)',
        r'@\s*\$?([\d.]+(?:e[+-]?\d+)?)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def run_backtest(chat_id=None):
    """
    Run backtest on today's signals only (since midnight).
    Compares entry price with current price.
    Records outcomes and returns report.
    """
    try:
        # Get today's signals only (since midnight)
        import time as time_module
        today_start = time_module.mktime(
            datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timetuple()
        )
        signals = get_signals(
            source_types=['scan', 'memecoin', 'gmgn', 'solana'],
            since=today_start,
            limit=200
        )

        # Also check legacy knowledge records (fallback)
        from duckscreeener.db.database import get_all_knowledge_by_source_prefix
        legacy_records = []
        for prefix in ['scan:', 'memecoin:', 'gmgn:']:
            legacy_records.extend(get_all_knowledge_by_source_prefix(prefix))

        if not signals and not legacy_records:
            return "No signals found for backtest.\nRun /scan or /memecoin first to generate signals."

        # Build symbol -> signal map (structured takes priority)
        symbol_signals = {}
        for sig in signals:
            sym = sig['symbol'].upper()
            if sym not in symbol_signals or sig['timestamp'] > symbol_signals[sym]['timestamp']:
                symbol_signals[sym] = sig

        # Add legacy records that don't have structured signals
        for record in legacy_records:
            source = record['source']
            symbol = source.split(':')[-1].upper()
            if symbol not in symbol_signals:
                entry_price = extract_entry_price_from_text(record['text'])
                if entry_price:
                    # Extract signal type from text
                    text = record.get('text', '')
                    sig_type = 'scan'
                    if 'GEM SCAN' in text or 'WHALE' in text:
                        sig_type = 'WHALE ACCUMULATION'
                    elif 'MEMECOIN' in text or 'NEW' in text:
                        sig_type = 'NEW MEMECOIN'
                    elif 'GMGN' in text:
                        sig_type = 'GMGN SCAN'

                    symbol_signals[symbol] = {
                        'id': record['id'],
                        'symbol': symbol,
                        'token_address': None,
                        'source_type': source.split(':')[0],
                        'entry_price': entry_price,
                        'signal_type': sig_type,
                        'market_cap': None,
                        'volume': None,
                        'score': None,
                        'narrative': None,
                        'analysis': record['text'][:200],
                        'timestamp': record['timestamp'],
                    }

        # Get current prices
        symbols = list(symbol_signals.keys())
        addresses = [s.get('token_address') for s in symbol_signals.values() if s.get('token_address')]
        current_prices = get_current_prices(symbols, addresses)

        success_count = 0
        failure_count = 0
        pending_count = 0
        report_by_source = {}

        for symbol, sig in symbol_signals.items():
            entry_price = sig['entry_price']
            if symbol not in current_prices:
                pending_count += 1
                continue

            current_price = current_prices[symbol]['price']
            if not current_price or not entry_price:
                pending_count += 1
                continue

            change_pct = ((current_price - entry_price) / entry_price) * 100

            if change_pct >= BACKTEST_SUCCESS_THRESHOLD:
                status = "SUCCESS"
                success_count += 1
            elif change_pct <= BACKTEST_FAILURE_THRESHOLD:
                status = "FAILED"
                failure_count += 1
            else:
                status = "PENDING"
                pending_count += 1

            # Record outcome
            signal_id = sig.get('id')
            if signal_id:
                record_outcome(signal_id, current_price, change_pct, status)

            ts = datetime.fromtimestamp(sig['timestamp']).strftime("%H:%M")
            entry_str = f"${entry_price:.6f}" if entry_price < 1 else f"${entry_price:.2f}"
            current_str = f"${current_price:.6f}" if current_price < 1 else f"${current_price:.2f}"
            source = sig.get('source_type', '?')
            sig_type = sig.get('signal_type', '')

            if status == "SUCCESS":
                status_emoji = "\u2705"
            elif status == "FAILED":
                status_emoji = "\u274C"
            else:
                status_emoji = "\u23F3"

            if source not in report_by_source:
                report_by_source[source] = []

            report_by_source[source].append(
                f"{status_emoji} *{symbol}* — Scanned at {ts} [{sig_type}]\n"
                f"Entry: {entry_str} -> Current: {current_str}\n"
                f"Change: {'+' if change_pct > 0 else ''}{change_pct:.1f}% - {status}"
            )

        if success_count == 0 and failure_count == 0 and pending_count == 0:
            return "No evaluable signals. All signals have unknown current prices."

        total = success_count + failure_count + pending_count
        win_rate = (success_count / (success_count + failure_count) * 100) if (success_count + failure_count) > 0 else 0

        source_labels = {
            'scan': "\U0001F40B CEX Spot — Whale Accumulation",
            'memecoin': "\U0001F680 Memecoin — New Launch",
            'gmgn': "\U0001F9E0 GMGN — Smart Money",
            'solana': "\u2600\uFE0F Solana — On-Chain",
        }

        report = f"\U0001F4CA BACKTEST REPORT\n"
        report += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        report += f"\u2705 Success: {success_count} | \u274C Failed: {failure_count} | \u23F3 Pending: {pending_count}\n"
        report += f"\U0001F4C8 Win Rate: {win_rate:.1f}%\n\n"

        # Pattern analysis
        patterns = get_pattern_analysis()
        if patterns:
            report += "\U0001F50D PATTERN ANALYSIS:\n"
            for p in patterns[:5]:
                report += f"- {p['signal_type']} ({p['source_type']}): {p['win_rate']:.0f}% WR, avg {p['avg_change']:+.1f}% ({p['total']} signals)\n"
            report += "\n"

        # Grouped signals by source
        source_labels = {
            'scan': "\U0001F40B CEX Spot — Whale Accumulation",
            'memecoin': "\U0001F680 Memecoin — New Launch",
            'gmgn': "\U0001F9E0 GMGN — Smart Money",
            'solana': "\u2600\uFE0F Solana — On-Chain",
        }
        for source, lines in report_by_source.items():
            label = source_labels.get(source, source.upper())
            report += f"── {label} ──\n"
            report += "\n".join(lines)
            report += "\n\n"

        report += "Use /backtest anytime to check performance"

        return report

    except Exception as e:
        logger.error(f"Backtest error: {e}")
        return f"Backtest error: {e}"
