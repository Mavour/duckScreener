import logging
import os
import tempfile
import re
import asyncio
import time
from duckscreeener.config.settings import (
    BOT_LANGUAGE, TELEGRAM_TOKEN, OPENROUTER_API_KEY, SOLANA_SMART_WALLETS,
)
from duckscreeener.db.database import (
    store_knowledge, search_knowledge, count_knowledge, get_recent_knowledge,
    load_list_setting, save_list_setting, get_first_scan_time,
)
from duckscreeener.services.external_apis import (
    openrouter_chat, extract_text_from_pdf, extract_text_from_image,
    extract_text_from_youtube, extract_tweet_from_url,
    fetch_latest_news, fetch_tweets, TWEEPY_AVAILABLE, TWITTER_BEARER_TOKEN,
)
from duckscreeener.scanners.coin_scanner import (
    scan_potential_coins, scan_smart_wallets, scan_gmgn_tokens,
    analyze_wallet_activity, get_trending_memecoins_for_command,
)
from duckscreeener.scanners.memecoin_scanner import (
    scan_new_memecoins, get_ai_memecoin_analysis,
)
from duckscreeener.scanners.backtest import run_backtest


async def _run_llm(prompt, system="You are a helpful assistant."):
    """Run LLM call in executor to avoid blocking the async event loop"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: openrouter_chat(prompt, system=system))

logger = logging.getLogger(__name__)

_user_cooldowns = {}
COMMAND_COOLDOWN = 30

def check_cooldown(user_id, command):
    key = f"{user_id}:{command}"
    now = time.time()
    if key in _user_cooldowns and now - _user_cooldowns[key] < COMMAND_COOLDOWN:
        remaining = COMMAND_COOLDOWN - (now - _user_cooldowns[key])
        return f"Please wait {remaining:.0f}s before using this command again."
    _user_cooldowns[key] = now
    return None

USER_ADDED_WALLETS = load_list_setting("user_added_wallets", [])
TRUSTED_TWITTER_ACCOUNTS = load_list_setting("trusted_twitter_accounts", [])


def _save_wallets():
    save_list_setting("user_added_wallets", USER_ADDED_WALLETS)


def _save_trusted():
    save_list_setting("trusted_twitter_accounts", TRUSTED_TWITTER_ACCOUNTS)


def translate(key):
    strings = {
        "start_both": {
            "en": """Welcome to Crypto Agent Bot!

I'm your AI-powered crypto assistant. Here's what I can do:

NEWS & ANALYSIS
/summary - Get daily crypto news summary

COIN SCREENING
/scan - Detect whale accumulation on CEX (auto every 6h + manual)

MEMECOIN SCANNER
/memecoin - Find new memecoins before they pump
/memecoin_ai - Scan + AI analysis

WALLET TRACKER
/wallet_analyze <addr> - Analyze specific wallet
/wallet_scan - Scan all tracked wallets
/wallet_list - List tracked wallets
/wallet_add <addr> - Add wallet to track
/wallet_remove <addr> - Remove wallet

KNOWLEDGE & TOOLS
/learn - Learn from PDF/image/link
/memory - View stored knowledge
/search <query> - Search knowledge base
/create_agent - Create custom AI agent

BACKTEST
/backtest - Check signal performance

SETTINGS
/health - Bot health status
/set_lang <en|id> - Change language

Just type naturally! I understand what you mean.""",
            "id": """Selamat Datang di Crypto Agent Bot!

Saya adalah asisten crypto AI Anda. Ini yang bisa saya lakukan:

BERITA & ANALISIS
/summary - Ringkasan berita crypto harian

SCREENING COIN
/scan - Deteksi akumulasi whale di CEX (auto 6 jam + manual)

MEMECOIN SCANNER
/memecoin - Cari memecoin baru sebelum pump
/memecoin_ai - Scan + analisis AI

WALLET TRACKER
/wallet_analyze <alamat> - Analisa wallet tertentu
/wallet_scan - Scan semua wallet tracker
/wallet_list - Lihat list wallet
/wallet_add <alamat> - Tambah wallet
/wallet_remove <alamat> - Hapus wallet

KNOWLEDGE & TOOLS
/learn - Belajar dari PDF/gambar/link
/memory - Lihat knowledge base
/search <query> - Cari di knowledge base
/create_agent - Buat AI agent kustom

BACKTEST
/backtest - Cek performa sinyal

SETTINGS
/health - Status bot
/set_lang <en|id> - Ganti bahasa

Tulis saja secara natural! Saya paham maksud Anda.""",
        },
        "learn_prompt": {
            "en": "Send me a PDF or an image, and I will extract text, summarize, and learn.",
            "id": "Kirim PDF atau gambar, saya akan mengekstrak teks, meringkas, dan belajar."
        },
        "set_lang_usage": {
            "en": "Usage: /set_lang <en|id|auto>",
            "id": "Cara pakai: /set_lang <en|id|auto>"
        },
        "search_usage": {
            "en": "Usage: /search <query>",
            "id": "Cara pakai: /search <query>"
        },
        "search_results": {
            "en": "Search results for '{query}':",
            "id": "Hasil pencarian untuk '{query}':"
        },
        "search_no_results": {
            "en": "No results found.",
            "id": "Tidak ada hasil."
        },
        "tweets_usage": {
            "en": "Usage: /tweets <keyword or #hashtag> [--coingecko-only | --twitter-only | --trusted]",
            "id": "Cara pakai: /tweets <keyword atau #hashtag> [--coingecko-only | --twitter-only | --trusted]"
        },
        "tweets_results": {
            "en": "Recent tweets about '{query}':",
            "id": "Tweet terbaru tentang '{query}':"
        },
        "tweets_no_results": {
            "en": "No tweets found for that query.",
            "id": "Tidak ada tweets ditemukan untuk query itu."
        },
        "sentiment_usage": {
            "en": "Usage: /sentiment <coin name or symbol>",
            "id": "Cara pakai: /sentiment <nama coin atau symbol>"
        },
        "sentiment_analyzing": {
            "en": "Analyzing sentiment for {coin}...",
            "id": "Menganalisis sentiment untuk {coin}..."
        },
        "sentiment_result": {
            "en": "Sentiment Analysis - {coin}\n\n",
            "id": "Analisis Sentiment - {coin}\n\n"
        },
        "auto_detect": {
            "en": "Auto-detect enabled. Language will switch based on your messages.",
            "id": "Auto-deteksi diaktifkan. Bahasa akan berganti sesuai pesan Anda."
        },
    }
    return strings.get(key, {}).get(BOT_LANGUAGE, strings.get(key, {}).get('en', ''))


def system_prompt(key):
    strings = {
        "summary": {
            "en": "You are a concise crypto news analyst.",
            "id": "Anda adalah analis berita kripto yang ringkas dan menggunakan bahasa Indonesia."
        },
        "screen": {
            "en": "You are a crypto analyst specializing in undervalued assets.",
            "id": "Anda adalah analis kripto yang mengkhususkan diri dalam aset undervalued dengan perspektif Indonesia."
        },
        "memecoin": {
            "en": "You are a crypto analyst focusing on memecoin and on-chain signals.",
            "id": "Anda adalah analis kripto yang fokus pada memecoin dan sinyal on-chain."
        },
        "general": {
            "en": "You are a helpful crypto assistant.",
            "id": "Anda adalah asisten kripto yang membantu dan sopan dalam bahasa Indonesia."
        },
        "agent_architect": {
            "en": "You are an AI agent architect.",
            "id": "Anda adalah arsitek agen AI yang membantu."
        },
    }
    return strings.get(key, {}).get(BOT_LANGUAGE, strings.get(key, {}).get('en', ''))


async def start(update, context):
    user = update.effective_user
    await update.message.reply_text(
        translate("start_both").format(name=user.first_name or "User"),
        parse_mode="Markdown"
    )


async def summary(update, context):
    await update.message.reply_chat_action(action="typing")
    status_msg = await update.message.reply_text("\u23F3 Fetching latest crypto news...")
    from duckscreeener.services.external_apis import fetch_latest_news_with_items

    news_items = fetch_latest_news_with_items(limit=10)
    if not news_items:
        await status_msg.edit_text("No recent crypto news found.")
        return

    news_text = "\n".join([
        f"- {item.get('title', '')}: {item.get('description', '')[:200]}... ({item.get('url', '')})"
        for item in news_items
    ])

    if BOT_LANGUAGE == "id":
        prompt = (
            f"Ringkaslah berita kripto berikut dari 24 jam terakhir dalam 3-4 poin bullet, "
            f"dengan highlight event kunci dan dampak pasar potensial. "
            f"WAJIB: Setiap poin ringkasan HARUS menyertakan link sumber asli. "
            f"RESPOND ENTIRELY IN INDONESIAN:\n\n{news_text}"
        )
    else:
        prompt = (
            f"Summarize the following crypto news from the last 24 hours in 3-4 bullet points, "
            f"highlighting key events and potential market impact. "
            f"IMPORTANT: Each bullet point MUST include the original source link.\n\n{news_text}"
        )

    summary_text = await _run_llm(prompt, system_prompt("summary"))

    from duckscreeener.utils.message_split import send_long_message
    source_links = "\n\nSumber:\n"
    for item in news_items[:5]:
        title = item.get('title', '')[:60]
        url = item.get('url', '')
        if url:
            source_links += f"- [{title}]({url})\n"

    await send_long_message(f"{summary_text}{source_links}", update, parse_mode="Markdown")


async def memecoin(update, context):
    user_id = update.effective_user.id
    cooldown_msg = check_cooldown(user_id, "memecoin")
    if cooldown_msg:
        await update.message.reply_text(cooldown_msg)
        return
    await update.message.reply_chat_action(action="typing")
    status_msg = await update.message.reply_text("\u23F3 Scanning for new memecoins...")

    loop = asyncio.get_event_loop()
    new_coins = await loop.run_in_executor(None, lambda: scan_new_memecoins(hours=12, min_liquidity=5000, max_liquidity=1500000, limit=5))

    if not new_coins:
        await status_msg.edit_text(
            "No promising new memecoins found in the last 12 hours.\n"
            "Market might be quiet. Try again later."
        )
        return

    message = "\U0001F525 NEW MEMECOINS WITH HYPE POTENTIAL\n"
    message += "Scanning for coins BEFORE they pump\n\n"

    for coin in new_coins[:5]:
        if coin['rating'] == 'HIGH':
            rating_emoji = "\U0001F680"
        elif coin['rating'] == 'MEDIUM':
            rating_emoji = "\u26A1"
        else:
            rating_emoji = "\U0001F4CA"
        message += f"{rating_emoji} [{coin['rating']}] Score: {coin['score']}\n"
        message += f"{coin['name']} ({coin['symbol']})\n"
        message += f"\U0001F550 Scanned at: {get_first_scan_time(coin['symbol'], 'memecoin')}\n"
        price_str = f"${coin['price']:.8f}" if coin['price'] < 0.001 else f"${coin['price']:.6f}"
        message += f"\U0001F4B0 Price: {price_str} | 1h: {'+' if coin['price_change_1h'] > 0 else ''}{coin['price_change_1h']:.1f}%\n"
        message += f"\u23F1\uFE0F Age: {coin['age_hours']:.1f}h | \U0001F4A7 Liq: ${coin['liquidity']/1000:.1f}K | \U0001F4B8 MC: ${coin['market_cap']/1000:.1f}K\n"
        message += f"\U0001F4C8 Vol/Liq Ratio: {coin['volume_liq_ratio']:.1f}x\n"
        message += f"\U0001F3F7\uFE0F Narrative: {', '.join(coin['narrative'])}\n"

        if coin['signals']:
            message += f"\u2705 Signals: {'; '.join(coin['signals'][:3])}\n"
        if coin['risks']:
            message += f"\u26A0\uFE0F Risks: {'; '.join(coin['risks'][:2])}\n"

        message += f"\U0001F517 [DexScreener]({coin['dex_screener_url']}) | [GMGN]({coin['gmgn_url']})\n\n"

        from duckscreeener.db.database import store_signal
        store_signal(
            symbol=coin['symbol'],
            entry_price=coin['price'],
            source_type='memecoin',
            signal_type=f"NEW ({coin['age_hours']:.1f}h)",
            token_address=coin['address'],
            market_cap=coin['market_cap'],
            volume=coin['volume_1h'],
            score=coin['score'],
            narrative=', '.join(coin['narrative']),
            analysis='; '.join(coin['signals'][:3]),
        )

    message += "\nDYOR! These are early signals, not financial advice."

    from duckscreeener.utils.message_split import send_long_message
    await send_long_message(message, update, parse_mode="Markdown")


async def memecoin_ai(update, context):
    user_id = update.effective_user.id
    cooldown_msg = check_cooldown(user_id, "memecoin_ai")
    if cooldown_msg:
        await update.message.reply_text(cooldown_msg)
        return
    await update.message.reply_chat_action(action="typing")
    status_msg = await update.message.reply_text("\u23F3 Scanning and analyzing memecoins with AI...")

    loop = asyncio.get_event_loop()
    new_coins = await loop.run_in_executor(None, lambda: scan_new_memecoins(hours=12, min_liquidity=5000, max_liquidity=1500000, limit=5))

    if not new_coins:
        await status_msg.edit_text(
            "No promising new memecoins found in the last 12 hours."
        )
        return

    data_summary = get_ai_memecoin_analysis(new_coins)

    if BOT_LANGUAGE == "id":
        prompt = (
            f"Berdasarkan data memecoin baru berikut, berikan analisis singkat:\n"
            f"1. Top 3 coin dengan potensi hype tertinggi\n"
            f"2. Narasi trending\n"
            f"3. Risiko utama\n"
            f"4. Strategi entry\n\n"
            f"Data:\n{data_summary}\n\n"
            f"Respond entirely in Indonesian. Keep it under 2000 characters."
        )
    else:
        prompt = (
            f"Based on the following new memecoin data, provide brief analysis:\n"
            f"1. Top 3 coins with highest hype potential\n"
            f"2. Trending narratives\n"
            f"3. Main risks\n"
            f"4. Entry strategy\n\n"
            f"Data:\n{data_summary}\n\n"
            f"Keep it under 2000 characters."
        )

    analysis = await _run_llm(prompt, system_prompt("memecoin"))

    from duckscreeener.utils.message_split import send_long_message
    await send_long_message(analysis, update)


async def learn(update, context):
    await update.message.reply_chat_action(action="typing")
    await update.message.reply_text(
        "\U0001F4D6 Send me a PDF or an image, and I will extract text, summarize, and learn."
    )


async def create_agent(update, context):
    await update.message.reply_chat_action(action="typing")
    args = context.args
    if not args:
        if BOT_LANGUAGE == "id":
            await update.message.reply_text(
                "Cara pakai: /create_agent <nama_agent> [deskripsi_singkat].\n"
                "Contoh: /create_agent duck_screener Spot undervalued memecoins dengan risk control."
            )
        else:
            await update.message.reply_text(
                "Usage: /create_agent <agent_name> [brief purpose].\n"
                "Example: /create_agent duck_screener Spot undervalued memecoins with risk control."
            )
        return

    agent_name = args[0]
    purpose = " ".join(args[1:]) if len(args) > 1 else "crypto screening and market insight"

    if BOT_LANGUAGE == "id":
        prompt = (
            f"Buat profil agen yang concise dan practical untuk bot Telegram bernama '{agent_name}'. "
            f"Agen harus specialize dalam {purpose}. "
            "Deskripsikan: 1) mission, 2) primary tasks, 3) persona tone, 4) fail-safe safety reminder. "
            "Respond entirely in Indonesian. Return results dalam short bullet points."
        )
    else:
        prompt = (
            f"Create a concise and practical agent profile for a Telegram bot called '{agent_name}'. "
            f"The agent should specialize in {purpose}. "
            "Describe: 1) mission, 2) primary tasks, 3) persona tone, 4) fail-safe safety reminder. "
            "Return results in short bullet points."
        )

    agent_profile = openrouter_chat(prompt, system=system_prompt("agent_architect"))
    await update.message.reply_text(f"Agent profile for '{agent_name}':\n{agent_profile}")


async def memory(update, context):
    await update.message.reply_chat_action(action="typing")
    status_msg = await update.message.reply_text("\U0001F9E0 Loading knowledge base...")
    total = count_knowledge()
    if total == 0:
        await status_msg.edit_text("\U0001F9E0 Knowledge base is empty.")
        return

    try:
        count = int(context.args[0]) if context.args else 5
        count = max(1, min(20, count))
    except ValueError:
        count = 5

    items = get_recent_knowledge(count)
    lines = ["\U0001F9E0 Memory entries (latest first):\n"]
    for i, item in enumerate(items):
        import time
        ts = time.strftime('%Y-%m-%d %H:%M', time.localtime(item['timestamp']))
        preview = item['text'][:200].replace('\n', ' ')
        source = item['source']

        if source.startswith('pdf:'):
            emoji = "\U0001F4C4"
        elif source.startswith('youtube:'):
            emoji = "\U0001F4FA"
        elif source.startswith('twitter:') or source.startswith('tweet:'):
            emoji = "\U0001F426"
        elif source.startswith('user:'):
            emoji = "\U0001F4AC"
        elif source.startswith('reflection:'):
            emoji = "\U0001F914"
        else:
            emoji = "\U0001F4D6"

        safe_source = source.replace('_', '').replace('*', '').replace('`', '').replace('[', '').replace(']', '').replace('(', '').replace(')', '')
        lines.append(f"{emoji} {i+1}. [{ts}] `{safe_source}`\n{preview}...")

    from duckscreeener.utils.message_split import send_long_message
    await send_long_message("\n\n".join(lines), update)


async def health(update, context):
    await update.message.reply_chat_action(action="typing")
    status_msg = await update.message.reply_text("\U0001F50D Running health check...")
    import time
    from duckscreeener.db.database import get_signal_stats, count_knowledge, get_db

    test_prompt = "Say OK in three words."
    openrouter_answer = await _run_llm(test_prompt, "You are a simple health-check assistant.")
    stored = count_knowledge()
    chat_id = update.effective_chat.id

    db = get_db()
    signal_count = db.execute("SELECT COUNT(*) FROM scan_signals").fetchone()[0]
    outcome_count = db.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0]

    stats = get_signal_stats()
    stats_text = ""
    if stats and stats['total'] > 0:
        stats_text = (
            f"\n\U0001F4CA Signal Stats:\n"
            f"- Total checked: {stats['total']}\n"
            f"- Win rate: {stats['win_rate']:.1f}%\n"
            f"- Avg change: {stats['avg_change']:+.1f}%"
        )

    await update.message.reply_text(
        f"\U0001F50D Health check:\n\n"
        f"\U0001F916 Bot process: connected\n"
        f"\U0001F511 Telegram token: {'set' if TELEGRAM_TOKEN else 'missing'}\n"
        f"\U0001F511 OpenRouter key: {'set' if OPENROUTER_API_KEY else 'missing'}\n"
        f"\U0001F9EA OpenRouter test: {openrouter_answer[:200]}\n"
        f"\U0001F9E0 Knowledge entries: {stored}\n"
        f"\U0001F4CA Scan signals: {signal_count}\n"
        f"\U0001F4C8 Signal outcomes: {outcome_count}{stats_text}\n"
        f"\U0001F464 Your chat_id: `{chat_id}`"
    )


async def search(update, context):
    await update.message.reply_chat_action(action="typing")
    if not context.args:
        await update.message.reply_text(translate("search_usage"))
        return
    query = " ".join(context.args)
    status_msg = await update.message.reply_text(f"\U0001F50D Searching for '{query}'...")

    from duckscreeener.db.vector_search import search_semantic
    results = search_semantic(query, limit=5)

    if not results:
        await status_msg.edit_text(translate("search_no_results"))
        return

    lines = [translate("search_results").format(query=query)]
    for i, item in enumerate(results):
        preview = item['text'][:500].replace('\n', ' ')
        sim = item.get('similarity')
        sim_str = f" ({sim:.2f})" if sim is not None else ""
        lines.append(f"{i+1}. [{item['source']}]{sim_str} {preview}...")

    from duckscreeener.utils.message_split import send_long_message
    await send_long_message("\n\n".join(lines), update)


async def set_lang(update, context):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(translate("set_lang_usage"))
        return
    chosen = context.args[0].lower()
    if chosen == "auto":
        from duckscreeener.config import settings
        settings.AUTO_DETECT_LANG = True
        await update.message.reply_text(translate("auto_detect"))
    elif chosen in ["en", "id"]:
        from duckscreeener.db.database import set_user_language
        set_user_language(user_id, chosen)
        await update.message.reply_text(f"Language set to {chosen}.")
    else:
        await update.message.reply_text(translate("set_lang_usage"))


async def wallet_list(update, context):
    all_wallets = SOLANA_SMART_WALLETS + USER_ADDED_WALLETS
    if all_wallets:
        msg = "Smart Wallets Tracker\n\nBuilt-in:\n"
        for w in SOLANA_SMART_WALLETS:
            msg += f"- `{w[:20]}...`\n"
        if USER_ADDED_WALLETS:
            msg += "\nUser added:\n"
            for w in USER_ADDED_WALLETS:
                msg += f"- `{w[:20]}...`\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("Belum ada smart wallets. Tambahkan via /wallet_add")


async def wallet_add(update, context):
    global USER_ADDED_WALLETS
    if not context.args:
        await update.message.reply_text("Cara pakai: /wallet_add <solana_address>")
        return

    wallet = context.args[0].strip()

    if len(wallet) < 32 or len(wallet) > 44:
        await update.message.reply_text("Invalid Solana address format.")
        return

    if wallet in USER_ADDED_WALLETS:
        await update.message.reply_text("Wallet sudah ada di list.")
        return

    USER_ADDED_WALLETS.append(wallet)
    _save_wallets()
    await update.message.reply_text(f"Wallet ditambahkan:\n`{wallet}`", parse_mode="Markdown")


async def wallet_remove(update, context):
    global USER_ADDED_WALLETS
    if not context.args:
        await update.message.reply_text("Cara pakai: /wallet_remove <solana_address>")
        return

    wallet = context.args[0].strip()
    if wallet not in USER_ADDED_WALLETS:
        await update.message.reply_text("Wallet tidak ada di user list.")
        return

    USER_ADDED_WALLETS.remove(wallet)
    _save_wallets()
    await update.message.reply_text(f"Wallet dihapus: `{wallet}`", parse_mode="Markdown")


async def wallet_analyze(update, context):
    await update.message.reply_chat_action(action="typing")

    if not context.args:
        await update.message.reply_text(
            "Cara pakai: /wallet_analyze <solana_address>\n"
            "Contoh: /wallet_analyze DNfuF1L62WWyW3pNakVkyGGFzVVhj4Yr52jSmdTyeBHm"
        )
        return

    wallet = context.args[0].strip()
    status_msg = await update.message.reply_text(f"\U0001F50D Analyzing wallet...\n`{wallet}`", parse_mode="Markdown")

    activity = analyze_wallet_activity(wallet)

    if not activity:
        await status_msg.edit_text(
            "Tidak dapat mengambil data transaksi.\n"
            "Kemungkinan:\n"
            "- RPC node sedang masalah\n"
            "- Wallet tidak ada di mainnet"
        )
        return

    if activity.get('error'):
        await status_msg.edit_text(
            f"Wallet Analysis\n`{wallet[:32]}...`\n\n"
            f"SOL Balance: {activity['sol_balance']:.4f} SOL\n\n"
            f"No transactions found. This wallet might be new or inactive."
        )
        return

    msg = f"Wallet Analysis\n`{wallet[:32]}...`\n\n"

    # Balance
    msg += f"\U0001F4B0 SOL Balance: {activity['sol_balance']:.4f} SOL\n"
    msg += f"\U0001F4C8 SOL In: {activity['total_sol_in']:.4f} | \U0001F4C9 SOL Out: {activity['total_sol_out']:.4f}\n\n"

    # Wallet age
    age_days = activity.get('wallet_age_days', 0)
    if age_days > 0:
        msg += f"\u23F1\uFE0F Wallet Age: {age_days:.0f} days\n"
    msg += f"\U0001F4CA Recent Transactions: {activity['recent_txs']}\n"

    last_activity = activity.get('last_activity', 0)
    if last_activity:
        from datetime import datetime
        msg += f"\U0001F550 Last Activity: {datetime.fromtimestamp(last_activity).strftime('%Y-%m-%d %H:%M')}\n"

    # Portfolio
    portfolio = activity.get('portfolio', [])
    if portfolio:
        msg += f"\n\U0001F4BC Portfolio ({len(portfolio)} tokens):\n"
        for token in portfolio[:10]:
            symbol = token.get('symbol', '?')
            name = token.get('name', '')
            amount = token.get('amount', 0)
            price = token.get('price', '0')
            liq = token.get('liquidity', 0)

            price_float = float(price) if price and price != '0' else 0
            price_str = f"${price_float:.8f}" if price_float < 0.001 else f"${price_float:.4f}"
            liq_str = f" | Liq: ${liq/1000:.0f}K" if liq > 0 else ""

            msg += f"- {symbol} ({name}): {amount:.0f} @ {price_str}{liq_str}\n"

    # Recent trades
    trades = activity.get('trades', [])
    if trades:
        msg += f"\n\U0001F504 Recent Trades:\n"
        for trade in trades[:10]:
            direction = "\u2705" if trade['direction'] == 'BUY' else "\u274C"
            time_str = datetime.fromtimestamp(trade['time']).strftime('%m/%d %H:%M') if trade.get('time') else '?'
            msg += f"{direction} {trade['direction']} {trade['amount']:.0f} tokens ({time_str}) [{trade['tx_sig']}]\n"

    # Wallet KB history
    wallet_knowledge = search_knowledge(wallet[:20], limit=3)
    if wallet_knowledge:
        msg += f"\n\U0001F4D6 KB History:\n"
        for kb in wallet_knowledge[:3]:
            text = kb['text'][:100]
            msg += f"- {text}...\n"

    from duckscreeener.utils.message_split import send_long_message
    await send_long_message(msg, update, parse_mode="Markdown")


async def wallet_scan(update, context):
    await update.message.reply_chat_action(action="typing")
    status_msg = await update.message.reply_text("\U0001F50D Scanning all tracked wallets...")

    all_wallets = SOLANA_SMART_WALLETS + USER_ADDED_WALLETS

    if not all_wallets:
        await update.message.reply_text("Tidak ada wallets untuk discan.")
        return

    await update.message.reply_text(f"Scanning {len(all_wallets)} wallets...")

    results = []
    for wallet in all_wallets[:5]:
        activity = analyze_wallet_activity(wallet)
        if activity and activity.get('token_details'):
            for token in activity['token_details']:
                results.append({
                    'wallet': wallet[:20],
                    'symbol': token.get('symbol', '?'),
                    'price': token.get('price', '0')
                })

    if not results:
        await update.message.reply_text(
            "Tidak ada token activity terdeteksi.\n"
            "Mungkin wallets sedang tidak trading atau hanya hold posisi."
        )
        return

    msg = "Wallet Scanner Results\n\n"
    for r in results[:10]:
        price = float(r['price']) if r['price'] != '0' else 0
        price_str = f"${price:.6f}" if price < 0.01 else f"${price:.4f}"
        msg += f"- {r['symbol']}: {price_str} (by {r['wallet']}...)\n"

    msg += "\nGanti /wallet_analyze <address> untuk detail"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def scan_coins(update, context):
    user_id = update.effective_user.id
    cooldown_msg = check_cooldown(user_id, "scan")
    if cooldown_msg:
        await update.message.reply_text(cooldown_msg)
        return

    await update.message.reply_chat_action(action="typing")
    status_msg = await update.message.reply_text("Scanning CEX spot for whale accumulation signals...")

    import asyncio
    loop = asyncio.get_event_loop()

    try:
        gems = await loop.run_in_executor(None, scan_potential_coins)
    except Exception as e:
        await status_msg.edit_text(f"Scan error: {e}")
        return

    if not gems:
        await status_msg.edit_text(
            "No accumulation signals found at the moment.\n"
            "Whales might be quiet. Try again later."
        )
        return

    message = "WHALE ACCUMULATION DETECTION\n"
    message += "High volume + flat price = accumulation before pump\n\n"

    for gem in gems:
        price_str = f"${gem['price']:.6f}" if gem['price'] < 1 else f"${gem['price']:.2f}"
        change_24h = f"+{gem['change_24h']:.2f}%" if gem['change_24h'] > 0 else f"{gem['change_24h']:.2f}%"
        volume_str = f"${gem['volume']/1_000_000:.1f}M"
        vm_ratio = gem.get('vol_mcap_ratio', 0)
        ath_drop = gem.get('ath_drop', 0)

        gem_type = gem.get('gem_type', '')
        if 'WHALE' in gem_type:
            gem_emoji = "\U0001F40B"
        elif 'SILENT' in gem_type:
            gem_emoji = "\U0001F92B"
        elif 'EARLY' in gem_type:
            gem_emoji = "\u26A1"
        elif 'DEEP' in gem_type:
            gem_emoji = "\U0001F48E"
        else:
            gem_emoji = "\U0001F50D"

        message += f"{gem_emoji} {gem_type}\n"
        message += f"*{gem['name']} ({gem['symbol']})*\n"
        message += f"\U0001F550 Scanned at: {get_first_scan_time(gem['symbol'], 'scan')}\n"
        message += f"\U0001F4B0 Price: {price_str} | 24h: {change_24h}\n"
        message += f"\U0001F4C8 Vol: {volume_str} | \U0001F4B8 MC: ${gem['market_cap']/1_000_000:.1f}M\n"
        message += f"\U0001F4CA Vol/MC Ratio: {vm_ratio:.2f} (high = unusual activity)\n"
        message += f"\U0001F4C9 From ATH: -{ath_drop:.0f}%\n"
        if gem.get('analysis'):
            message += f"\U0001F4DD Analisis: {gem['analysis'][:200]}\n"
        coin_id = gem.get('coin_id', gem['symbol'].lower())
        message += f"\U0001F517 [CoinGecko](https://www.coingecko.com/en/coins/{coin_id}) | [CoinMarketCap](https://coinmarketcap.com/currencies/{coin_id})\n\n"

    message += "\nDYOR! These are accumulation signals, not financial advice."

    from duckscreeener.utils.message_split import send_long_message
    await send_long_message(message, update, parse_mode="Markdown")


async def run_backtest_command(update, context):
    await update.message.reply_chat_action(action="typing")
    status_msg = await update.message.reply_text("\U0001F4CA Running backtest analysis...")

    try:
        report = run_backtest()
        if report:
            from duckscreeener.utils.message_split import send_long_message
            await send_long_message(report, update, parse_mode="Markdown")
        else:
            await update.message.reply_text("Backtest complete. No signals to evaluate.")
    except Exception as e:
        await update.message.reply_text(f"Backtest error: {e}")


async def handle_message(update, context):
    msg = update.message

    if msg.document:
        await msg.reply_text("Document received. Processing...")
        file_name = msg.document.file_name or "document"
        file = await context.bot.get_file(msg.document.file_id)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1] or ".pdf")
        await file.download_to_drive(temp_file.name)
        try:
            if file_name.lower().endswith(".pdf"):
                text = extract_text_from_pdf(temp_file.name)
            else:
                await msg.reply_text("Only PDF documents are supported currently.")
                return
            store_knowledge(f"pdf:{file_name}", text)
            if text:
                if BOT_LANGUAGE == "id":
                    agent_prompt = (
                        "Anda adalah crypto analyst. Ringkaslah dokumen extracted berikut dalam 3 concise bullet points "
                        "dengan actionable insight dan risk warning. Respond entirely in Indonesian.\n\n" + text[:6000]
                    )
                else:
                    agent_prompt = (
                        "You are a crypto analyst. Summarize the following extracted document in 3 concise bullet points "
                        "with actionable insight and a risk warning.\n\n" + text[:6000]
                    )
                summary = openrouter_chat(agent_prompt, system="You are a crypto knowledge curator.")
                await msg.reply_text(f"Extracted {len(text)} characters from {file_name}.\nSummary:\n{summary}")
            else:
                await msg.reply_text("PDF extracted no text.")
        finally:
            try:
                os.remove(temp_file.name)
            except OSError:
                pass
        return

    if msg.photo:
        await msg.reply_text("Image received. Running OCR and learning...")
        photo = msg.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        await file.download_to_drive(temp_file.name)
        try:
            text = extract_text_from_image(temp_file.name)
            store_knowledge("image", text)
            if text:
                if BOT_LANGUAGE == "id":
                    agent_prompt = (
                        "Anda adalah crypto analyst. Ringkaslah extracted image text dalam 3 bullet points "
                        "dan berikan satu actionable suggestion. Respond entirely in Indonesian.\n\n" + text[:6000]
                    )
                else:
                    agent_prompt = (
                        "You are a crypto analyst. Summarize the extracted image text in 3 bullet points "
                        "and give one actionable suggestion.\n\n" + text[:6000]
                    )
                summary = openrouter_chat(agent_prompt, system="You are a crypto knowledge curator.")
                await msg.reply_text(f"OCR extracted {len(text)} chars.\nSummary:\n{summary}")
            else:
                await msg.reply_text("No text found in image.")
        finally:
            try:
                os.remove(temp_file.name)
            except OSError:
                pass
        return

    if msg.text:
        text = msg.text.strip()

        if text.startswith("/create-agent"):
            payload = text.split(maxsplit=1)
            context.args = payload[1].split() if len(payload) > 1 else []
            return await create_agent(update, context)

        # YouTube link
        if "youtube.com" in text.lower() or "youtu.be" in text.lower():
            await msg.reply_text("YouTube link detected! Fetching video info and learning...")

            try:
                video_info = extract_text_from_youtube(text)
                if video_info.startswith("YouTube extraction failed"):
                    await msg.reply_text(video_info)
                    return

                store_knowledge(f"youtube:{text}", video_info)

                if BOT_LANGUAGE == "id":
                    agent_prompt = (
                        "Anda adalah crypto analyst. Ringkaslah video YouTube berikut dalam 3 concise bullet points "
                        "dengan actionable insight dan relevance ke crypto. Respond entirely in Indonesian.\n\n" + video_info[:6000]
                    )
                else:
                    agent_prompt = (
                        "You are a crypto analyst. Summarize the following YouTube video in 3 concise bullet points "
                        "with actionable insight and relevance to crypto.\n\n" + video_info[:6000]
                    )

                summary = openrouter_chat(agent_prompt, system="You are a crypto knowledge curator.")
                await msg.reply_text(f"Video learned!\n\nSummary:\n{summary}")
            except Exception as e:
                await msg.reply_text(f"Error processing YouTube: {e}")
            return

        # X/Twitter link
        if "x.com" in text.lower() or "twitter.com" in text.lower():
            await msg.reply_text("Link Twitter/X detected! Mengambil dan menganalisa...")

            try:
                tweet_content, username, tweet_id = extract_tweet_from_url(text)

                if not tweet_content:
                    if username and tweet_id:
                        tweet_content = (
                            f"Info Tweet:\n"
                            f"- Username: @{username}\n"
                            f"- Tweet ID: {tweet_id}\n"
                            f"- Link: {text}\n\n"
                            f"Saya tidak dapat mengambil konten tweet langsung. "
                            f"Silakan copy-paste isi tweet nya di sini agar saya bisa analisa!"
                        )
                    else:
                        tweet_content = f"Link: {text}\n\nSilakan share isi tweet nya langsung untuk analisa."

                store_knowledge(f"twitter:{text}", tweet_content)

                if "saya tidak dapat" in tweet_content.lower() or "silakan" in tweet_content.lower() or "cannot" in tweet_content.lower():
                    await msg.reply_text(tweet_content, parse_mode="Markdown")
                    return

                if BOT_LANGUAGE == "id":
                    agent_prompt = (
                        "Anda adalah crypto analyst yang menganalisa tweet/X. "
                        "BERIKAN ANALISA LENGKAP dengan:\n"
                        "1. RINGKASAN: Apa isi utama dari tweet ini?\n"
                        "2. IMPLIKASI: Apa dampak potensial ke market/coin tertentu?\n"
                        "3. RISK: Apa risiko atau warning yang perlu diperhatikan?\n"
                        "4. REKOMENDASI: Apakah ini bullish, bearish, atau neutral?\n\n"
                        f"Tweet content:\n{tweet_content}\n\n"
                        "Respond entirely in Indonesian dengan detail."
                    )
                else:
                    agent_prompt = (
                        "You are a crypto analyst analyzing a tweet/X post. "
                        "PROVIDE DETAILED ANALYSIS with:\n"
                        "1. SUMMARY: What is the main point?\n"
                        "2. IMPLICATION: What's the potential market/coin impact?\n"
                        "3. RISK: What risks or warnings to note?\n"
                        "4. RECOMMENDATION: Is this bullish, bearish, or neutral?\n\n"
                        f"Tweet content:\n{tweet_content}"
                    )

                analysis = openrouter_chat(agent_prompt, system="You are a crypto analyst expert.")

                max_msg_len = 4000
                if len(analysis) > max_msg_len:
                    parts = analysis.split("\n\n")
                    current_msg = ""
                    for part in parts:
                        if len(current_msg) + len(part) > max_msg_len:
                            await msg.reply_text(current_msg.strip(), parse_mode="Markdown")
                            current_msg = part
                        else:
                            current_msg += "\n\n" + part
                    if current_msg.strip():
                        await msg.reply_text(current_msg.strip(), parse_mode="Markdown")
                else:
                    await msg.reply_text(f"Analisa Tweet/X\n\n{analysis}", parse_mode="Markdown")
            except Exception as e:
                await msg.reply_text(f"Error processing Twitter/X: {e}")
            return

        if text.startswith("http"):
            await msg.reply_text(f"Link received: {text[:80]}")
            return

        # Intent-based handling
        from duckscreeener.agent.intent_parser import parse_intent, get_natural_response
        intent, params = parse_intent(text)

        if intent:
            await _handle_intent(update, context, intent, params)
            return

        # General chat — AI conversational response
        user_id = update.effective_user.id
        from duckscreeener.db.database import get_user_language
        user_lang = get_user_language(user_id)

        recent = get_recent_knowledge(5)
        history = "\n".join([f"- {item['source']}: {item['text'][:200]}" for item in recent])

        if user_lang == "id":
            prompt = (
                f"Kamu adalah AI crypto assistant yang ngobrol natural seperti teman diskusi.\n"
                f"Jawab pertanyaan user dengan santai tapi informatif.\n"
                f"Gunakan data dari knowledge base kalau relevan, tapi jangan terlalu kaku.\n"
                f"Kalau user tanya tentang pengalaman belajar kamu, ceritakan dari data yang ada.\n\n"
                f"Data terakhir yang dipelajari:\n{history}\n\n"
                f"Pertanyaan user: {text}\n\n"
                f"Jawab dalam bahasa Indonesia yang natural, seperti ngobrol biasa. "
                f"Jangan sebutkan 'code' atau 'function'. Jangan jawab seperti bot."
            )
            system_msg = "Kamu adalah AI crypto assistant yang ngobrol natural, bukan bot kaku. Jawab seperti teman diskusi yang berpengalaman di crypto."
        else:
            prompt = (
                f"You are a crypto AI assistant that chats naturally like a discussion partner.\n"
                f"Answer the user's question casually but informatively.\n"
                f"Use knowledge base data if relevant, but don't be too rigid.\n"
                f"If user asks about your learning experience, tell them from the data you have.\n\n"
                f"Recent knowledge:\n{history}\n\n"
                f"User question: {text}\n\n"
                f"Answer naturally, like a normal conversation. "
                f"Don't mention 'code' or 'function'. Don't answer like a bot."
            )
            system_msg = "You are a crypto AI assistant that chats naturally, not a stiff bot. Answer like an experienced crypto discussion partner."

        import asyncio
        loop = asyncio.get_event_loop()
        ans = await loop.run_in_executor(None, lambda: openrouter_chat(prompt, system=system_msg))
        await msg.reply_text(ans)

        store_knowledge("user:question", text)


async def _handle_intent(update, context, intent, params):
    """Route intent to the appropriate handler function"""
    msg = update.message

    if intent == "scan_coins":
        await scan_coins(update, context)

    elif intent == "scan_memecoins":
        await memecoin(update, context)

    elif intent == "backtest":
        await run_backtest_command(update, context)

    elif intent == "summary":
        await summary(update, context)

    elif intent == "wallet_analyze":
        if params and params.get('address'):
            context.args = [params['address']]
            await wallet_analyze(update, context)
        else:
            await msg.reply_text("Untuk analisa wallet, berikan address-nya. Contoh: analisa wallet DNfuF1L62WWyW3pNakVkyGGFzVVhj4Yr52jSmdTyeBHm")

    elif intent == "sentiment":
        if params and params.get('coin'):
            coin = params['coin']
            await msg.reply_text(f"Menganalisis sentiment untuk {coin}...")
            from duckscreeener.services.external_apis import fetch_latest_news_with_items
            news_items = fetch_latest_news_with_items(limit=20)
            coin_lower = coin.lower()
            filtered = [n for n in news_items if coin_lower in n.get('title', '').lower() or coin_lower in n.get('description', '').lower()]
            news_text = "\n".join([f"- {n.get('title', '')[:150]}: {n.get('description', '')[:150]}..." for n in filtered[:5]]) if filtered else "No specific news found."
            prompt = f"Analyze market sentiment for '{coin}'. Provide: 1) Overall sentiment (Bullish/Bearish/Neutral) 2) Key highlights 3) Risks 4) Conclusion\n\nNews:\n{news_text}"
            analysis = openrouter_chat(prompt, system="You are a crypto sentiment analyst.")
            await msg.reply_text(f"Sentiment Analysis - {coin}\n\n{analysis}")
        else:
            await msg.reply_text("Sentiment coin apa? Contoh: sentiment BTC")

    elif intent == "search_knowledge":
        query = params.get('query', '') if params else ''
        if query:
            context.args = query.split()
            await search(update, context)
        else:
            await msg.reply_text("Cari apa? Contoh: cari tentang whale accumulation")

    elif intent == "show_memory":
        await memory(update, context)

    elif intent == "help":
        await start(update, context)
