import logging
import re
import requests
from duckscreeener.config.settings import COINGECKO_API_URL
from duckscreeener.db.database import get_all_knowledge_by_source_prefix
from duckscreeener.services.external_apis import openrouter_chat

logger = logging.getLogger(__name__)


def get_current_prices(symbols):
    try:
        url = f"{COINGECKO_API_URL}/coins/markets"
        params = {'vs_currency': 'usd', 'order': 'market_cap_desc', 'per_page': 250, 'page': 1}
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        price_map = {}
        for coin in data:
            sym = coin.get('symbol', '').upper()
            price_map[sym] = {
                'price': coin.get('current_price', 0),
                'name': coin.get('name', ''),
                'image': coin.get('image', ''),
                'market_cap': coin.get('market_cap', 0)
            }

        try:
            sol_url = "https://api.dexscreener.com/latest/dex/tokens/solana"
            sol_resp = requests.get(sol_url, timeout=10)
            if sol_resp.status_code == 200:
                sol_data = sol_resp.json()
                for pair in sol_data.get('pairs', [])[:100]:
                    base = pair.get('baseToken', {})
                    sym = base.get('symbol', '').upper()
                    if sym and sym not in price_map:
                        price_map[sym] = {
                            'price': float(pair.get('priceUsd', 0)),
                            'name': base.get('name', ''),
                            'image': base.get('logoURI', ''),
                            'market_cap': 0
                        }
        except:
            pass

        return price_map
    except Exception as e:
        logger.error(f"Failed to get prices: {e}")
        return {}


def extract_entry_price(text):
    """Robust entry price extraction using regex"""
    patterns = [
        r'Price:\s*\$([\d.]+)',
        r'Entry:\s*\$([\d.]+)',
        r'entry\s+price[:\s]*\$?([\d.]+)',
        r'@\s*\$?([\d.]+)',
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
    from duckscreeener.config.settings import (
        BACKTEST_SUCCESS_THRESHOLD, BACKTEST_FAILURE_THRESHOLD, BACKTEST_CHAT_ID,
    )
    from duckscreeener.db.database import get_all_knowledge_by_source_prefix

    try:
        all_records = []
        for prefix in ['scan:', 'solana:', 'gmgn:']:
            all_records.extend(get_all_knowledge_by_source_prefix(prefix))

        if not all_records:
            logger.info("No scan records found for backtest")
            return

        symbols = set()
        scan_by_symbol = {}
        for record in all_records:
            source = record['source']
            symbol = source.split(':')[-1].upper()
            timestamp = record['timestamp']
            if symbol not in scan_by_symbol or timestamp > scan_by_symbol[symbol]['timestamp']:
                scan_by_symbol[symbol] = record

        symbols = set(scan_by_symbol.keys())
        current_prices = get_current_prices(symbols)

        success_count = 0
        failure_count = 0
        pending_count = 0
        report_lines = []

        from datetime import datetime
        report_date = datetime.now().strftime("%Y-%m-%d %H:%M")

        for symbol, record in scan_by_symbol.items():
            text = record['text']
            timestamp = record['timestamp']

            entry_price = extract_entry_price(text)

            if not entry_price or symbol not in current_prices:
                pending_count += 1
                continue

            current_price = current_prices[symbol]['price']

            if entry_price > 0:
                change_pct = ((current_price - entry_price) / entry_price) * 100

                if change_pct >= BACKTEST_SUCCESS_THRESHOLD:
                    status = "SUCCESS"
                    status_emoji = ""
                    success_count += 1
                elif change_pct <= BACKTEST_FAILURE_THRESHOLD:
                    status = "FAILED"
                    status_emoji = ""
                    failure_count += 1
                else:
                    status = "PENDING"
                    status_emoji = ""
                    pending_count += 1

                ts = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
                entry_str = f"${entry_price:.6f}" if entry_price < 1 else f"${entry_price:.2f}"
                current_str = f"${current_price:.6f}" if current_price < 1 else f"${current_price:.2f}"

                report_lines.append(
                    f"{status_emoji} *{symbol}* ({ts})\n"
                    f"Entry: {entry_str} -> Current: {current_str}\n"
                    f"Change: {'+' if change_pct > 0 else ''}{change_pct:.1f}% - {status}\n"
                )

        if success_count > 0 or failure_count > 0:
            total = success_count + failure_count + pending_count
            success_rate = (success_count / total * 100) if total > 0 else 0

            report = "BACKTEST REPORT\n"
            report += f"Generated: {report_date}\n\n"
            report += f"Success: {success_count} | Failed: {failure_count} | Pending: {pending_count}\n"
            report += f"Win Rate: {success_rate:.1f}%\n\n"
            report += "Recent Signals:\n"
            report += "\n".join(report_lines)
            report += "\n\nUse /backtest anytime to check performance"

            if chat_id:
                return report
            elif BACKTEST_CHAT_ID:
                try:
                    import asyncio
                    from telegram import Bot
                    from duckscreeener.config.settings import TELEGRAM_TOKEN
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    bot = Bot(token=TELEGRAM_TOKEN)
                    loop.run_until_complete(bot.send_message(
                        chat_id=int(BACKTEST_CHAT_ID),
                        text=report,
                        parse_mode="Markdown"
                    ))
                    loop.close()
                    logger.info(f"Sent backtest report to chat {BACKTEST_CHAT_ID}")
                except Exception as e:
                    logger.error(f"Failed to send backtest report: {e}")

        logger.info(f"Backtest completed: {success_count} success, {failure_count} failed, {pending_count} pending")

    except Exception as e:
        logger.error(f"Backtest error: {e}")
