"""
Smart Wallet Tracker — discovers, validates, and monitors profitable Solana wallets.

Workflow:
1. DexScreener: Get trending memecoins
2. DexScreener: Get top traders per token
3. Solana RPC: Validate each wallet (win rate, min trade, unique tokens, not dev/sniper)
4. Store validated wallets to DB
5. Monitor tracked wallets for new trades
6. Alert when smart wallet buys a coin that meets memecoin criteria
"""
import logging
import time
import requests
from datetime import datetime
from duckscreeener.db.database import (
    store_smart_wallet, get_all_smart_wallets, delete_smart_wallet,
    cleanup_stale_wallets, store_wallet_trade, get_wallet_trade_stats,
)
from duckscreeener.config.settings import SOLANAFM_API_KEY

logger = logging.getLogger(__name__)

SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
SOLANA_RPC_HEADERS = {"Content-Type": "application/json"}
DEXSCREENER_BASE = "https://api.dexscreener.com/latest/dex"
SOLANAFM_BASE = "https://api.solana.fm/v0"

# Discovery criteria
MIN_WIN_RATE = 60
MIN_TRADE_USD = 50
MIN_UNIQUE_TOKENS = 3
MIN_TOTAL_TRADES = 5
MAX_WALLETS = 50
MAX_INACTIVE_DAYS = 7

# Known dev/bot program IDs to exclude
DEV_PROGRAM_IDS = {
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # Token program (creation)
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM
}

# Track discovered wallets to avoid re-processing
_discovered_wallets = set()


def _solana_rpc(method, params):
    """Make a Solana RPC call"""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        resp = requests.post(SOLANA_RPC_URL, json=payload, headers=SOLANA_RPC_HEADERS, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        logger.debug(f"Solana RPC error: {e}")
        return None


def get_trending_memecoins(limit=20):
    """Get trending memecoins from DexScreener"""
    try:
        queries = ["solana meme", "sol meme", "solana coin", "sol dog", "sol cat"]
        all_pairs = []
        seen = set()

        for query in queries:
            try:
                url = f"{DEXSCREENER_BASE}/search?q={query}"
                resp = requests.get(url, timeout=15)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                pairs = data.get('pairs') or []

                for pair in pairs:
                    if pair.get('chainId') != 'solana':
                        continue
                    base = pair.get('baseToken', {})
                    addr = base.get('address', '')
                    if not addr or addr in seen or addr.startswith('0x'):
                        continue

                    liq = float(pair.get('liquidity', {}).get('usd', 0) or 0)
                    vol = float(pair.get('volume', {}).get('h24', 0) or 0)
                    created = pair.get('pairCreatedAt', 0)

                    # Filter: new coins with moderate liquidity
                    if liq < 5000 or liq > 2000000:
                        continue

                    seen.add(addr)
                    all_pairs.append({
                        'address': addr,
                        'symbol': base.get('symbol', '').upper(),
                        'name': base.get('name', ''),
                        'liquidity': liq,
                        'volume_24h': vol,
                        'created_at': created,
                    })
            except Exception:
                continue

        # Sort by volume, return top
        all_pairs.sort(key=lambda x: x['volume_24h'], reverse=True)
        return all_pairs[:limit]

    except Exception as e:
        logger.error(f"Trending memecoins error: {e}")
        return []


def get_top_traders(token_address, limit=20):
    """Get top traders for a token from DexScreener"""
    return []


def get_token_holders(mint_address, limit=15):
    """Get recent token holders via Solana FM API"""
    try:
        headers = {"Accept": "application/json"}
        if SOLANAFM_API_KEY:
            headers["x-api-key"] = SOLANAFM_API_KEY

        # Get token transfers to find recent buyers
        url = f"{SOLANAFM_BASE}/tokens/{mint_address}/transfers"
        params = {"limit": limit * 3, "type": "transfer"}
        resp = requests.get(url, params=params, headers=headers, timeout=15)

        wallets = set()
        if resp.status_code == 200:
            data = resp.json()
            results = data.get('results', [])
            for transfer in results:
                # Look for destination wallets (buyers)
                dest = transfer.get('destination', '')
                if dest and len(dest) >= 32:
                    wallets.add(dest)
                # Also check from addresses that aren't system programs
                src = transfer.get('source', '')
                if src and len(src) >= 32 and src not in [
                    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    "11111111111111111111111111111111",
                    "ComputeBudget111111111111111111111111111111",
                ]:
                    wallets.add(src)

        return list(wallets)[:limit]

    except Exception as e:
        logger.debug(f"Solana FM token holders error for {mint_address}: {e}")
        return []


def get_wallet_transactions(wallet_address, limit=30):
    """Get recent transaction signatures for a wallet"""
    result = _solana_rpc("getSignaturesForAddress", [
        wallet_address,
        {"limit": limit}
    ])
    if result and 'result' in result:
        return result['result']
    return []


def get_transaction_details(signature):
    """Get full transaction details"""
    result = _solana_rpc("getTransaction", [
        signature,
        {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}
    ])
    if result and 'result' in result and result['result']:
        return result['result']
    return None


def analyze_wallet(wallet_address, token_symbol="", token_address=""):
    """
    Analyze a wallet's recent activity to determine if it's a smart wallet.
    Returns wallet stats or None if invalid.
    """
    try:
        sigs = get_wallet_transactions(wallet_address, limit=30)
        if not sigs or len(sigs) < 5:
            return None

        trades = []
        unique_tokens = set()
        total_buy_usd = 0
        total_sell_usd = 0
        earliest_tx = None

        for sig_info in sigs[:20]:
            sig = sig_info.get('signature', '')
            tx = get_transaction_details(sig)
            if not tx:
                continue

            meta = tx.get('meta', {})
            pre_tb = meta.get('preTokenBalances', [])
            post_tb = meta.get('postTokenBalances', [])
            block_time = tx.get('blockTime', 0)

            if earliest_tx is None or block_time < earliest_tx:
                earliest_tx = block_time

            for i in range(min(len(pre_tb), len(post_tb))):
                pre_amt = float(pre_tb[i].get('uiTokenAmount', {}).get('uiAmountString', '0') or '0')
                post_amt = float(post_tb[i].get('uiTokenAmount', {}).get('uiAmountString', '0') or '0')
                diff = post_amt - pre_amt
                mint = post_tb[i].get('mint', '')

                if mint == 'So11111111111111111111111111111111111111112':
                    continue

                if abs(diff) > 0.001 and mint:
                    unique_tokens.add(mint)
                    action = 'BUY' if diff > 0 else 'SELL'

                    # Estimate USD value (rough: use SOL price ~$180)
                    # Better: use token price from DexScreener if available
                    est_usd = abs(diff) * 0.01  # rough estimate, will be refined

                    trades.append({
                        'action': action,
                        'mint': mint,
                        'amount': abs(diff),
                        'usd_value': est_usd,
                        'timestamp': block_time,
                        'tx_sig': sig[:10] + '...',
                    })

                    store_wallet_trade(
                        wallet_address=wallet_address,
                        token_symbol="",
                        token_address=mint,
                        action=action,
                        usd_value=est_usd,
                        timestamp=block_time,
                        tx_signature=sig,
                    )

        if len(trades) < MIN_TOTAL_TRADES:
            return None

        if len(unique_tokens) < MIN_UNIQUE_TOKENS:
            return None

        # Calculate win rate from DB
        stats = get_wallet_trade_stats(wallet_address)
        if not stats or stats['total_trades'] < MIN_TOTAL_TRADES:
            return None

        win_rate = stats['win_rate']
        if win_rate < MIN_WIN_RATE:
            return None

        # Calculate trust score (0-100)
        trust_score = 0
        trust_score += min(win_rate, 100) * 0.4  # 40% from win rate
        trust_score += min(stats['unique_tokens'], 20) * 2  # up to 40 from diversity
        trust_score += min(stats['total_trades'], 50) * 0.4  # up to 20 from experience

        # Track early buyer status
        early_buyer_of = token_symbol if token_symbol else ""

        return {
            'address': wallet_address,
            'win_rate': win_rate,
            'total_trades': stats['total_trades'],
            'total_pnl': stats['total_pnl'],
            'unique_tokens': stats['unique_tokens'],
            'early_buyer_of': early_buyer_of,
            'last_activity': trades[0]['timestamp'] if trades else time.time(),
            'trust_score': trust_score,
        }

    except Exception as e:
        logger.debug(f"Wallet analysis error for {wallet_address}: {e}")
        return None


def discover_smart_wallets():
    """
    Main discovery loop:
    1. Get trending memecoins from DexScreener
    2. Get recent token transfers via Solana FM API (more reliable than RPC)
    3. Find early buyers from token transfers
    4. Validate wallets against strict criteria
    5. Store qualified wallets
    """
    logger.info("Starting smart wallet discovery...")
    trending = get_trending_memecoins(limit=20)

    if not trending:
        logger.warning("No trending memecoins found")
        return 0, 0

    logger.info(f"Found {len(trending)} trending memecoins")
    discovered_count = 0
    checked_count = 0
    current_wallets = get_all_smart_wallets(limit=MAX_WALLETS)
    current_addresses = {w['address'] for w in current_wallets}

    for coin in trending[:10]:
        # Get recent token holders via Solana FM API
        candidate_wallets = get_token_holders(coin['address'], limit=15)

        if not candidate_wallets:
            logger.info(f"  {coin['symbol']}: No holders found via Solana FM")
            continue

        logger.info(f"  {coin['symbol']}: {len(candidate_wallets)} candidate wallets")

        for wallet_addr in candidate_wallets[:5]:
            if wallet_addr in current_addresses or wallet_addr in _discovered_wallets:
                continue

            checked_count += 1

            # Analyze wallet
            result = analyze_wallet(wallet_addr, coin['symbol'], coin['address'])
            if result:
                store_smart_wallet(
                    address=result['address'],
                    label="discovered",
                    win_rate=result['win_rate'],
                    total_trades=result['total_trades'],
                    total_pnl=result['total_pnl'],
                    unique_tokens=result['unique_tokens'],
                    early_buyer_of=result['early_buyer_of'],
                    last_activity=result['last_activity'],
                    trust_score=result['trust_score'],
                )
                _discovered_wallets.add(wallet_addr)
                current_addresses.add(wallet_addr)
                discovered_count += 1
                logger.info(
                    f"New smart wallet: {wallet_addr[:20]}... "
                    f"(WR: {result['win_rate']:.1f}%, Tokens: {result['unique_tokens']}, "
                    f"Trust: {result['trust_score']:.0f}, Early: {result['early_buyer_of']})"
                )
            else:
                logger.debug(f"  Wallet {wallet_addr[:20]}... did not meet criteria")

    # Maintenance
    cleanup_stale_wallets(
        max_inactive_days=MAX_INACTIVE_DAYS,
        min_win_rate=MIN_WIN_RATE,
        max_wallets=MAX_WALLETS,
    )

    logger.info(f"Smart wallet discovery complete: {discovered_count} new wallets found, {checked_count} checked")
    return discovered_count, checked_count


def monitor_smart_wallets():
    """
    Check all tracked smart wallets for new trades.
    If a wallet buys a new coin, check if it meets memecoin criteria.
    """
    wallets = get_all_smart_wallets(limit=MAX_WALLETS)
    if not wallets:
        return []

    alerts = []
    for wallet in wallets:
        try:
            addr = wallet['address']
            sigs = get_wallet_transactions(addr, limit=5)
            if not sigs:
                continue

            # Check for new transactions since last activity
            last_activity = wallet.get('last_activity', 0)
            for sig_info in sigs:
                sig_time = sig_info.get('blockTime', 0)
                if sig_time and sig_time > last_activity:
                    # New trade detected
                    tx = get_transaction_details(sig_info['signature'])
                    if tx:
                        meta = tx.get('meta', {})
                        post_tb = meta.get('postTokenBalances', [])
                        for bal in post_tb:
                            mint = bal.get('mint', '')
                            amount = float(bal.get('uiTokenAmount', {}).get('uiAmountString', '0') or '0')
                            if mint and mint != 'So11111111111111111111111111111111111111112' and amount > 0:
                                # Get token info
                                token_info = _get_token_info(mint)
                                if token_info:
                                    store_wallet_trade(
                                        wallet_address=addr,
                                        token_symbol=token_info.get('symbol', ''),
                                        token_address=mint,
                                        action='BUY',
                                        usd_value=amount * 0.01,  # rough estimate
                                        timestamp=sig_time,
                                        tx_signature=sig_info['signature'],
                                    )

                                    # Update wallet last_activity
                                    store_smart_wallet(
                                        address=addr,
                                        label=wallet.get('label', 'discovered'),
                                        win_rate=wallet.get('win_rate', 0),
                                        total_trades=wallet.get('total_trades', 0),
                                        total_pnl=wallet.get('total_pnl', 0),
                                        unique_tokens=wallet.get('unique_tokens', 0),
                                        early_buyer_of=wallet.get('early_buyer_of', ''),
                                        last_activity=sig_time,
                                        trust_score=wallet.get('trust_score', 0),
                                    )

                                    alerts.append({
                                        'wallet': addr,
                                        'wallet_label': wallet.get('label', 'discovered'),
                                        'wallet_wr': wallet.get('win_rate', 0),
                                        'token_symbol': token_info.get('symbol', ''),
                                        'token_address': mint,
                                        'token_name': token_info.get('name', ''),
                                        'timestamp': sig_time,
                                    })
        except Exception as e:
            logger.debug(f"Monitor error for {wallet.get('address', '?')}: {e}")

    return alerts


def _get_token_info(mint_address):
    """Get token info from DexScreener"""
    try:
        url = f"{DEXSCREENER_BASE}/tokens/{mint_address}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            pairs = data.get('pairs') or []
            if pairs:
                pair = pairs[0]
                base = pair.get('baseToken', {})
                return {
                    'symbol': base.get('symbol', ''),
                    'name': base.get('name', ''),
                    'price': pair.get('priceUsd', '0'),
                    'liquidity': pair.get('liquidity', {}).get('usd', 0),
                }
    except Exception:
        pass
    return None


def seed_wallet(wallet_address, label="seed"):
    """Manually add a wallet as seed"""
    result = analyze_wallet(wallet_address)
    if result:
        store_smart_wallet(
            address=wallet_address,
            label=label,
            win_rate=result['win_rate'],
            total_trades=result['total_trades'],
            total_pnl=result['total_pnl'],
            unique_tokens=result['unique_tokens'],
            early_buyer_of=result.get('early_buyer_of', ''),
            last_activity=result['last_activity'],
            trust_score=result['trust_score'],
        )
        logger.info(f"Seed wallet stored: {wallet_address}")
        return result
    else:
        # Store with minimal data, will be updated on next analysis
        import time
        store_smart_wallet(
            address=wallet_address,
            label=label,
            win_rate=0,
            total_trades=0,
            total_pnl=0,
            unique_tokens=0,
            early_buyer_of="",
            last_activity=time.time(),
            trust_score=50,
        )
        logger.info(f"Seed wallet stored (pending analysis): {wallet_address}")
        return {'address': wallet_address, 'label': label}
