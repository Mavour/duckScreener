import os
import sys
import logging
import threading
import asyncio
from dotenv import load_dotenv

load_dotenv()

from duckscreeener.config.settings import (
    TELEGRAM_TOKEN, OPENROUTER_API_KEY,
    SCAN_ENABLED, SOLANA_ENABLED, GMGN_ENABLED,
    BACKTEST_ENABLED, SCHEDULE_ENABLED,
    LOG_DIR, LOG_FILE,
    SCAN_INTERVAL_MINUTES, SOLANA_SCAN_INTERVAL,
)
from duckscreeener.db.database import init_db
from duckscreeener.handlers.commands import (
    start, summary, memecoin, memecoin_ai, learn, create_agent,
    set_lang, search,
    wallet_list, wallet_add, wallet_remove, wallet_analyze, wallet_scan,
    memory, health, scan_coins,
    run_backtest_command, handle_message,
)
from duckscreeener.scanners.coin_scanner import (
    scan_potential_coins, scan_gmgn_tokens,
)
from duckscreeener.scheduler.tasks import (
    run_backtest_scheduler, run_daily_news_scheduler, run_daily_reset_scheduler,
    send_telegram_message_sync,
)

os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


def log_activity(action_type: str, details: str, status: str = "success"):
    import time
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] [{action_type}] [{status}] {details}"
    logger.info(log_entry)


def run_coin_scanner():
    log_activity("SCANNER", "Coin scanner started")
    while True:
        try:
            gems = scan_potential_coins()
            if gems:
                message = "WHALE ACCUMULATION DETECTION\n\n"
                for gem in gems:
                    price_str = f"${gem['price']:.6f}" if gem['price'] < 1 else f"${gem['price']:.2f}"
                    change_1h = f"+{gem['change_1h']:.2f}%" if gem['change_1h'] > 0 else f"{gem['change_1h']:.2f}%"
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
                    message += f"Price: {price_str} | 1h: {change_1h} | 24h: {change_24h}\n"
                    message += f"Vol: {volume_str} | MC: ${gem['market_cap']/1_000_000:.1f}M\n"
                    message += f"Vol/MC: {vm_ratio:.2f} | ATH: -{ath_drop:.0f}%\n"
                    if gem.get('analysis'):
                        message += f"Analisis: {gem['analysis'][:150]}...\n"
                    coin_id = gem.get('coin_id', gem['symbol'].lower())
                    message += f"[CoinGecko](https://www.coingecko.com/en/coins/{coin_id}) | [CoinMarketCap](https://coinmarketcap.com/currencies/{coin_id})\n\n"

                    from duckscreeener.db.database import store_knowledge
                    scan_record = (
                        f"[GEM SCAN] {gem['name']} ({gem['symbol']}) - "
                        f"Price: {price_str}, 24h: {change_24h}, Volume: {volume_str}, "
                        f"Type: {gem['gem_type']}, Analysis: {gem.get('analysis', 'N/A')[:200]}"
                    )
                    store_knowledge(f"scan:{gem['symbol']}", scan_record)

                message += "\nDo your own research before investing!"
                from duckscreeener.config.settings import SCAN_CHAT_ID
                if SCAN_CHAT_ID:
                    send_telegram_message_sync(SCAN_CHAT_ID, message)
                log_activity("COIN_SCAN", f"Found {len(gems)} gems and sent alert", "success")
        except Exception as e:
            log_activity("SCANNER", f"Error: {e}", "error")

        import time
        time.sleep(SCAN_INTERVAL_MINUTES * 60)


def run_gmgn_scanner():
    from duckscreeener.scanners.memecoin_scanner import scan_new_memecoins
    log_activity("GMGN_SCANNER", "GMGN memecoin scanner started - interval: 30 minutes")
    while True:
        try:
            alerts = scan_new_memecoins(hours=12, min_liquidity=5000, max_liquidity=1500000, limit=5)
            if alerts:
                message = "GMGN MEMECOIN ALERT\n_Smart money tracking from GMGN_\n\n"
                for alert in alerts:
                    price = alert.get('price', 0)
                    price_str = f"${price:.8f}" if price < 0.001 else f"${price:.6f}"
                    liquidity_str = f"${alert['liquidity']/1_000:.1f}K"
                    volume_str = f"${alert['volume_24h']/1_000:.1f}K"
                    smart_buys = alert.get('volume_liq_ratio', 0)
                    holders = alert.get('holder_count', 0)

                    safety = "" if not alert.get('is_honeypot') else "HONEYPOT"

                    rating_emoji = "" if alert['rating'] == 'HIGH' else ("⚡" if alert['rating'] == 'MEDIUM' else "📊")
                    message += f"{rating_emoji} [{alert['rating']}] Score: {alert['score']}\n"
                    message += f"*{alert['name']} ({alert['symbol']})*\n"
                    message += f"Price: {price_str} | 1h: {'+' if alert['price_change_1h'] > 0 else ''}{alert['price_change_1h']:.1f}%\n"
                    message += f"Age: {alert['age_hours']:.1f}h | Vol: {volume_str} | Liq: {liquidity_str}\n"
                    message += f"Narrative: {', '.join(alert.get('narrative', ['Unknown']))}\n"
                    if alert.get('signals'):
                        message += f"Signals: {'; '.join(alert['signals'][:2])}\n"
                    message += f"[DexScreener]({alert['dex_screener_url']}) | [GMGN]({alert['gmgn_url']})\n\n"

                    from duckscreeener.db.database import store_knowledge
                    gmgn_record = (
                        f"[GMGN GEM] {alert['name']} ({alert['symbol']}) - "
                        f"Price: {price_str}, 1h: {alert['price_change_1h']:.1f}%, "
                        f"Age: {alert['age_hours']:.1f}h, Score: {alert['score']}, "
                        f"Rating: {alert['rating']}, Token: {alert['address']}"
                    )
                    store_knowledge(f"gmgn:{alert['symbol']}", gmgn_record)

                message += "\n_Always do your own research!_"
                from duckscreeener.config.settings import SOLANA_CHAT_ID
                if SOLANA_CHAT_ID:
                    send_telegram_message_sync(SOLANA_CHAT_ID, message)
                log_activity("GMGN_SCAN", f"Sent {len(alerts)} alerts", "success")
        except Exception as e:
            log_activity("GMGN_SCANNER", f"Error: {e}", "error")

        import time
        time.sleep(1800)


def main():
    log_activity("BOT_START", "Starting Crypto Agent Bot (Modular)")
    init_db()

    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("Please set TELEGRAM_TOKEN in .env")
        log_activity("BOT_START", "Missing TELEGRAM_TOKEN", "error")
        return

    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "YOUR_OPENROUTER_API_KEY":
        logger.error("Please set OPENROUTER_API_KEY in .env")
        log_activity("BOT_START", "Missing OPENROUTER_API_KEY", "error")
        return

    from telegram import Update, BotCommand
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
    from telegram.request import HTTPXRequest

    async def setup_bot_commands(app):
        commands = [
            BotCommand("start", "Menu Utama / Help"),
            BotCommand("summary", "News Harian"),
            BotCommand("scan", "Whale Accumulation Detection"),
            BotCommand("memecoin", "New Memecoin Scanner"),
            BotCommand("memecoin_ai", "AI Memecoin Analysis"),
            BotCommand("wallet_analyze", "Analisa Wallet"),
            BotCommand("wallet_scan", "Scan Semua Wallet"),
            BotCommand("wallet_list", "List Wallet"),
            BotCommand("wallet_add", "Tambah Wallet"),
            BotCommand("wallet_remove", "Hapus Wallet"),
            BotCommand("learn", "Learn PDF/Link"),
            BotCommand("memory", "Knowledge Base"),
            BotCommand("search", "Cari di KB"),
            BotCommand("backtest", "Cek Performa"),
            BotCommand("health", "Status Bot"),
            BotCommand("set_lang", "Ganti Bahasa"),
        ]
        await app.bot.set_my_commands(commands)

    request = HTTPXRequest(connect_timeout=10.0, read_timeout=20.0)
    app = (ApplicationBuilder()
           .token(TELEGRAM_TOKEN)
           .request(request)
           .post_init(setup_bot_commands)
           .build())

    async def error_handler(update, context):
        log_activity("ERROR", f"{context.error}", "error")
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("scan", scan_coins))
    app.add_handler(CommandHandler("memecoin", memecoin))
    app.add_handler(CommandHandler("memecoin_ai", memecoin_ai))
    app.add_handler(CommandHandler("wallet_list", wallet_list))
    app.add_handler(CommandHandler("wallet_add", wallet_add))
    app.add_handler(CommandHandler("wallet_remove", wallet_remove))
    app.add_handler(CommandHandler("wallet_analyze", wallet_analyze))
    app.add_handler(CommandHandler("wallet_scan", wallet_scan))
    app.add_handler(CommandHandler("memory", memory))
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("set_lang", set_lang))
    app.add_handler(CommandHandler("learn", learn))
    app.add_handler(CommandHandler("create_agent", create_agent))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("backtest", run_backtest_command))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.TEXT & (~filters.COMMAND), handle_message))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if SCAN_ENABLED:
        scanner_thread = threading.Thread(target=run_coin_scanner, daemon=True)
        scanner_thread.start()
        log_activity("BOT_START", "Coin scanner thread started (every 6 hours)", "success")

    if GMGN_ENABLED:
        gmgn_thread = threading.Thread(target=run_gmgn_scanner, daemon=True)
        gmgn_thread.start()
        log_activity("BOT_START", "GMGN scanner thread started", "success")

    if BACKTEST_ENABLED:
        backtest_thread = threading.Thread(target=run_backtest_scheduler, daemon=True)
        backtest_thread.start()
        log_activity("BOT_START", "Backtest scheduler thread started", "success")

    if SCHEDULE_ENABLED:
        schedule_thread = threading.Thread(target=run_daily_news_scheduler, daemon=True)
        schedule_thread.start()
        log_activity("BOT_START", "Daily news scheduler thread started", "success")

    reset_thread = threading.Thread(target=run_daily_reset_scheduler, daemon=True)
    reset_thread.start()
    log_activity("BOT_START", "Daily signal reset thread started (00:00)", "success")

    logger.info("Bot started...")
    log_activity("BOT_START", "Bot successfully started and polling for updates", "success")

    try:
        app.run_polling()
    except Exception as e:
        logger.error(f"Bot error: {e}")
        log_activity("BOT_ERROR", str(e), "error")


if __name__ == "__main__":
    main()
