import logging
import requests
import time
import random
from duckscreeener.config.settings import (
    COINGECKO_API_URL, COINGECKO_NEWS_URL,
    SCAN_MIN_VOLUME_USD, SCAN_MIN_PRICE_CHANGE,
    GMGN_API_URL, SOLANA_RPC_URL, SOLANA_RPC_HEADERS,
)
from duckscreeener.services.external_apis import openrouter_chat

logger = logging.getLogger(__name__)

SOLANA_SENT_ALERTS = set()
GMGN_SENT_ALERTS = set()

EXCLUDED_SYMBOLS = {
    "SOL", "WSOL", "USDC", "USDT", "BUSD", "DAI", "ETH", "WETH", "BTC", "WBTC",
    "RAY", "JUP", "JTO", "ORCA", "MNGO", "SRM", "MSOL", "STSOL",
    "RENDER", "PYTH",
}


def is_memecoin(symbol, name, market_cap, liquidity):
    if not symbol:
        return False
    sym = symbol.upper().strip()
    if sym in EXCLUDED_SYMBOLS:
        return False
    if liquidity > 5_000_000:
        return False
    if market_cap > 100_000_000:
        return False
    return True


def _coingecko_request(url, params, max_retries=3):
    import random
    import time as time_module
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                wait = (2 ** attempt) * 5 + random.uniform(0, 3)
                logger.warning(f"CoinGecko rate limited, waiting {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time_module.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait = (2 ** attempt) * 3 + random.uniform(0, 2)
                logger.warning(f"CoinGecko request failed: {e}, retrying in {wait:.0f}s")
                time_module.sleep(wait)
            else:
                raise
    return None


def scan_potential_coins():
    """
    Detect CEX spot coins where whales are accumulating BEFORE price moves.
    
    Logic:
    1. Volume is high but price is still flat (volume/price divergence = accumulation)
    2. 24h change is small (-5% to +10%) — NOT already pumped
    3. Cross-reference with recent news/narratives
    4. Market cap $10M-$500M (room to grow, not micro-cap)
    """
    try:
        coins_url = f"{COINGECKO_API_URL}/coins/markets"
        params = {
            'vs_currency': 'usd',
            'order': 'volume_desc',
            'per_page': 100,
            'page': 1,
            'sparkline': 'false',
            'price_change_percentage': '1h,24h,7d'
        }
        markets_data = _coingecko_request(coins_url, params)
        if not markets_data:
            logger.error("Failed to fetch CoinGecko markets data after retries")
            return []

        potential_gems = []

        for coin in markets_data:
            volume = coin.get('total_volume', 0) or 0
            price_change_24h = coin.get('price_change_percentage_24h', 0) or 0
            price_change_1h = coin.get('price_change_percentage_1h_in_currency', 0) or 0
            market_cap = coin.get('market_cap', 0) or 0
            current_price = coin.get('current_price', 0)
            symbol = coin.get('symbol', '').upper()
            ath = coin.get('ath', 0) or 0

            if symbol in EXCLUDED_SYMBOLS:
                continue

            if market_cap < 2_000_000 or market_cap > 500_000_000:
                continue

            if volume < 50_000:
                continue

            price_change_24h_abs = abs(price_change_24h)
            if price_change_24h_abs > 20:
                continue

            volume_to_mcap_ratio = volume / market_cap if market_cap > 0 else 0

            ath_drop = ((ath - current_price) / ath * 100) if ath and ath > 0 else 0

            is_accumulation = False
            gem_type = ""

            if volume_to_mcap_ratio > 0.15 and price_change_24h_abs < 8:
                is_accumulation = True
                gem_type = "WHALE ACCUMULATION"
            elif volume_to_mcap_ratio > 0.1 and -10 <= price_change_24h <= 10:
                is_accumulation = True
                gem_type = "SILENT ACCUMULATION"
            elif volume_to_mcap_ratio > 0.08 and 0 < price_change_24h < 15:
                is_accumulation = True
                gem_type = "EARLY MOMENTUM"
            elif ath_drop > 60 and volume_to_mcap_ratio > 0.05 and price_change_24h > -10:
                is_accumulation = True
                gem_type = "DEEP VALUE + VOLUME"

            if not is_accumulation:
                continue

            coin_id = coin.get('id', symbol.lower())
            coingecko_url = f"https://www.coingecko.com/en/coins/{coin_id}"
            coinmarketcap_url = f"https://coinmarketcap.com/currencies/{coin_id}/"

            potential_gems.append({
                'name': coin.get('name', ''),
                'symbol': symbol,
                'price': current_price,
                'change_1h': price_change_1h,
                'change_24h': price_change_24h,
                'volume': volume,
                'market_cap': market_cap,
                'image': coin.get('image', ''),
                'gem_type': gem_type,
                'coingecko_url': coingecko_url,
                'coinmarketcap_url': coinmarketcap_url,
                'coin_id': coin_id,
                'vol_mcap_ratio': volume_to_mcap_ratio,
                'ath_drop': ath_drop,
            })

        # Fetch news ONCE before the loop
        news_data = []
        try:
            news_resp = requests.get(f"{COINGECKO_NEWS_URL}?page=1", timeout=10)
            if news_resp.status_code == 200:
                news_data = news_resp.json().get('data', [])[:50]
        except Exception:
            pass

        for gem in potential_gems:
            news_context = ""
            if news_data:
                search_terms = [gem['symbol'].lower(), gem['name'].lower(), gem['coin_id'].lower()]
                related = []
                for item in news_data:
                    title = item.get('title', '').lower()
                    desc = item.get('description', '').lower()
                    for term in search_terms:
                        if len(term) > 2 and (term in title or term in desc):
                            related.append(f"- {item.get('title', '')[:100]} ({item.get('url', '')})")
                            break
                if related:
                    news_context = "\nRelated news:\n" + "\n".join(related[:3])

            # Skip LLM — use rule-based analysis instead (much faster)
            if gem['vol_mcap_ratio'] > 0.3:
                gem['analysis'] = f"Volume sangat tinggi ({gem['vol_mcap_ratio']:.2f}x MC) tapi harga masih flat. Indikasi akumulasi."
            elif gem['ath_drop'] > 70:
                gem['analysis'] = f"Turun {gem['ath_drop']:.0f}% dari ATH, volume mulai masuk. Potensi bottom formation."
            elif gem['vol_mcap_ratio'] > 0.15:
                gem['analysis'] = f"Volume/MC ratio {gem['vol_mcap_ratio']:.2f} — ada aktivitas tidak biasa."
            else:
                gem['analysis'] = f"Signal: {gem['gem_type']}. Cek lebih lanjut di CoinGecko/CoinMarketCap."

            from duckscreeener.db.database import store_signal
            store_signal(
                symbol=gem['symbol'],
                entry_price=gem['price'],
                source_type='scan',
                signal_type=gem['gem_type'],
                market_cap=gem['market_cap'],
                volume=gem['volume'],
                score=int(gem['vol_mcap_ratio'] * 100),
                narrative=None,
                analysis=gem.get('analysis', '')[:500],
            )

        return potential_gems[:10]

    except Exception as e:
        logger.error(f"Coin scan error: {e}")
        return []


def get_solana_token_data():
    try:
        url = "https://api.dexscreener.com/latest/dex/tokens/solana"
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data
        return None
    except Exception as e:
        logger.error(f"Failed to get Solana token data: {e}")
        return None


def scan_smart_wallets():
    global SOLANA_SENT_ALERTS

    try:
        token_data = get_solana_token_data()
        recent_alerts = []

        if token_data and 'pairs' in token_data:
            pairs = token_data.get('pairs', [])

            for pair in pairs[:100]:
                try:
                    liquidity = float(pair.get('liquidity', {}).get('usd', 0) or 0)
                    volume_24h = float(pair.get('volume', {}).get('h24', 0) or 0)
                    price_change = float(pair.get('priceChange', {}).get('h24', 0) or 0)

                    base_token = pair.get('baseToken', {})
                    token_address = base_token.get('address', '')

                    if token_address in SOLANA_SENT_ALERTS:
                        continue

                    is_early = False
                    alert_type = ""

                    if liquidity >= 2000 and volume_24h > 5000 and price_change > 5:
                        is_early = True
                        alert_type = "NEW PAIR"
                    elif liquidity > 10000 and volume_24h > 20000 and price_change > 10:
                        is_early = True
                        alert_type = "STRONG MOMENTUM"
                    elif liquidity < 100000 and price_change > 30 and volume_24h > 3000:
                        is_early = True
                        alert_type = "MOONSHOT CANDIDATE"

                    if is_early and token_address:
                        SOLANA_SENT_ALERTS.add(token_address)

                        token_name = base_token.get('name', 'Unknown')
                        token_symbol = base_token.get('symbol', '???')

                        dex_screener_url = f"https://dexscreener.com/solana/{token_address}"
                        raydium_url = f"https://raydium.io/swap/?inputCurrency=sol&outputCurrency={token_address}"

                        recent_alerts.append({
                            'name': token_name,
                            'symbol': token_symbol,
                            'price': pair.get('priceUsd', '0'),
                            'price_change_24h': price_change,
                            'liquidity': liquidity,
                            'volume_24h': volume_24h,
                            'dex': pair.get('dexId', 'unknown'),
                            'token_address': token_address,
                            'alert_type': alert_type,
                            'dex_screener_url': dex_screener_url,
                            'raydium_url': raydium_url
                        })
                except Exception:
                    continue

        return recent_alerts[:5]

    except Exception as e:
        logger.error(f"Solana scan failed: {e}")
        return []


def fetch_gmgn_tokens(chain='sol', time_period='1h', orderby='smartmoney', limit=50):
    try:
        url = f"{GMGN_API_URL}/{chain}/swaps/{time_period}"
        params = {
            'orderby': orderby,
            'direction': 'desc',
            'limit': limit
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'https://gmgn.ai/'
        }
        resp = requests.get(url, params=params, headers=headers, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == 0:
                return data.get('data', {}).get('rank', [])
        elif resp.status_code == 403:
            logger.warning("GMGN API 403 - trying DexScreener fallback")

        # DexScreener fallback - use multiple targeted queries for memecoins
        tokens = []
        seen_addresses = set()

        search_queries = ["solana", "sol memecoin", "sol meme"]
        for query in search_queries:
            try:
                sol_url = f"https://api.dexscreener.com/latest/dex/search?q={query}"
                sol_resp = requests.get(sol_url, timeout=15)
                if sol_resp.status_code != 200:
                    continue
                sol_data = sol_resp.json()
                pairs = sol_data.get('pairs') or []

                for pair in pairs:
                    base = pair.get('baseToken', {})
                    token_address = base.get('address', '')
                    symbol = base.get('symbol', '').upper()
                    if not token_address or not symbol or token_address in seen_addresses:
                        continue

                    chain_id = pair.get('chainId', '')
                    if chain_id != 'solana':
                        continue

                    volume = float(pair.get('volume', {}).get('h24', 0) or 0)
                    liquidity = float(pair.get('liquidity', {}).get('usd', 0) or 0)
                    fdv = float(pair.get('fdv', 0) or 0)

                    if not is_memecoin(symbol, base.get('name', ''), fdv, liquidity):
                        continue

                    seen_addresses.add(token_address)

                    tokens.append({
                        'address': token_address,
                        'symbol': symbol,
                        'name': base.get('name', ''),
                        'price': float(pair.get('priceUsd', 0) or 0),
                        'price_change_1h': float(pair.get('priceChange', {}).get('h1', 0) or 0),
                        'volume': volume,
                        'liquidity': liquidity,
                        'market_cap': fdv,
                        'holder_count': 0,
                        'smart_buy_24h': int(volume // 10000),
                        'smart_sell_24h': 0,
                        'is_honeypot': False,
                        'is_verified': False
                    })
            except Exception:
                continue

        tokens.sort(key=lambda x: x['volume'], reverse=True)
        return tokens[:limit]
    except Exception as e:
        logger.error(f"Failed to fetch GMGN tokens: {e}")
        return []


def scan_gmgn_tokens():
    global GMGN_SENT_ALERTS

    alerts = []

    try:
        tokens = fetch_gmgn_tokens(chain='sol', time_period='1h', orderby='smartmoney', limit=50)

        for token in tokens:
            try:
                token_address = token.get('address', '')
                if not token_address or token_address in GMGN_SENT_ALERTS:
                    continue

                if token_address.startswith('0x'):
                    continue

                symbol = token.get('symbol', '').upper()
                name = token.get('name', '')
                price = float(token.get('price', 0))
                volume_24h = float(token.get('volume', 0))
                liquidity = float(token.get('liquidity', 0))
                market_cap = float(token.get('market_cap', 0))
                holder_count = int(token.get('holder_count', 0))
                smart_buy_24h = int(token.get('smart_buy_24h', 0))
                smart_sell_24h = int(token.get('smart_sell_24h', 0))
                price_change_1h = float(token.get('price_change_1h', 0))

                if not is_memecoin(symbol, name, market_cap, liquidity):
                    continue

                if smart_buy_24h < 3 and volume_24h < 10000:
                    continue

                is_honeypot = token.get('is_honeypot', False)
                is_verified = token.get('is_verified', False)

                alert_type = ""
                is_early = False

                if holder_count > 0 and holder_count < 100 and smart_buy_24h >= 5:
                    alert_type = "EARLY GEM"
                    is_early = True
                elif smart_buy_24h >= smart_sell_24h * 2 and smart_buy_24h >= 10:
                    alert_type = "WHALE BUYING"
                    is_early = True
                elif volume_24h > 30000 and price_change_1h > 10:
                    alert_type = "TRENDING"
                    is_early = True
                elif market_cap > 0 and market_cap < 500000 and price_change_1h > 20:
                    alert_type = "MOONSHOT"
                    is_early = True

                if is_early:
                    symbol = token.get('symbol', '').upper()
                    name = token.get('name', '')

                    alerts.append({
                        'token_address': token_address,
                        'symbol': symbol,
                        'name': name,
                        'price': price,
                        'price_change_1h': price_change_1h,
                        'volume_24h': volume_24h,
                        'liquidity': liquidity,
                        'market_cap': market_cap,
                        'holder_count': holder_count,
                        'smart_buy_24h': smart_buy_24h,
                        'smart_sell_24h': smart_sell_24h,
                        'alert_type': alert_type,
                        'is_honeypot': is_honeypot,
                        'is_verified': is_verified,
                        'gmgn_url': f"https://gmgn.ai/sol/token/{token_address}"
                    })

                    GMGN_SENT_ALERTS.add(token_address)

                    if len(GMGN_SENT_ALERTS) > 100:
                        GMGN_SENT_ALERTS = set(list(GMGN_SENT_ALERTS)[-100:])
            except Exception:
                continue

        return alerts

    except Exception as e:
        logger.error(f"GMGN scan error: {e}")
        return []


def get_trending_memecoins_for_command():
    """Fetch real-time trending memecoin data for /memecoin command"""
    try:
        tokens = fetch_gmgn_tokens(chain='sol', time_period='1h', orderby='volume', limit=20)

        if not tokens:
            sol_url = "https://api.dexscreener.com/latest/dex/search?q=solana+memecoin"
            sol_resp = requests.get(sol_url, timeout=15)
            if sol_resp.status_code == 200:
                sol_data = sol_resp.json()
                pairs = sol_data.get('pairs') or []
                for pair in pairs[:20]:
                    base = pair.get('baseToken', {})
                    volume = float(pair.get('volume', {}).get('h24', 0) or 0)
                    tokens.append({
                        'address': base.get('address', ''),
                        'symbol': base.get('symbol', '').upper(),
                        'name': base.get('name', ''),
                        'price': float(pair.get('priceUsd', 0) or 0),
                        'price_change_1h': float(pair.get('priceChange', {}).get('h1', 0) or 0),
                        'volume': volume,
                        'liquidity': float(pair.get('liquidity', {}).get('usd', 0) or 0),
                        'market_cap': float(pair.get('fdv', 0) or 0),
                    })

        if not tokens:
            return None

        top_tokens = sorted(tokens, key=lambda x: x.get('volume', 0), reverse=True)[:10]

        data_summary = "Trending Solana Memecoins (real-time data):\n\n"
        for i, t in enumerate(top_tokens, 1):
            data_summary += (
                f"{i}. {t.get('name', 'Unknown')} ({t.get('symbol', '?')})\n"
                f"   Price: ${t.get('price', 0):.8f}\n"
                f"   1h Change: {t.get('price_change_1h', 0):.1f}%\n"
                f"   Volume 24h: ${t.get('volume', 0)/1000:.1f}K\n"
                f"   Liquidity: ${t.get('liquidity', 0)/1000:.1f}K\n"
                f"   Address: {t.get('address', 'N/A')}\n\n"
            )

        return data_summary
    except Exception as e:
        logger.error(f"Failed to get trending memecoins: {e}")
        return None


def make_rpc_request(method, params, timeout=30):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        resp = requests.post(
            SOLANA_RPC_URL,
            json=payload,
            headers=SOLANA_RPC_HEADERS,
            timeout=timeout
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        logger.error(f"RPC error: {e}")
        return None


def get_wallet_transactions(wallet_address, limit=20):
    try:
        sigs_resp = make_rpc_request("getSignaturesForAddress", [
            wallet_address,
            {"limit": limit}
        ])

        if not sigs_resp or 'result' not in sigs_resp:
            return []

        signatures = [s['signature'] for s in sigs_resp['result']]

        tx_details = []
        for sig in signatures[:10]:
            tx_resp = make_rpc_request("getTransaction", [sig, {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0
            }])

            if tx_resp and 'result' in tx_resp and tx_resp['result']:
                tx = tx_resp['result']
                tx_details.append({
                    'signature': sig,
                    'slot': tx.get('slot'),
                    'blockTime': tx.get('blockTime'),
                    'meta': tx.get('meta', {}),
                    'transaction': tx.get('transaction', {})
                })

        return tx_details
    except Exception as e:
        logger.error(f"Get tx error: {e}")
        return []


def analyze_wallet_activity(wallet_address):
    try:
        txs = get_wallet_transactions(wallet_address, limit=15)

        if not txs:
            return None

        activity = {
            'recent_txs': len(txs),
            'last_activity': txs[0].get('blockTime'),
            'tokens_traded': set(),
            'total_volume': 0
        }

        for tx in txs:
            meta = tx.get('meta', {})
            post_token_balances = meta.get('postTokenBalances', [])
            pre_token_balances = meta.get('preTokenBalances', [])

            for bal in post_token_balances:
                mint = bal.get('mint', '')
                if mint and mint != 'So11111111111111111111111111111111111111112':
                    activity['tokens_traded'].add(mint)

            try:
                pre_sol = float(pre_token_balances[0].get('uiTokenAmount', {}).get('uiAmountString', '0')) if pre_token_balances else 0
                post_sol = float(post_token_balances[0].get('uiTokenAmount', {}).get('uiAmountString', '0')) if post_token_balances else 0
                activity['total_volume'] += abs(post_sol - pre_sol)
            except:
                pass

        activity['tokens_traded'] = list(activity['tokens_traded'])

        token_details = []
        for mint in activity['tokens_traded'][:5]:
            info = get_token_info(mint)
            if info:
                token_details.append(info)

        activity['token_details'] = token_details

        return activity

    except Exception as e:
        logger.error(f"Wallet analysis error: {e}")
        return None


def get_token_info(mint_address):
    try:
        dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{mint_address}"
        dex_resp = requests.get(dex_url, timeout=10)
        if dex_resp.status_code == 200:
            data = dex_resp.json()
            pairs = data.get('pairs') or []
            if pairs:
                pair = pairs[0]
                base = pair.get('baseToken', {})
                return {
                    'mint': mint_address,
                    'symbol': base.get('symbol', '?'),
                    'name': base.get('name', '?'),
                    'price': pair.get('priceUsd', '0'),
                    'liquidity': pair.get('liquidity', {}).get('usd', 0)
                }

        return {'mint': mint_address, 'symbol': 'Unknown'}
    except Exception:
        return {'mint': mint_address, 'symbol': 'Unknown'}
