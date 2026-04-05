import logging
import os
import tempfile
import re
from duckscreeener.config.settings import (
    BOT_LANGUAGE, TELEGRAM_TOKEN, OPENROUTER_API_KEY, SOLANA_SMART_WALLETS,
)
from duckscreeener.db.database import (
    store_knowledge, search_knowledge, count_knowledge, get_recent_knowledge,
    load_list_setting, save_list_setting,
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

logger = logging.getLogger(__name__)

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

I'm your AI-powered crypto trading assistant. Here's what I can do:

NEWS & ANALYSIS
/summary - Get daily crypto news summary
/sentiment - Analyze market sentiment for a coin

COIN SCREENING
/screen - Find undervalued coins (whale accumulation, fundamentals)
/scan - Scan for potential gems

MEMECOIN & SOLANA
/memecoin - Find trending memecoins
/solana - Scan Solana smart wallet activity
/gmgn - GMGN/DexScreener memecoin scanner
/wallet_analyze <addr> - Analyze specific wallet
/wallet_scan - Scan all tracked wallets
/wallet_list - List tracked wallets
/wallet_add <addr> - Add wallet to track
/wallet_remove <addr> - Remove wallet

TWITTER/X
/tweets <keyword> - Fetch tweets (use --trusted for verified accounts)
/trust_list - View trusted accounts
/trust_add @user - Add trusted account
/trust_remove @user - Remove trusted account

KNOWLEDGE & TOOLS
/learn - Learn from PDF/image/link
/memory - View stored knowledge
/search <query> - Search knowledge base
/create_agent - Create custom AI agent

BACKTEST & ALERTS
/backtest - Check signal performance
/health - Bot health status

SETTINGS
/set_lang <en|id> - Change language
/help - Show this help message

Just type any command to get started!""",
            "id": """Selamat Datang di Crypto Agent Bot!

Saya adalah asisten trading crypto AI Anda. Ini yang bisa saya lakukan:

BERITA & ANALISIS
/summary - Ringkasan berita crypto harian
/sentiment - Analisis sentiment market untuk coin

SCREENING COIN
/screen - Cari coin yang undervalued
/scan - Scan potential gems

MEMECOIN & SOLANA
/memecoin - Cari trending memecoins
/solana - Scan smart wallet activity di Solana
/gmgn - Scanner memecoin via GMGN/DexScreener
/wallet_analyze <alamat> - Analisa wallet tertentu
/wallet_scan - Scan semua wallet tracker
/wallet_list - Lihat list wallet
/wallet_add <alamat> - Tambah wallet
/wallet_remove <alamat> - Hapus wallet

TWITTER/X
/tweets <keyword> - Ambil tweets (--trusted untuk akun terverifikasi)
/trust_list - Lihat trusted accounts
/trust_add @user - Tambah trusted account
/trust_remove @user - Hapus trusted account

KNOWLEDGE & TOOLS
/learn - Belajar dari PDF/gambar/link
/memory - Lihat knowledge base
/search <query> - Cari di knowledge base
/create_agent - Buat AI agent kustom

BACKTEST & ALERTS
/backtest - Cek performa sinyal
/health - Status kesehatan bot

SETTINGS
/set_lang <en|id> - Ganti bahasa
/help - Tampilkan pesan ini

Cukup ketik command untuk memulai!"""
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
    from duckscreeener.services.external_apis import fetch_latest_news_with_items

    news_items = fetch_latest_news_with_items(limit=10)
    if not news_items:
        await update.message.reply_text("No recent crypto news found.")
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

    summary_text = openrouter_chat(prompt, system=system_prompt("summary"))

    source_links = "\n\nSumber:\n"
    for item in news_items[:5]:
        title = item.get('title', '')[:60]
        url = item.get('url', '')
        if url:
            source_links += f"- [{title}]({url})\n"

    await update.message.reply_text(f"{summary_text}{source_links}", parse_mode="Markdown")


async def memecoin(update, context):
    await update.message.reply_chat_action(action="typing")
    await update.message.reply_text("Scanning for NEW memecoins with hype potential...")

    new_coins = scan_new_memecoins(hours=12, min_liquidity=5000, max_liquidity=1500000, limit=5)

    if not new_coins:
        await update.message.reply_text(
            "No promising new memecoins found in the last 12 hours.\n"
            "Market might be quiet. Try again later."
        )
        return

    message = "NEW MEMECOINS WITH HYPE POTENTIAL\n"
    message += "Scanning for coins BEFORE they pump\n\n"

    for coin in new_coins[:5]:
        message += f"[{coin['rating']}] Score: {coin['score']}\n"
        message += f"{coin['name']} ({coin['symbol']})\n"
        price_str = f"${coin['price']:.8f}" if coin['price'] < 0.001 else f"${coin['price']:.6f}"
        message += f"Price: {price_str} | 1h: {'+' if coin['price_change_1h'] > 0 else ''}{coin['price_change_1h']:.1f}%\n"
        message += f"Age: {coin['age_hours']:.1f}h | Liq: ${coin['liquidity']/1000:.1f}K | MC: ${coin['market_cap']/1000:.1f}K\n"
        message += f"Vol/Liq Ratio: {coin['volume_liq_ratio']:.1f}x\n"
        message += f"Narrative: {', '.join(coin['narrative'])}\n"

        if coin['signals']:
            message += f"Signals: {'; '.join(coin['signals'][:3])}\n"
        if coin['risks']:
            message += f"Risks: {'; '.join(coin['risks'][:2])}\n"

        message += f"[DexScreener]({coin['dex_screener_url']}) | [GMGN]({coin['gmgn_url']})\n\n"

        from duckscreeener.db.database import store_knowledge
        record = (
            f"[NEW MEMECOIN] {coin['name']} ({coin['symbol']}) - "
            f"Price: {price_str}, 1h: {coin['price_change_1h']:.1f}%, "
            f"Age: {coin['age_hours']:.1f}h, Score: {coin['score']}, "
            f"Rating: {coin['rating']}, Narrative: {', '.join(coin['narrative'])}"
        )
        store_knowledge(f"memecoin:{coin['symbol']}", record)

    message += "\nDYOR! These are early signals, not financial advice."

    await update.message.reply_text(message, parse_mode="Markdown")


async def memecoin_ai(update, context):
    await update.message.reply_chat_action(action="typing")
    await update.message.reply_text("Scanning and analyzing new memecoins with AI...")

    new_coins = scan_new_memecoins(hours=12, min_liquidity=5000, max_liquidity=1500000, limit=5)

    if not new_coins:
        await update.message.reply_text(
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

    analysis = openrouter_chat(prompt, system=system_prompt("memecoin"))

    max_len = 4000
    if len(analysis) > max_len:
        parts = analysis.split("\n\n")
        current = ""
        for part in parts:
            if len(current) + len(part) + 2 > max_len:
                if current:
                    await update.message.reply_text(current.strip())
                current = part
            else:
                current += "\n\n" + part if current else part
        if current.strip():
            await update.message.reply_text(current.strip())
    else:
        await update.message.reply_text(analysis)


async def learn(update, context):
    await update.message.reply_chat_action(action="typing")
    await update.message.reply_text(translate("learn_prompt"))


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
    total = count_knowledge()
    if total == 0:
        await update.message.reply_text("Knowledge base is empty.")
        return

    try:
        count = int(context.args[0]) if context.args else 3
        count = max(1, min(20, count))
    except ValueError:
        count = 3

    items = get_recent_knowledge(count)
    lines = []
    for i, item in enumerate(items):
        import time
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item['timestamp']))
        preview = item['text'][:280].replace('\n', ' ')
        lines.append(f"{i+1}. [{ts}] {item['source']}: {preview}...")

    await update.message.reply_text("Memory entries (latest first):\n" + "\n".join(lines))


async def health(update, context):
    await update.message.reply_chat_action(action="typing")
    test_prompt = "Say OK in three words."
    openrouter_answer = openrouter_chat(test_prompt, system="You are a simple health-check assistant.")
    stored = count_knowledge()
    chat_id = update.effective_chat.id

    await update.message.reply_text(
        f"Health check:\n"
        f"- Bot process connected and handling commands.\n"
        f"- Telegram token: {'set' if TELEGRAM_TOKEN else 'missing'}\n"
        f"- OpenRouter key: {'set' if OPENROUTER_API_KEY else 'missing'}\n"
        f"- OpenRouter test: {openrouter_answer[:200]}\n"
        f"- Knowledge entries: {stored}\n"
        f"- Your chat_id: `{chat_id}`"
    )


async def search(update, context):
    await update.message.reply_chat_action(action="typing")
    if not context.args:
        await update.message.reply_text(translate("search_usage"))
        return
    query = " ".join(context.args)
    results = search_knowledge(query, limit=5)
    if not results:
        await update.message.reply_text(translate("search_no_results"))
        return
    lines = [translate("search_results").format(query=query)]
    for i, item in enumerate(results):
        preview = item['text'][:200].replace('\n', ' ')
        lines.append(f"{i+1}. [{item['source']}] {preview}...")
    await update.message.reply_text("\n".join(lines))


async def set_lang(update, context):
    global BOT_LANGUAGE
    if not context.args:
        await update.message.reply_text(translate("set_lang_usage"))
        return
    chosen = context.args[0].lower()
    if chosen == "auto":
        from duckscreeener.config import settings
        settings.AUTO_DETECT_LANG = True
        await update.message.reply_text(translate("auto_detect"))
    elif chosen in ["en", "id"]:
        from duckscreeener.config import settings
        settings.AUTO_DETECT_LANG = False
        settings.BOT_LANGUAGE = chosen
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
    await update.message.reply_text(f"Analyzing wallet...\n`{wallet}`", parse_mode="Markdown")

    activity = analyze_wallet_activity(wallet)

    if not activity:
        await update.message.reply_text(
            "Tidak dapat mengambil data transaksi.\n"
            "Kemungkinan:\n"
            "- RPC node sedang masalah\n"
            "- Wallet tidak ada di mainnet"
        )
        return

    msg = f"Wallet Analysis\n`{wallet[:32]}...`\n\n"
    msg += f"Recent transactions: {activity['recent_txs']}\n"

    wallet_knowledge = search_knowledge(wallet[:20], limit=5)
    if wallet_knowledge:
        msg += f"\nRiwayat dari Knowledge Base:\n"
        for kb in wallet_knowledge[:3]:
            text = kb['text'][:100]
            msg += f"- {text}...\n"

    if activity.get('token_details'):
        msg += "\nTokens Traded:\n"
        for token in activity['token_details'][:5]:
            symbol = token.get('symbol', '?')
            price = token.get('price', '0')
            liquidity = token.get('liquidity', 0)

            if price and price != '0':
                msg += f"- {symbol}: ${float(price):.6f}"
                if liquidity:
                    msg += f" (liq: ${liquidity/1000:.1f}K)"
                msg += "\n"
            else:
                msg += f"- {symbol}\n"

    msg += f"\nEst. Volume: ~{activity['total_volume']:.2f} SOL"

    if activity.get('last_activity'):
        from datetime import datetime
        dt = datetime.fromtimestamp(activity['last_activity'])
        msg += f"\nLast activity: {dt.strftime('%Y-%m-%d %H:%M')}"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def wallet_scan(update, context):
    await update.message.reply_chat_action(action="typing")

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

        message += f"{gem['gem_type']}\n"
        message += f"*{gem['name']} ({gem['symbol']})*\n"
        message += f"Price: {price_str} | 24h: {change_24h}\n"
        message += f"Vol: {volume_str} | MC: ${gem['market_cap']/1_000_000:.1f}M\n"
        message += f"Vol/MC Ratio: {vm_ratio:.2f} (high = unusual activity)\n"
        message += f"From ATH: -{ath_drop:.0f}%\n"
        if gem.get('analysis'):
            message += f"Analisis: {gem['analysis'][:200]}\n\n"
        else:
            message += "\n"

        scan_record = (
            f"[GEM SCAN] {gem['name']} ({gem['symbol']}) - "
            f"Price: {price_str}, 24h: {change_24h}, Volume: {volume_str}, "
            f"Type: {gem['gem_type']}, Vol/MC: {vm_ratio:.2f}, "
            f"Analysis: {gem.get('analysis', 'N/A')[:200]}"
        )
        store_knowledge(f"scan:{gem['symbol']}", scan_record)

    message += "\nDYOR! These are accumulation signals, not financial advice."

    max_len = 4000
    if len(message) > max_len:
        parts = message.split("\n\n")
        current = ""
        for part in parts:
            if len(current) + len(part) + 2 > max_len:
                if current.strip():
                    await update.message.reply_text(current.strip(), parse_mode="Markdown")
                current = part
            else:
                current += "\n\n" + part if current else part
        if current.strip():
            await update.message.reply_text(current.strip(), parse_mode="Markdown")
    else:
        await status_msg.edit_text(message, parse_mode="Markdown")


async def run_backtest_command(update, context):
    await update.message.reply_chat_action(action="typing")
    await update.message.reply_text("Running backtest analysis...")

    try:
        report = run_backtest(chat_id=str(update.effective_chat.id))
        if report:
            await update.message.reply_text(report, parse_mode="Markdown")
        else:
            await update.message.reply_text("Backtest complete. Check report above.")
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

        # General chat
        recent = get_recent_knowledge(10)
        history = "\n".join([f"[{item['source']}] {item['text'][:300]}" for item in recent])

        full_context = f"""
KONTEKS KNOWLEDGE BASE

Data yang sudah dipelajari:
{history}

---
Sekarang jawab pertanyaan berikut dengan mempertimbangkan semua knowledge di atas:
"""

        if BOT_LANGUAGE == "id":
            prompt = (
                f"{full_context}\n\n"
                f"Pertanyaan: {text}\n\n"
                "Sebagai mentor crypto, berikan jawaban yang:\n"
                "1. Menggunakan data dari knowledge base\n"
                "2. Berbasis data (bukan opini kosong)\n"
                "3. Include risk warning jika perlu\n\n"
                "RESPOND ENTIRELY IN INDONESIAN."
            )
            system_msg = "Anda adalah mentor crypto yang menggunakan semua knowledge yang sudah dipelajari untuk memberikan jawaban terbaik."
        else:
            prompt = (
                f"{full_context}\n\n"
                f"Question: {text}\n\n"
                "As a crypto mentor, provide answer that:\n"
                "1. Uses data from knowledge base\n"
                "2. Is data-driven\n"
                "3. Include risk warning if needed"
            )
            system_msg = "You are a crypto mentor using all learned knowledge to provide the best answers."

        ans = openrouter_chat(prompt, system=system_msg)
        await msg.reply_text(ans)

        store_knowledge("user:question", text)
