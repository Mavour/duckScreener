import logging
import asyncio
from duckscreeener.config.settings import (
    TELEGRAM_TOKEN, SCHEDULE_CHAT_ID, SCHEDULE_ENABLED, BACKTEST_CHAT_ID, BACKTEST_ENABLED,
    SCHEDULE_HOUR, SCHEDULE_MINUTE, BACKTEST_HOUR, BACKTEST_MINUTE,
    GMGN_ENABLED, BOT_LANGUAGE,
)
from duckscreeener.services.external_apis import fetch_latest_news_with_items, openrouter_chat, fetch_tweets
from duckscreeener.scanners.backtest import run_backtest

logger = logging.getLogger(__name__)

MAX_TELEGRAM_MSG = 4000


async def send_telegram_message(chat_id, text, parse_mode="Markdown"):
    from telegram import Bot
    bot = Bot(token=TELEGRAM_TOKEN)

    if len(text) <= MAX_TELEGRAM_MSG:
        await bot.send_message(chat_id=int(chat_id), text=text, parse_mode=parse_mode)
    else:
        parts = text.split("\n\n")
        current = ""
        for part in parts:
            if len(current) + len(part) + 2 > MAX_TELEGRAM_MSG:
                if current.strip():
                    await bot.send_message(chat_id=int(chat_id), text=current.strip(), parse_mode=parse_mode)
                current = part
            else:
                current += "\n\n" + part if current else part
        if current.strip():
            await bot.send_message(chat_id=int(chat_id), text=current.strip(), parse_mode=parse_mode)


def send_telegram_message_sync(chat_id, text, parse_mode="Markdown"):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(send_telegram_message(chat_id, text, parse_mode))
        finally:
            loop.close()
        logger.info(f"Message sent to chat {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send Telegram message to {chat_id}: {e}")


def run_backtest_scheduler():
    import time
    import schedule

    logger.info(f"Backtest scheduled for {BACKTEST_HOUR:02d}:{BACKTEST_MINUTE:02d} daily")

    def backtest_job():
        try:
            report = run_backtest(chat_id=BACKTEST_CHAT_ID)
            if report:
                send_telegram_message_sync(BACKTEST_CHAT_ID, report)
                logger.info("Backtest report sent successfully")
            else:
                send_telegram_message_sync(
                    BACKTEST_CHAT_ID,
                    "Backtest completed. No signals to evaluate yet.\nRun /scan or /gmgn first to generate signals."
                )
                logger.info("Backtest completed - no signals")
        except Exception as e:
            logger.error(f"Backtest scheduler error: {e}")
            send_telegram_message_sync(
                BACKTEST_CHAT_ID,
                f"Backtest error: {e}"
            )

    schedule.every().day.at(f"{BACKTEST_HOUR:02d}:{BACKTEST_MINUTE:02d}").do(backtest_job)

    while True:
        schedule.run_pending()
        time.sleep(60)


def run_daily_news_scheduler():
    import time
    import schedule

    logger.info(f"Daily news scheduled for {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}")

    def news_job():
        send_daily_news()

    schedule.every().day.at(f"{SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}").do(news_job)

    while True:
        schedule.run_pending()
        time.sleep(60)


def send_daily_news():
    if not SCHEDULE_ENABLED or not SCHEDULE_CHAT_ID:
        logger.warning("Daily news: SCHEDULE_ENABLED or SCHEDULE_CHAT_ID not set")
        return

    try:
        news_items = fetch_latest_news_with_items(limit=10)
        if not news_items:
            send_telegram_message_sync(SCHEDULE_CHAT_ID, "No crypto news found from CoinGecko today.")
            return

        news_text = "\n".join([
            f"- {item.get('title', '')}: {item.get('description', '')[:200]}... ({item.get('url', '')})"
            for item in news_items
        ])

        tweets_data = []
        try:
            tweets_data, _, _ = fetch_tweets("crypto OR bitcoin OR ethereum OR memecoin", max_results=5)
        except Exception as e:
            logger.warning(f"Failed to fetch tweets for daily news: {e}")

        combined_data = f"=== COINGECKO NEWS ===\n{news_text}\n\n"
        if tweets_data:
            tweets_text = "\n".join([f"- @{t['author']}: {t['text'][:200]}" for t in tweets_data])
            combined_data += f"=== TWITTER/X UPDATES ===\n{tweets_text}"

        if BOT_LANGUAGE == "id":
            prompt = (
                f"Ringkaslah perkembangan crypto dari 24 jam terakhir dalam format berikut:\n"
                f"1. NEWS: Ringkasan 3-5 berita terpenting - SELALU sertakan link sumber\n"
                f"2. TRENDS: Insight dari tweet terbaru tentang crypto\n"
                f"3. ANALISIS: Apa yang perlu diperhatikan untuk hari ini\n"
                f"4. OUTLOOK: Prediksi singkat untuk market hari ini\n\n"
                f"Data:\n{combined_data}\n\nRESPOND ENTIRELY IN INDONESIAN. Keep it under 2000 characters."
            )
            system_msg = "Anda adalah analis crypto professional yang memberikan update harian dalam bahasa Indonesia."
        else:
            prompt = (
                f"Summarize the crypto developments from the last 24 hours in the following format:\n"
                f"1. NEWS: Summary of 3-5 important news\n"
                f"2. TRENDS: Insights from latest crypto tweets\n"
                f"3. ANALYSIS: What to watch for today\n"
                f"4. OUTLOOK: Brief market prediction for today\n\n"
                f"Data:\n{combined_data}\n\nKeep it under 2000 characters."
            )
            system_msg = "You are a professional crypto analyst providing daily updates."

        summary = openrouter_chat(prompt, system=system_msg)

        from datetime import datetime
        source_links = ""
        for item in news_items[:5]:
            title = item.get('title', '')[:50]
            url = item.get('url', '')
            if url:
                source_links += f"- [{title}...]({url})\n"

        message = f"Daily Crypto Update - {datetime.now().strftime('%d %B %Y')}\n\n{summary}\n\nSources:\n{source_links}"

        send_telegram_message_sync(SCHEDULE_CHAT_ID, message)
        logger.info(f"Sent daily news to chat {SCHEDULE_CHAT_ID}")

    except Exception as e:
        logger.error(f"Error generating daily news: {e}")
        send_telegram_message_sync(
            SCHEDULE_CHAT_ID,
            f"Failed to generate daily news: {e}"
        )
