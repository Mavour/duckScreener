import os
import sys
import json
import sqlite3
import logging
import requests
import time
import random
import tempfile
import uuid
import threading
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()  # take environment variables from .env
from telegram import Update, ForceReply, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

# Optional schedule module
import subprocess
import sys
try:
    import schedule
    SCHEDULE_AVAILABLE = True
except ImportError:
    # Try to install it automatically
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "schedule", "-q"])
        import schedule
        SCHEDULE_AVAILABLE = True
    except:
        SCHEDULE_AVAILABLE = False
        print("WARNING: schedule module not installed. Scheduled news feature disabled.")

# Optional dependencies for PDF/image learning and language detection
try:
    import fitz  # PyMuPDF
    from PIL import Image
    import pytesseract
except ImportError:
    fitz = None
    Image = None
    pytesseract = None
    logging.warning("Optional PDF/image learning dependencies are not installed.")

try:
    from textblob import TextBlob
    TEXTBLOB_AVAILABLE = True
except ImportError:
    TEXTBLOB_AVAILABLE = False
    logging.warning("TextBlob not installed for language detection; auto-detect disabled.")

try:
    import tweepy
    TWEEPY_AVAILABLE = True
except ImportError:
    TWEEPY_AVAILABLE = False
    logging.warning("Tweepy not installed for X (Twitter) integration; /tweets disabled.")

# Ensure UTF-8 output for console (Windows compatibility)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "YOUR_OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")  # free model on OpenRouter
BOT_LANGUAGE = os.getenv("BOT_LANGUAGE", "en")  # use "id" for Indonesian
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
TRUSTED_TWITTER_ACCOUNTS = [x.strip().replace('@', '') for x in os.getenv("TRUSTED_TWITTER_ACCOUNTS", "").split(",") if x.strip()]
COINGECKO_NEWS_URL = "https://api.coingecko.com/api/v3/news"
TWITTER_ERROR_MSG = ""
TWITTER_ERROR_CODE = None
TWITTER_FALLBACK_MODE = os.getenv("TWITTER_FALLBACK_MODE", "auto").lower()  # auto|on|off

# Logging with file output
LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "agent_activity.log")

# Coin Scanner Configuration
COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
SCAN_ENABLED = os.getenv("SCAN_ENABLED", "false").lower() == "true"
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))
SCAN_CHAT_ID = os.getenv("SCAN_CHAT_ID", "")  # Chat ID for alerts
SCAN_MIN_VOLUME_USD = float(os.getenv("SCAN_MIN_VOLUME_USD", "100000"))  # Min $100k volume
SCAN_MIN_PRICE_CHANGE = float(os.getenv("SCAN_MIN_PRICE_CHANGE", "5"))  # Min 5% change

# Solana Smart Wallet Scanner Configuration
SOLANA_ENABLED = os.getenv("SOLANA_ENABLED", "false").lower() == "true"
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
SOLANA_CHAT_ID = os.getenv("SOLANA_CHAT_ID", "")
SOLANA_MIN_TRADE_VALUE = float(os.getenv("SOLANA_MIN_TRADE_VALUE", "10"))
SOLANA_KNOWN_WALLETS = os.getenv("SOLANA_KNOWN_WALLETS", "")
SOLANA_SCAN_INTERVAL = int(os.getenv("SOLANA_SCAN_INTERVAL", "60"))

# GMGN Memecoin Scanner Configuration
GMGN_ENABLED = os.getenv("GMGN_ENABLED", "false").lower() == "true"
GMGN_API_URL = "https://gmgn.ai/defi/quotation/v1/rank"

# Backtest Configuration
BACKTEST_ENABLED = os.getenv("BACKTEST_ENABLED", "true").lower() == "true"
BACKTEST_INTERVAL_HOURS = int(os.getenv("BACKTEST_INTERVAL_HOURS", "24"))  # Check every 24 hours
BACKTEST_CHAT_ID = os.getenv("BACKTEST_CHAT_ID", "")
BACKTEST_SUCCESS_THRESHOLD = float(os.getenv("BACKTEST_SUCCESS_THRESHOLD", "10"))  # 10% gain = success
BACKTEST_FAILURE_THRESHOLD = float(os.getenv("BACKTEST_FAILURE_THRESHOLD", "-20"))  # -20% = failure

# Known smart wallet addresses (famous traders on Solana)
SOLANA_SMART_WALLETS = [
    "7xKXtg2CW87d97TXJSDpbD5jBkHuTWrPqCg44dFYrCE8",  # Famous Solana trader
    "BLToaDD4iYS3F5W6Kdx4p5UTyiZWxyPnDKhMTqGgy3x",  # Known whale
]

# Dynamic smart wallet list (user-added)
USER_ADDED_WALLETS = []

# Solana RPC Configuration
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
SOLANA_RPC_HEADERS = {"Content-Type": "application/json"}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Schedule configuration
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "8"))  # Default 8 AM
SCHEDULE_MINUTE = int(os.getenv("SCHEDULE_MINUTE", "0"))  # Default minute 0
SCHEDULE_TIMEZONE = os.getenv("SCHEDULE_TIMEZONE", "Asia/Makassar")  # WITA timezone
SCHEDULE_ENABLED = os.getenv("SCHEDULE_ENABLED", "true").lower() == "true"
SCHEDULE_CHAT_ID = os.getenv("SCHEDULE_CHAT_ID", "")  # Chat ID untuk kirim pesan terjadwal

# Activity log function to track all agent actions
def log_activity(action_type: str, details: str, status: str = "success"):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] [{action_type}] [{status}] {details}"
    logger.info(log_entry)

# Knowledge persistence with SQLite
KNOWLEDGE_DB = os.getenv("KNOWLEDGE_DB", "knowledge_base.db")
_db_conn = None

def get_db():
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect(KNOWLEDGE_DB, check_same_thread=False)
        _db_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
            """
        )
        _db_conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                source, text
            )
            """
        )
        _db_conn.commit()
    return _db_conn


def detect_language(text):
    """Auto-detect language: 'id' for Indonesian, 'en' for English"""
    if not TEXTBLOB_AVAILABLE:
        return None
    try:
        blob = TextBlob(text)
        lang = blob.detect_language()
        if lang in ['id', 'en']:
            return lang
    except Exception as e:
        logger.warning(f"Language detection failed: {e}")
    return None


def load_knowledge():
    get_db()  # ensure DB and table exist


def translate(key):
    strings = {
        "start_both": {
            "en": """👋 *Welcome to Crypto Agent Bot!*

I'm your AI-powered crypto trading assistant. Here's what I can do:

📰 *NEWS & ANALYSIS*
/summary - Get daily crypto news summary
/sentiment - Analyze market sentiment for a coin

💎 *COIN SCREENING*
/screen - Find undervalued coins (whale accumulation, fundamentals)
/scan - Scan for potential gems

🐕 *MEMECOIN & SOLANA*
/memecoin - Find trending memecoins
/solana - Scan Solana smart wallet activity  
/gmgn - GMGN/DexScreener memecoin scanner
/wallet_analyze <addr> - Analyze specific wallet
/wallet_scan - Scan all tracked wallets
/wallet_list - List tracked wallets
/wallet_add <addr> - Add wallet to track
/wallet_remove <addr> - Remove wallet

🐦 *TWITTER/X*
/tweets <keyword> - Fetch tweets (use --trusted for verified accounts)
/trust_list - View trusted accounts
/trust_add @user - Add trusted account
/trust_remove @user - Remove trusted account

🧠 *KNOWLEDGE & TOOLS*
/learn - Learn from PDF/image/link
/memory - View stored knowledge
/search <query> - Search knowledge base
/create_agent - Create custom AI agent

📊 *BACKTEST & ALERTS*
/backtest - Check signal performance
/health - Bot health status

⚙️ *SETTINGS*
/set_lang <en|id> - Change language
/help - Show this help message

_Just type any command to get started!_""",
            "id": """👋 *Selamat Datang di Crypto Agent Bot!*

Saya adalah asisten trading crypto AI Anda. Ini yang bisa saya lakukan:

📰 *BERITA & ANALISIS*
/summary - Ringkasan berita crypto harian
/sentiment - Analisis sentiment market untuk coin

💎 *SCREENING COIN*
/screen - Cari coin yang undervalued
/scan - Scan potential gems

🐕 *MEMECOIN & SOLANA*
/memecoin - Cari trending memecoins
/solana - Scan smart wallet activity di Solana
/gmgn - Scanner memecoin via GMGN/DexScreener
/wallet_analyze <alamat> - Analisa wallet tertentu
/wallet_scan - Scan semua wallet tracker
/wallet_list - Lihat list wallet
/wallet_add <alamat> - Tambah wallet
/wallet_remove <alamat> - Hapus wallet

🐦 *TWITTER/X*
/tweets <keyword> - Ambil tweets (--trusted untuk akun terverifikasi)
/trust_list - Lihat trusted accounts
/trust_add @user - Tambah trusted account
/trust_remove @user - Hapus trusted account

🧠 *KNOWLEDGE & TOOLS*
/learn - Belajar dari PDF/gambar/link
/memory - Lihat knowledge base
/search <query> - Cari di knowledge base
/create_agent - Buat AI agent kustom

📊 *BACKTEST & ALERTS*
/backtest - Cek performa sinyal
/health - Status kesehatan bot

⚙️ *SETTINGS*
/set_lang <en|id> - Ganti bahasa
/help - Tampilkan pesan ini

_Cukup ketik command untuk memulai!_"""
        },
        "learn_prompt": {
            "en": "Send me a PDF or an image, and I will extract text, summarize, and learn.",
            "id": "Kirim PDF atau gambar, saya akan mengekstrak teks, meringkas, dan belajar."
        },
        "set_lang_success": {
            "en": "Language set to {lang}.",
            "id": "Bahasa diatur ke {lang}."
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
        "tweets_fallback_set": {
            "en": "Tweet fallback mode set to {mode}. Options: auto/on/off.",
            "id": "Mode fallback tweet diatur ke {mode}. Opsi: auto/on/off."
        },
        "tweets_fallback_usage": {
            "en": "Usage: /tweets_fallback <auto|on|off>",
            "id": "Cara pakai: /tweets_fallback <auto|on|off>"
        },
        "tweets_fallback_status": {
            "en": "Tweets fallback status: mode={mode}. Twitter configured={twitter}.", 
            "id": "Status fallback tweets: mode={mode}. Twitter dikonfigurasi={twitter}."
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
            "en": "📊 *Sentiment Analysis - {coin}*\n\n",
            "id": "📊 *Analisis Sentiment - {coin}*\n\n"
        },
        "auto_detect": {
            "en": "Auto-detect enabled. Language will switch based on your messages.",
            "id": "Auto-deteksi diaktifkan. Bahasa akan berganti sesuai pesan Anda."
        },
        "summary_system": {
            "en": "You are a concise crypto news analyst.",
            "id": "Anda adalah analis berita kripto yang ringkas dan menggunakan bahasa Indonesia."
        },
        "screen_system": {
            "en": "You are a crypto analyst specializing in undervalued assets.",
            "id": "Anda adalah analis kripto yang mengkhususkan diri dalam aset undervalued dengan perspektif Indonesia."
        },
        "memecoin_system": {
            "en": "You are a crypto analyst focusing on memecoin and on-chain signals.",
            "id": "Anda adalah analis kripto yang fokus pada memecoin dan sinyal on-chain."
        },
        "general_system": {
            "en": "You are a helpful crypto assistant.",
            "id": "Anda adalah asisten kripto yang membantu dan sopan dalam bahasa Indonesia."
        },
        "agent_architect_system": {
            "en": "You are an AI agent architect.",
            "id": "Anda adalah arsitek agen AI yang membantu."
        }
    }
    return strings.get(key, {}).get(BOT_LANGUAGE, strings.get(key, {}).get('en', ''))


def system_prompt(key):
    return translate(key + "_system")


def store_knowledge(source, text):
    db = get_db()
    db.execute(
        "INSERT INTO knowledge (source, text, timestamp) VALUES (?, ?, ?)",
        (source, text, time.time()),
    )
    # Also index in FTS5 for fast search
    db.execute(
        "INSERT INTO knowledge_fts (source, text) VALUES (?, ?)",
        (source, text),
    )
    db.commit()
    logger.info(f"Knowledge stored from {source} ({len(text)} chars)")


def search_knowledge(query, limit=5):
    """Search knowledge base using FTS5"""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT source, text FROM knowledge_fts WHERE knowledge_fts MATCH ? LIMIT ?",
            (query, limit),
        ).fetchall()
        return [{'source': r[0], 'text': r[1]} for r in rows]
    except Exception as e:
        logger.error(f"FTS5 search failed: {e}")
        return []


def count_knowledge():
    db = get_db()
    row = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()
    return row[0] if row else 0


def get_recent_knowledge(limit=3):
    db = get_db()
    rows = db.execute(
        "SELECT source, text, timestamp FROM knowledge ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [{'source': r[0], 'text': r[1], 'timestamp': r[2]} for r in rows]

def extract_text_from_pdf(file_path):
    if not fitz:
        return "PDF extraction not available. Please install PyMuPDF."
    try:
        doc = fitz.open(file_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts).strip()
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return f"PDF extraction failed: {e}"

def extract_text_from_image(file_path):
    if not Image or not pytesseract:
        return "Image OCR not available. Please install pillow and pytesseract."
    try:
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image)
        return text.strip()
    except Exception as e:
        logger.error(f"Image OCR failed: {e}")
        return f"Image OCR failed: {e}"

def extract_text_from_youtube(url):
    """Extract transcript/text from YouTube video using yt-dlp"""
    try:
        import yt_dlp
    except ImportError:
        try:
            import subprocess, sys
            subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp", "-q"])
            import yt_dlp
        except:
            return "YouTube extraction not available. Please install yt-dlp: pip install yt-dlp"
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', '')
            duration = info.get('duration', 0)
            description = info.get('description', '')
            return f"Video: {title}\nDuration: {duration//60} min\n\n{description[:5000] if description else 'No description available'}"
    except Exception as e:
        logger.error(f"YouTube extraction failed: {e}")
        return f"YouTube extraction failed: {e}"

# Helper: fetch latest crypto news from CoinGecko (free)
def fetch_latest_news(limit=5):
    try:
        log_activity("NEWS_FETCH", f"Fetching latest {limit} crypto news items")
        resp = requests.get(f"{COINGECKO_NEWS_URL}?page=1", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # CoinGecko returns list of news items with 'title', 'description', 'url', 'published_at'
        news_items = data.get('data', [])
        # Take first 'limit' items
        selected = news_items[:limit]
        summary_parts = []
        for item in selected:
            title = item.get('title', '').strip()
            desc = item.get('description', '').strip()
            url = item.get('url', '')
            if title:
                summary_parts.append(f"{title} - {desc[:150]}... ({url})")
        result = "\n".join(summary_parts) if summary_parts else "No recent news found."
        log_activity("NEWS_FETCH", f"Successfully fetched {len(summary_parts)} news items", "success")
        return result
    except Exception as e:
        log_activity("NEWS_FETCH", f"Failed to fetch news: {e}", "error")
        logger.error(f"Error fetching news: {e}")
        return "Failed to fetch news."

# === COIN SCANNER FOR POTENTIAL GEMs ===
def scan_potential_coins():
    """Scan for potential gems based on volume, price change, and market cap"""
    if not SCAN_ENABLED:
        return []
    
    log_activity("COIN_SCAN", "Starting coin scan...")
    
    try:
        # Get trending coins
        trending_url = f"{COINGECKO_API_URL}/search/trending"
        resp = requests.get(trending_url, timeout=15)
        resp.raise_for_status()
        trending_data = resp.json()
        
        # Get coins with high volume and price change
        coins_url = f"{COINGECKO_API_URL}/coins/markets"
        params = {
            'vs_currency': 'usd',
            'order': 'volume_desc',
            'per_page': 100,
            'page': 1,
            'sparkline': 'false',
            'price_change_percentage': '1h,24h,7d'
        }
        resp = requests.get(coins_url, params=params, timeout=15)
        resp.raise_for_status()
        markets_data = resp.json()
        
        potential_gems = []
        
        for coin in markets_data:
            # Filter criteria
            volume = coin.get('market_cap', 0)
            price_change_24h = coin.get('price_change_percentage_24h', 0) or 0
            price_change_1h = coin.get('price_change_percentage_1h_in_currency', 0) or 0
            market_cap = coin.get('market_cap', 0)
            current_price = coin.get('current_price', 0)
            symbol = coin.get('symbol', '').upper()
            
            # Skip if market cap too high (not a gem)
            if market_cap > 500_000_000:  # > $500M
                continue
            
            # Skip if volume too low
            if volume < SCAN_MIN_VOLUME_USD:
                continue
            
            # Check for potential gem criteria
            is_potential_gem = False
            gem_type = ""
            
            # Type 1: High 24h gainers with decent volume (scalping)
            if price_change_24h >= 10 and volume > 500_000:
                is_potential_gem = True
                gem_type = "🔥 SCALP (24h gainer)"
            
            # Type 2: Recovering from dip (buy the dip)
            elif price_change_24h < -15 and price_change_1h > 2:
                is_potential_gem = True
                gem_type = "📉 BUY THE DIP"
            
            # Type 3: Trending + volume spike
            elif price_change_1h > 5 and volume > 1_000_000:
                is_potential_gem = True
                gem_type = "📈 VOLUME SPIKE"
            
            # Type 4: Low cap with momentum (moonshot)
            elif market_cap < 10_000_000 and price_change_24h > 20:
                is_potential_gem = True
                gem_type = "🚀 MOONSHOT"
            
            if is_potential_gem:
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
                    'coin_id': coin_id
                })
        
        # Generate AI analysis for each gem (with fallback if LLM fails)
        for gem in potential_gems:
            try:
                price_str = f"${gem['price']:.6f}" if gem['price'] < 1 else f"${gem['price']:.2f}"
                analysis_prompt = (
                    f"Berikan analisis singkat (2-3 sentences) mengapa {gem['name']} ({gem['symbol']}) "
                    f"dengan price {price_str}, 24h change {gem['change_24h']:.2f}%, "
                    f"volume ${gem['volume']/1_000_000:.1f}M, dan market cap ${gem['market_cap']/1_000_000:.1f}M "
                    f"sangat potensial untuk {gem['gem_type'].split()[0]}. "
                    f"Fokus pada momentum, volume, dan potensi upside. "
                    f"Respond dalam bahasa Indonesia yang natural dan singkat."
                )
                gem['analysis'] = openrouter_chat(analysis_prompt, system="You are a crypto analyst providing brief, actionable insights.")
                # Check if the response indicates failure
                if "couldn't process" in gem['analysis'].lower() or "maaf" in gem['analysis'].lower():
                    raise Exception("LLM failed")
            except Exception as e:
                # Fallback: Get news from CoinGecko and search for related coin
                try:
                    news_resp = requests.get(f"{COINGECKO_API_URL}/news?page=1", timeout=10)
                    if news_resp.status_code == 200:
                        news_data = news_resp.json()
                        related_news = []
                        search_term = gem['symbol'].lower()
                        for item in news_data.get('data', [])[:30]:
                            title = item.get('title', '').lower()
                            if search_term in title or gem['name'].lower() in title:
                                related_news.append(f"📰 {item.get('title', '')[:100]}")
                        if related_news:
                            gem['analysis'] = " | ".join(related_news[:2])
                        else:
                            gem['analysis'] = f"Data: {gem['change_24h']:.1f}% 24h, vol ${gem['volume']/1e6:.1f}M. Cek langsung untuk info terbaru."
                    else:
                        raise Exception("No news API")
                except:
                    change = gem['change_24h']
                    if change > 20:
                        gem['analysis'] = "Momentum sangat kuat."
                    elif change > 10:
                        gem['analysis'] = "Tren naik solid."
                    else:
                        gem['analysis'] = "Potensi upside terlihat."
                log_activity("COIN_SCAN", f"Using news fallback for {gem['symbol']}", "warning")
        
        log_activity("COIN_SCAN", f"Found {len(potential_gems)} potential gems with AI analysis", "success")
        return potential_gems[:10]  # Return top 10
        
    except Exception as e:
        log_activity("COIN_SCAN", f"Scan failed: {e}", "error")
        logger.error(f"Coin scan error: {e}")
        return []

def send_scan_alert(app, gems):
    """Send scan results to configured chat"""
    if not gems or not SCAN_CHAT_ID:
        return
    
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        message = "🔍 *POTENTIAL GEM SCAN*\n\n"
        
        for gem in gems:
            price_str = f"${gem['price']:.6f}" if gem['price'] < 1 else f"${gem['price']:.2f}"
            change_1h = f"+{gem['change_1h']:.2f}%" if gem['change_1h'] > 0 else f"{gem['change_1h']:.2f}%"
            change_24h = f"+{gem['change_24h']:.2f}%" if gem['change_24h'] > 0 else f"{gem['change_24h']:.2f}%"
            volume_str = f"${gem['volume']/1_000_000:.1f}M"
            
            message += f"{gem['gem_type']}\n"
            message += f"*{gem['name']} ({gem['symbol']})*\n"
            message += f"💰 Price: {price_str} | 1h: {change_1h} | 24h: {change_24h}\n"
            message += f"📊 Vol: {volume_str}\n"
            message += f"🔗 [CoinGecko]({gem['coingecko_url']}) | [CMC]({gem['coinmarketcap_url']})\n"
            if gem.get('analysis'):
                message += f"💡 *Analisis:* {gem['analysis'][:150]}...\n\n"
            else:
                message += "\n"
            
            # Store to knowledge base for backtest
            scan_record = (
                f"[GEM SCAN] {gem['name']} ({gem['symbol']}) - "
                f"Price: {price_str}, 24h: {change_24h}, Volume: {volume_str}, "
                f"Type: {gem['gem_type']}, Analysis: {gem.get('analysis', 'N/A')[:200]}"
            )
            store_knowledge(f"scan:{gem['symbol']}", scan_record)
        
        # Send to Telegram
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)
        loop.run_until_complete(bot.send_message(
            chat_id=int(SCAN_CHAT_ID),
            text=message,
            parse_mode="Markdown"
        ))
        
        log_activity("COIN_SCAN", f"Sent alert to chat {SCAN_CHAT_ID} and stored {len(gems)} records", "success")
        loop.close()
        
    except Exception as e:
        log_activity("COIN_SCAN", f"Failed to send alert: {e}", "error")

def run_coin_scanner(app):
    """Background scanner for potential gems"""
    log_activity("SCANNER", "Coin scanner started")
    
    while True:
        try:
            gems = scan_potential_coins()
            if gems:
                send_scan_alert(app, gems)
        except Exception as e:
            log_activity("SCANNER", f"Error: {e}", "error")
        
        # Sleep for scan interval
        time.sleep(SCAN_INTERVAL_MINUTES * 60)

# === SOLANA SMART WALLET TRACKER ===
# Track previously sent alerts to avoid duplicates
SOLANA_SENT_ALERTS = set()  # Store token addresses already alerted

def get_solana_token_data():
    """Get recent token trades on Solana using public API"""
    try:
        url = "https://api.dexscreener.com/latest/dex/tokens/solana"
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            pairs = data.get('pairs') or []
            log_activity("SOLANA_DEBUG", f"API returned {len(pairs)} pairs", "success")
            return data
        return None
    except Exception as e:
        log_activity("SOLANA_SCAN", f"Failed to get token data: {e}", "error")
        return None

def scan_smart_wallets():
    """Scan for smart wallet activity on Solana"""
    global SOLANA_SENT_ALERTS
    
    if not SOLANA_ENABLED:
        return []
    
    log_activity("SOLANA_SCAN", "Scanning Solana for early gems...")
    
    try:
        # Get recent token data from multiple sources
        token_data = get_solana_token_data()
        
        recent_alerts = []
        
        # Try DexScreener pairs
        if token_data and 'pairs' in token_data:
            pairs = token_data.get('pairs', [])
            
            for pair in pairs[:100]:  # Check top 100 pairs
                try:
                    liquidity = float(pair.get('liquidity', {}).get('usd', 0) or 0)
                    volume_24h = float(pair.get('volume', {}).get('h24', 0) or 0)
                    price_change = float(pair.get('priceChange', {}).get('h24', 0) or 0)
                    
                    base_token = pair.get('baseToken', {})
                    token_address = base_token.get('address', '')
                    
                    # Skip if already alerted
                    if token_address in SOLANA_SENT_ALERTS:
                        continue
                    
                    # Relaxed criteria for finding more alerts
                    is_early = False
                    alert_type = ""
                    
                    # Type 1: New pair with good volume (more relaxed)
                    if liquidity >= 2000 and volume_24h > 5000 and price_change > 5:
                        is_early = True
                        alert_type = "🆕 NEW PAIR"
                    
                    # Type 2: Strong momentum
                    elif liquidity > 10000 and volume_24h > 20000 and price_change > 10:
                        is_early = True
                        alert_type = "📈 STRONG MOMENTUM"
                    
                    # Type 3: Low cap high gainer (moonshot)
                    elif liquidity < 100000 and price_change > 30 and volume_24h > 3000:
                        is_early = True
                        alert_type = "🚀 MOONSHOT CANDIDATE"
                    
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
                except Exception as e:
                    continue
        
        log_activity("SOLANA_SCAN", f"Found {len(recent_alerts)} new Solana alerts", "success")
        return recent_alerts[:5]  # Return top 5 new alerts
        
    except Exception as e:
        log_activity("SOLANA_SCAN", f"Scan failed: {e}", "error")
        return []
        
    except Exception as e:
        log_activity("SOLANA_SCAN", f"Scan failed: {e}", "error")
        return []

def send_solana_alert(app, alerts):
    """Send Solana smart wallet alerts"""
    if not alerts or not SOLANA_CHAT_ID:
        return
    
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        message = "🐋 *SOLANA SMART WALLET ALERT*\n"
        message += "_Early token signals from Solana network_\n\n"
        
        for alert in alerts:
            price = alert.get('price', '0')
            price_str = f"${float(price):.6f}" if float(price) < 1 else f"${float(price):.2f}"
            liquidity_str = f"${alert['liquidity']/1_000:.1f}K"
            volume_str = f"${alert['volume_24h']/1_000:.1f}K"
            
            message += f"{alert['alert_type']}\n"
            message += f"*{alert['name']} ({alert['symbol']})*\n"
            message += f"💰 Price: {price_str} | 24h: {'+' if alert['price_change_24h'] > 0 else ''}{alert['price_change_24h']:.1f}%\n"
            message += f"💧 Liq: {liquidity_str} | 📊 Vol: {volume_str}\n"
            message += f"🔗 [DexScreener]({alert['dex_screener_url']}) | [Raydium]({alert['raydium_url']})\n\n"
            
            # Store to knowledge base for backtest
            solana_record = (
                f"[SOLANA GEM] {alert['name']} ({alert['symbol']}) - "
                f"Price: {price_str}, 24h: +{alert['price_change_24h']:.1f}%, "
                f"Liquidity: {liquidity_str}, Volume: {volume_str}, "
                f"Type: {alert['alert_type']}, Token: {alert['token_address']}"
            )
            store_knowledge(f"solana:{alert['symbol']}", solana_record)
        
        message += "_\n⚠️ Always do your own research!_"
        
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)
        loop.run_until_complete(bot.send_message(
            chat_id=int(SOLANA_CHAT_ID),
            text=message,
            parse_mode="Markdown"
        ))
        
        log_activity("SOLANA_SCAN", f"Sent alert to chat {SOLANA_CHAT_ID} and stored {len(alerts)} records", "success")
        loop.close()
        
    except Exception as e:
        log_activity("SOLANA_SCAN", f"Failed to send alert: {e}", "error")

def run_solana_scanner(app):
    """Background scanner for Solana smart wallet activity"""
    log_activity("SOLANA_SCANNER", f"Solana scanner started - will run every {SOLANA_SCAN_INTERVAL} minutes")
    
    while True:
        try:
            alerts = scan_smart_wallets()
            if alerts:
                send_solana_alert(app, alerts)
        except Exception as e:
            log_activity("SOLANA_SCANNER", f"Error: {e}", "error")
        
        # Sleep for configured interval (default 60 minutes)
        time.sleep(SOLANA_SCAN_INTERVAL * 60)


# === WALLET TRACKER ===
def get_solana_rpc():
    """Get Solana RPC URL"""
    return SOLANA_RPC_URL

def make_rpc_request(method, params, timeout=30):
    """Make RPC request to Solana"""
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
        log_activity("WALLET_TRACKER", f"RPC error: {e}", "error")
        return None

def get_wallet_transactions(wallet_address, limit=20):
    """Get recent transactions for a wallet"""
    try:
        # First get signatures
        sigs_resp = make_rpc_request("getSignaturesForAddress", [
            wallet_address,
            {"limit": limit}
        ])
        
        if not sigs_resp or 'result' not in sigs_resp:
            return []
        
        signatures = [s['signature'] for s in sigs_resp['result']]
        
        # Then get transaction details
        tx_details = []
        for sig in signatures[:10]:  # Limit to 10 for speed
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
        log_activity("WALLET_TRACKER", f"Get tx error: {e}", "error")
        return []

def parse_solana_transactions(wallet_address, txs):
    """Parse transactions to extract token swaps"""
    tokens_bought = []
    tokens_sold = []
    
    for tx in txs:
        try:
            meta = tx.get('meta', {})
            post_balances = meta.get('postBalances', [])
            pre_balances = meta.get('preBalances', [])
            
            # Check for token transfers
            for i, (pre, post) in enumerate(zip(pre_balances, post_balances)):
                diff = post - pre
                
                # SOL balance change (not this wallet, skip index 0)
                if i > 0 and abs(diff) > 1000000:  # > 0.001 SOL
                    pass
            
            # Parse inner instructions for token swaps
            inner_instructions = meta.get('innerInstructions', [])
            for inst_group in inner_instructions:
                for inst in inst_group.get('instructions', []):
                    parsed = inst.get('parsed', {})
                    if isinstance(parsed, dict):
                        inst_type = parsed.get('type', '')
                        if inst_type in ['transfer', 'swap']:
                            info = parsed.get('info', {})
                            
                            if inst_type == 'swap':
                                # This is likely a swap transaction
                                pass
                            
                            # Extract token info
                            if 'mint' in info:
                                mint = info['mint']
                                if mint and mint != wallet_address:
                                    amount = info.get('amount', '0')
                                    if int(amount) > 0:
                                        if diff < 0:  # Selling SOL/token
                                            tokens_sold.append({
                                                'mint': mint,
                                                'amount': amount,
                                                'tx': tx['signature'][:20]
                                            })
                                        else:  # Buying
                                            tokens_bought.append({
                                                'mint': mint,
                                                'amount': amount,
                                                'tx': tx['signature'][:20]
                                            })
        
        except Exception:
            continue
    
    return {
        'bought': tokens_bought,
        'sold': tokens_sold
    }

def get_token_info(mint_address):
    """Get token info from mint address"""
    try:
        # Try to get token metadata
        resp = make_rpc_request("getTokenMint", [mint_address])
        if resp and 'result' in resp:
            data = resp['result']
            return {
                'mint': mint_address,
                'decimals': data.get('decimals', 0),
                'supply': data.get('data', {}).get('supply', 0),
                'frozen': data.get('data', {}).get('frozen', False)
            }
        
        # Fallback: use DexScreener
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

def analyze_wallet_activity(wallet_address):
    """Analyze what a wallet has been doing"""
    log_activity("WALLET_TRACKER", f"Analyzing wallet: {wallet_address}")
    
    try:
        # Get recent transactions
        txs = get_wallet_transactions(wallet_address, limit=15)
        
        if not txs:
            return None
        
        # Parse transactions
        activity = {
            'recent_txs': len(txs),
            'last_activity': txs[0].get('blockTime'),
            'tokens_traded': set(),
            'total_volume': 0
        }
        
        # Simple analysis - just get token mints from changes
        for tx in txs:
            meta = tx.get('meta', {})
            
            # Get token balance changes
            post_token_balances = meta.get('postTokenBalances', [])
            pre_token_balances = meta.get('preTokenBalances', [])
            
            for bal in post_token_balances:
                mint = bal.get('mint', '')
                if mint and mint != 'So11111111111111111111111111111111111111112':  # Not SOL
                    activity['tokens_traded'].add(mint)
            
            # Estimate volume from SOL changes
            pre_sol = pre_token_balances[0].get('uiTokenAmount', {}).get('uiAmountString', '0') if pre_token_balances else '0'
            post_sol = post_token_balances[0].get('uiTokenAmount', {}).get('uiTokenAmount', {}).get('uiAmountString', '0') if post_token_balances else '0'
            
            try:
                activity['total_volume'] += abs(float(post_sol) - float(pre_sol))
            except:
                pass
        
        activity['tokens_traded'] = list(activity['tokens_traded'])
        
        # Get token details
        token_details = []
        for mint in activity['tokens_traded'][:5]:
            info = get_token_info(mint)
            if info:
                token_details.append(info)
        
        activity['token_details'] = token_details
        
        return activity
        
    except Exception as e:
        log_activity("WALLET_TRACKER", f"Analysis error: {e}", "error")
        return None


# === GMGN MEMECOIN SCANNER ===
GMGN_SENT_ALERTS = set()  # Track alerted token addresses

def fetch_gmgn_tokens(chain='sol', time_period='1h', orderby='smartmoney', limit=50):
    """Fetch trending tokens from GMGN API with DexScreener fallback"""
    try:
        # Try GMGN first
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
            log_activity("GMGN_SCAN", "GMGN API 403 - trying DexScreener fallback", "warning")
        
        # Fallback: Use DexScreener search endpoint
        sol_url = "https://api.dexscreener.com/latest/dex/search?q=solana"
        sol_resp = requests.get(sol_url, timeout=15)
        if sol_resp.status_code == 200:
            sol_data = sol_resp.json()
            pairs = sol_data.get('pairs') or []
            
            # Deduplicate by token symbol (keep highest volume)
            seen_symbols = {}
            tokens = []
            for pair in pairs[:limit*2]:
                base = pair.get('baseToken', {})
                token_address = base.get('address', '')
                symbol = base.get('symbol', '').upper()
                if not token_address or not symbol:
                    continue
                
                volume = float(pair.get('volume', {}).get('h24', 0) or 0)
                
                # Keep the pair with highest volume for each symbol
                if symbol in seen_symbols:
                    if volume <= seen_symbols[symbol]['volume']:
                        continue
                
                seen_symbols[symbol] = {'address': token_address, 'volume': volume}
                
                tokens.append({
                    'address': token_address,
                    'symbol': symbol,
                    'name': base.get('name', ''),
                    'price': float(pair.get('priceUsd', 0) or 0),
                    'price_change_1h': float(pair.get('priceChange', {}).get('h1', 0) or 0),
                    'volume': volume,
                    'liquidity': float(pair.get('liquidity', {}).get('usd', 0) or 0),
                    'market_cap': float(pair.get('fdv', 0) or 0),
                    'holder_count': 0,
                    'smart_buy_24h': int(volume // 10000),
                    'smart_sell_24h': 0,
                    'is_honeypot': False,
                    'is_verified': False
                })
            
            log_activity("GMGN_SCAN", f"Using DexScreener fallback: {len(tokens)} unique tokens", "success")
            return tokens[:limit]
        
        return []
    except Exception as e:
        log_activity("GMGN_SCAN", f"Failed to fetch tokens: {e}", "error")
        return []


def scan_gmgn_tokens():
    """Scan for trending memecoins on GMGN with smart money activity"""
    global GMGN_SENT_ALERTS
    
    if not GMGN_ENABLED:
        return []
    
    log_activity("GMGN_SCAN", "Scanning GMGN for trending memecoins...")
    
    alerts = []
    
    try:
        # Get tokens sorted by smartmoney activity (last 1h)
        tokens = fetch_gmgn_tokens(chain='sol', time_period='1h', orderby='smartmoney', limit=50)
        
        for token in tokens:
            try:
                token_address = token.get('address', '')
                if not token_address or token_address in GMGN_SENT_ALERTS:
                    continue
                
                # Get token metrics
                price = float(token.get('price', 0))
                volume_24h = float(token.get('volume', 0))
                liquidity = float(token.get('liquidity', 0))
                market_cap = float(token.get('market_cap', 0))
                holder_count = int(token.get('holder_count', 0))
                smart_buy_24h = int(token.get('smart_buy_24h', 0))
                smart_sell_24h = int(token.get('smart_sell_24h', 0))
                price_change_1h = float(token.get('price_change_1h', 0))
                
                # Skip if no activity (for DexScreener fallback, use volume)
                if smart_buy_24h < 3 and volume_24h < 10000:
                    continue
                
                # Check safety filters
                is_honeypot = token.get('is_honeypot', False)
                is_verified = token.get('is_verified', False)
                
                # Determine alert type based on smart money activity
                alert_type = ""
                is_early = False
                
                # New gem with smart money accumulation
                if holder_count > 0 and holder_count < 100 and smart_buy_24h >= 5:
                    alert_type = "💎 EARLY GEM"
                    is_early = True
                # Strong smart money buying
                elif smart_buy_24h >= smart_sell_24h * 2 and smart_buy_24h >= 10:
                    alert_type = "🐋 WHALE BUYING"
                    is_early = True
                # Trending with momentum (works with DexScreener data)
                elif volume_24h > 30000 and price_change_1h > 10:
                    alert_type = "🔥 TRENDING"
                    is_early = True
                # Low cap high gain
                elif market_cap > 0 and market_cap < 500000 and price_change_1h > 20:
                    alert_type = "🚀 MOONSHOT"
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
                        'gmgn_url': f"https://gmgn.ai/sol/coin/{token_address}"
                    })
                    
                    GMGN_SENT_ALERTS.add(token_address)
                    
                    if len(GMGN_SENT_ALERTS) > 100:
                        GMGN_SENT_ALERTS = set(list(GMGN_SENT_ALERTS)[-100:])
            except Exception:
                continue
        
        log_activity("GMGN_SCAN", f"Found {len(alerts)} potential gems", "success")
        return alerts
        
    except Exception as e:
        log_activity("GMGN_SCAN", f"Scan error: {e}", "error")
        return []


def send_gmgn_alert(app, alerts):
    """Send GMGN scan results to configured chat"""
    if not alerts or not SOLANA_CHAT_ID:
        return
    
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        message = "💎 *GMGN MEMECOIN ALERT*\n"
        message += "_Smart money tracking from GMGN_\n\n"
        
        for alert in alerts:
            price = alert.get('price', 0)
            price_str = f"${price:.6f}" if price < 0.01 else f"${price:.4f}"
            liquidity_str = f"${alert['liquidity']/1_000:.1f}K"
            volume_str = f"${alert['volume_24h']/1_000:.1f}K"
            smart_buys = alert.get('smart_buy_24h', 0)
            holders = alert.get('holder_count', 0)
            
            # Safety indicators
            safety = "✅" if not alert.get('is_honeypot') else "⚠️HONEYPOT"
            
            message += f"{alert['alert_type']} {safety}\n"
            message += f"*{alert['name']} ({alert['symbol']})*\n"
            message += f"💰 Price: {price_str} | 1h: {'+' if alert['price_change_1h'] > 0 else ''}{alert['price_change_1h']:.1f}%\n"
            message += f"📊 Vol: {volume_str} | 💧 Liq: {liquidity_str}\n"
            message += f"🐋 Smart Buys: {smart_buys} | 👥 Holders: {holders}\n"
            message += f"🔗 [GMGN]({alert['gmgn_url']})\n\n"
            
            # Store to knowledge base
            gmgn_record = (
                f"[GMGN GEM] {alert['name']} ({alert['symbol']}) - "
                f"Price: {price_str}, 1h: {alert['price_change_1h']:.1f}%, "
                f"Smart Buys: {smart_buys}, Holders: {holders}, "
                f"Type: {alert['alert_type']}, Token: {alert['token_address']}"
            )
            store_knowledge(f"gmgn:{alert['symbol']}", gmgn_record)
        
        message += "_\n⚠️ Always do your own research!_"
        
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)
        loop.run_until_complete(bot.send_message(
            chat_id=int(SOLANA_CHAT_ID),
            text=message,
            parse_mode="Markdown"
        ))
        loop.close()
        log_activity("GMGN_SCAN", f"Sent alert to chat {SOLANA_CHAT_ID}", "success")
    except Exception as e:
        log_activity("GMGN_SCAN", f"Failed to send alert: {e}", "error")


def run_gmgn_scanner(app):
    """Background scanner for GMGN memecoins"""
    log_activity("GMGN_SCANNER", "GMGN scanner started - will scan every 30 minutes")
    
    while True:
        try:
            alerts = scan_gmgn_tokens()
            if alerts:
                send_gmgn_alert(app, alerts)
        except Exception as e:
            log_activity("GMGN_SCANNER", f"Error: {e}", "error")
        
        time.sleep(1800)  # 30 minutes


# === BACKTEST SYSTEM ===
def get_current_prices(symbols):
    """Get current prices for given symbols from CoinGecko"""
    try:
        # Get top coins to find matching symbols
        url = f"{COINGECKO_API_URL}/coins/markets"
        params = {'vs_currency': 'usd', 'order': 'market_cap_desc', 'per_page': 200, 'page': 1}
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        # Build price map
        price_map = {}
        for coin in data:
            sym = coin.get('symbol', '').upper()
            price_map[sym] = {
                'price': coin.get('current_price', 0),
                'name': coin.get('name', ''),
                'image': coin.get('image', ''),
                'market_cap': coin.get('market_cap', 0)
            }
        
        # Also check Solana tokens via DexScreener
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
        log_activity("BACKTEST", f"Failed to get prices: {e}", "error")
        return {}

def run_backtest(app):
    """Run backtest to check performance of scanned gems"""
    if not BACKTEST_ENABLED:
        return
    
    log_activity("BACKTEST", "Starting backtest check...")
    
    try:
        # Get all scan records from knowledge base
        db = get_db()
        scan_records = db.execute(
            "SELECT id, source, text, timestamp FROM knowledge WHERE source LIKE 'scan:%' OR source LIKE 'solana:%'"
        ).fetchall()
        
        if not scan_records:
            log_activity("BACKTEST", "No scan records found", "success")
            return
        
        # Extract symbols and get current prices
        symbols = set()
        scan_by_symbol = {}  # Keep only latest scan per symbol
        for record in scan_records:
            source = record[1]
            symbol = source.split(':')[-1].upper()
            timestamp = record[3]
            # Keep only the most recent scan for each symbol
            if symbol not in scan_by_symbol or timestamp > scan_by_symbol[symbol][1]:
                scan_by_symbol[symbol] = (record, timestamp)
        
        symbols = set(scan_by_symbol.keys())
        
        current_prices = get_current_prices(symbols)
        
        # Analyze each record
        success_count = 0
        failure_count = 0
        pending_count = 0
        report_lines = ["📊 *BACKTEST REPORT*\n"]
        
        from datetime import datetime
        report_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        for record, timestamp in scan_by_symbol.values():
            record_id, source, text, timestamp = record
            symbol = source.split(':')[-1].upper()
            
            # Try to extract entry price from stored text
            # Format: "[GEM SCAN] Pepe (PEPE) - Price: $0.0000012..."
            entry_price = None
            try:
                if 'Price:' in text:
                    price_str = text.split('Price:')[1].split(',')[0].replace('$', '').replace(' ', '')
                    entry_price = float(price_str)
            except:
                pass
            
            if not entry_price or symbol not in current_prices:
                pending_count += 1
                continue
            
            current_price = current_prices[symbol]['price']
            
            if entry_price > 0:
                change_pct = ((current_price - entry_price) / entry_price) * 100
                
                # Determine status
                if change_pct >= BACKTEST_SUCCESS_THRESHOLD:
                    status = "✅ SUCCESS"
                    status_emoji = "🟢"
                    success_count += 1
                elif change_pct <= BACKTEST_FAILURE_THRESHOLD:
                    status = "❌ FAILED"
                    status_emoji = "🔴"
                    failure_count += 1
                else:
                    status = "⏳ PENDING"
                    status_emoji = "🟡"
                    pending_count += 1
                
                ts = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
                entry_str = f"${entry_price:.6f}" if entry_price < 1 else f"${entry_price:.2f}"
                current_str = f"${current_price:.6f}" if current_price < 1 else f"${current_price:.2f}"
                
                report_lines.append(
                    f"{status_emoji} *{symbol}* ({ts})\n"
                    f"Entry: {entry_str} → Current: {current_str}\n"
                    f"Change: {'+' if change_pct > 0 else ''}{change_pct:.1f}% - {status}\n"
                )
        
        # Build final report
        if success_count > 0 or failure_count > 0:
            total = success_count + failure_count + pending_count
            success_rate = (success_count / total * 100) if total > 0 else 0
            
            report = "📊 *BACKTEST REPORT*\n"
            report += f"_Generated: {report_date}_\n\n"
            report += f"📈 Success: {success_count} | ❌ Failed: {failure_count} | ⏳ Pending: {pending_count}\n"
            report += f"🎯 Win Rate: {success_rate:.1f}%\n\n"
            report += "*Recent Signals:*\n"
            report += "\n".join(report_lines[1:])  # Skip the header line we added earlier
            report += "\n\n_Use /backtest anytime to check performance_"
            
            # Send to chat if configured
            if BACKTEST_CHAT_ID:
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    from telegram import Bot
                    bot = Bot(token=TELEGRAM_TOKEN)
                    loop.run_until_complete(bot.send_message(
                        chat_id=int(BACKTEST_CHAT_ID),
                        text=report,
                        parse_mode="Markdown"
                    ))
                    loop.close()
                    log_activity("BACKTEST", f"Sent report to chat {BACKTEST_CHAT_ID}", "success")
                except Exception as e:
                    log_activity("BACKTEST", f"Failed to send report: {e}", "error")
        
        log_activity("BACKTEST", f"Completed: {success_count} success, {failure_count} failed, {pending_count} pending", "success")
        
    except Exception as e:
        log_activity("BACKTEST", f"Error: {e}", "error")

def run_backtest_scheduler(app):
    """Run backtest on schedule"""
    log_activity("BACKTEST_SCHEDULER", f"Backtest scheduler started - will run every {BACKTEST_INTERVAL_HOURS} hours")
    
    while True:
        try:
            run_backtest(app)
        except Exception as e:
            log_activity("BACKTEST_SCHEDULER", f"Error: {e}", "error")
        
        # Sleep for configured interval
        time.sleep(BACKTEST_INTERVAL_HOURS * 3600)

# Helper: Initialize Twitter/X client
def get_twitter_client():
    if not TWEEPY_AVAILABLE or not TWITTER_BEARER_TOKEN:
        return None
    try:
        client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
        log_activity("TWITTER_INIT", "Twitter client initialized successfully", "success")
        return client
    except Exception as e:
        log_activity("TWITTER_INIT", f"Failed to initialize Twitter client: {e}", "error")
        logger.error(f"Failed to initialize Twitter client: {e}")
        return None

def fetch_tweets(query, max_results=10, trusted_only=False):
    """Fetch recent tweets matching a keyword/hashtag"""
    global TWITTER_ERROR_MSG, TWITTER_ERROR_CODE
    TWITTER_ERROR_MSG = ""
    TWITTER_ERROR_CODE = None

    log_activity("TWITTER_FETCH", f"Fetching tweets for query='{query}', max_results={max_results}, trusted_only={trusted_only}")
    logger.info(f"fetch_tweets start: query='{query}', max_results={max_results}, trusted_only={trusted_only}")

    if not TWEEPY_AVAILABLE or not TWITTER_BEARER_TOKEN:
        TWITTER_ERROR_MSG = "Tweepy not available or missing bearer token."
        logger.warning("fetch_tweets aborted: Tweepy unavailable or missing bearer token")
        return []
    try:
        client = get_twitter_client()
        if not client:
            TWITTER_ERROR_MSG = "Failed to initialize Twitter client."
            logger.warning("fetch_tweets aborted: failed to initialize Twitter client")
            return []

        # Build query with safe defaults for more results
        safe_query = query.strip()
        if not safe_query:
            TWITTER_ERROR_MSG = "Empty query."
            return []

        # Add filter for non-retweets and language according to BOT_LANGUAGE
        if 'is:retweet' not in safe_query.lower():
            safe_query += ' -is:retweet'
        if BOT_LANGUAGE == 'id':
            safe_query += ' lang:id'
        else:
            safe_query += ' lang:en'

        tweets = client.search_recent_tweets(
            query=safe_query,
            max_results=min(max_results, 100),
            tweet_fields=['created_at', 'author_id', 'lang'],
            expansions=['author_id'],
            user_fields=['username']
        )
        
        if not tweets.data:
            return []
        
        # Extract user info from includes
        user_map = {}
        if tweets.includes and 'users' in tweets.includes:
            for user in tweets.includes['users']:
                user_map[user.id] = user.username
        
        result = []
        for tweet in tweets.data:
            author = user_map.get(tweet.author_id, 'unknown')
            
            # Filter by trusted accounts if enabled
            if trusted_only and TRUSTED_TWITTER_ACCOUNTS:
                if author.lower() not in [x.lower() for x in TRUSTED_TWITTER_ACCOUNTS]:
                    continue
            
            result.append({
                'text': tweet.text,
                'author': author,
                'created_at': tweet.created_at.isoformat() if tweet.created_at else '',
                'tweet_id': tweet.id
            })
        return result
    except Exception as e:
        TWITTER_ERROR_MSG = str(e)
        if hasattr(e, 'response') and e.response is not None:
            TWITTER_ERROR_CODE = getattr(e.response, 'status_code', None)
        elif hasattr(e, 'status_code'):
            TWITTER_ERROR_CODE = getattr(e, 'status_code', None)
        elif isinstance(e, tweepy.errors.TooManyRequests):
            TWITTER_ERROR_CODE = 429
        logger.error(f"Error fetching tweets: {e}")
        log_activity("TWITTER_FETCH", f"Failed to fetch tweets: {e}", "error")
        return []

# Helper: call OpenRouter for summarization / QA with retry & backoff
def openrouter_chat(prompt: str, system: str = "You are a helpful crypto analyst.") -> str:
    log_activity("LLM_CALL", f"Calling OpenRouter with system='{system[:30]}...' and prompt length={len(prompt)}")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 800,  # Increased for daily summary
    }
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            # If we get a non-200, raise for status to trigger except
            resp.raise_for_status()
            result = resp.json()
            # Log raw response for debugging (ensure we don't break on unicode)
            logger.debug(f"OpenRouter raw response: {result}")
            # Extract content safely
            message = result.get('choices', [{}])[0].get('message', {})
            content = message.get('content')
            if content is None:
                # Some models may return a refusal instead of content
                refusal = message.get('refusal')
                if refusal:
                    logger.warning(f"OpenRouter refused: {refusal}")
                    log_activity("LLM_CALL", f"OpenRouter refused: {refusal[:50]}...", "warning")
                    return refusal.strip()
                else:
                    # Fallback: if there is reasoning, use it; otherwise generic message
                    reasoning = message.get('reasoning')
                    if reasoning:
                        logger.warning("OpenRouter returned reasoning instead of content")
                        log_activity("LLM_CALL", "OpenRouter returned reasoning instead of content", "warning")
                        return reasoning.strip()
                    logger.warning("OpenRouter returned empty content and no refusal")
                    log_activity("LLM_CALL", "OpenRouter returned empty content and no refusal", "warning")
                    return "Sorry, I couldn't generate a response."
            log_activity("LLM_CALL", f"Successfully got response, length={len(content)}", "success")
            return content.strip()
        except requests.exceptions.RequestException as e:
            logger.warning(f"OpenRouter request attempt {attempt+1} failed: {e}")
            log_activity("LLM_CALL", f"Attempt {attempt+1} failed: {e}", "retry")
            if attempt < max_retries - 1:
                # exponential backoff with jitter
                sleep_time = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(sleep_time)
            else:
                logger.error(f"OpenRouter error after {max_retries} attempts: {e}")
                log_activity("LLM_CALL", f"OpenRouter error after {max_retries} attempts: {e}", "error")
                return "Sorry, I couldn't process that request."
        except (KeyError, IndexError, ValueError) as e:
            # JSON parsing errors or unexpected structure
            logger.error(f"OpenRouter response parsing error: {e}")
            logger.debug(f"OpenRouter raw response: {resp.text if 'resp' in locals() else 'no response'}")
            log_activity("LLM_CALL", f"Response parsing error: {e}", "error")
            return "Sorry, I couldn't process that request."

# Scheduled daily news function
def send_daily_news():
    """Send daily crypto news summary at scheduled time"""
    log_activity("SCHEDULED_NEWS", f"Starting daily news generation at {datetime.now()}")
    
    if not SCHEDULE_ENABLED:
        log_activity("SCHEDULED_NEWS", "Schedule disabled, skipping", "warning")
        return
    
    if not SCHEDULE_CHAT_ID:
        log_activity("SCHEDULED_NEWS", "No chat ID configured, skipping", "warning")
        return
    
    try:
        # Fetch news from CoinGecko
        news = fetch_latest_news(limit=10)
        
        # Fetch tweets if available
        tweets_data = []
        if TWEEPY_AVAILABLE and TWITTER_BEARER_TOKEN:
            tweets_data = fetch_tweets("crypto OR bitcoin OR ethereum OR memecoin", max_results=5)
        
        # Combine data for summary
        combined_data = f"=== COINGECKO NEWS ===\n{news}\n\n"
        if tweets_data:
            tweets_text = "\n".join([f"- @{t['author']}: {t['text'][:200]}" for t in tweets_data])
            combined_data += f"=== TWITTER/X UPDATES ===\n{tweets_text}"
        
        # Generate AI summary
        if BOT_LANGUAGE == "id":
            prompt = (
                f"Ringkaslah perkembangan crypto dari 24 jam terakhir dalam format berikut:\n"
                f"1. 📰 NEWS: Ringkasan 3-5 berita terpenting dari CoinGecko - SELALU sertakan link sumber (contoh: coingecko.com/en/news)\n"
                f"2. 🐦 TRENDS: Insight dari tweet terbaru tentang crypto\n"
                f"3. 💡 ANALISIS: Apa yang perlu diperhatikan untuk hari ini\n"
                f"4. 🎯 OUTLOOK: Prediksi singkat untuk market hari ini\n\n"
                f"IMPORTANT: Setiap berita wajib ada link sumber! Contoh: (sumber: coingecko.com/...) atau (link: ...)\n\n"
                f"Data:\n{combined_data}\n\nRESPOND ENTIRELY IN INDONESIAN."
            )
            system_msg = "Anda adalah analis crypto professional yang memberikan update harian dalam bahasa Indonesia yang natural dan mudah dipahami. SELALU sertakan link sumber untuk setiap berita."
        else:
            prompt = (
                f"Summarize the crypto developments from the last 24 hours in the following format:\n"
                f"1. 📰 NEWS: Summary of 3-5 important news from CoinGecko\n"
                f"2. 🐦 TRENDS: Insights from latest crypto tweets\n"
                f"3. 💡 ANALYSIS: What to watch for today\n"
                f"4. 🎯 OUTLOOK: Brief market prediction for today\n\n"
                f"Data:\n{combined_data}"
            )
            system_msg = "You are a professional crypto analyst providing daily updates."
        
        summary = openrouter_chat(prompt, system=system_msg)
        
        # Send to configured chat with source links
        source_links = ""
        try:
            resp = requests.get(f"{COINGECKO_NEWS_URL}?page=1", timeout=10)
            if resp.status_code == 200:
                news_data = resp.json()
                items = news_data.get('data', [])[:5]
                source_links = "📚 *Sumber:*\n"
                for item in items:
                    title = item.get('title', '')[:50]
                    url = item.get('url', '')
                    if url:
                        source_links += f"• [{title}...]({url})\n"
        except:
            pass
        
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            from telegram import Bot
            bot = Bot(token=TELEGRAM_TOKEN)
            message = f"📅 *Daily Crypto Update - {datetime.now().strftime('%d %B %Y')}*\n\n{summary}\n\n{source_links}"
            loop.run_until_complete(bot.send_message(
                chat_id=int(SCHEDULE_CHAT_ID), 
                text=message, 
                parse_mode="Markdown"
            ))
            log_activity("SCHEDULED_NEWS", f"Sent daily news to chat {SCHEDULE_CHAT_ID}", "success")
        except Exception as e:
            log_activity("SCHEDULED_NEWS", f"Failed to send to chat: {e}", "error")
            
    except Exception as e:
        log_activity("SCHEDULED_NEWS", f"Error generating daily news: {e}", "error")

def run_scheduler():
    """Run the scheduler in a background thread"""
    if not SCHEDULE_AVAILABLE:
        log_activity("SCHEDULER", "Schedule module not available, skipping", "error")
        return
        
    log_activity("SCHEDULER", f"Scheduler started, will run at {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} WITA")
    
    # Schedule the daily news
    schedule.every().day.at(f"{SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}").do(send_daily_news)
    
    log_activity("SCHEDULER", f"Daily news scheduled for {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}")
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

# Global auto-detect flag
AUTO_DETECT_LANG = os.getenv("AUTO_DETECT_LANG", "false").lower() == "true"

# Telegram command handlers
async def set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_LANGUAGE, AUTO_DETECT_LANG
    log_activity("CMD_SET_LANG", f"User triggered set_lang with args: {context.args}")
    if not context.args:
        await update.message.reply_text(translate("set_lang_usage"))
        return
    chosen = context.args[0].lower()
    if chosen == "auto":
        AUTO_DETECT_LANG = True
        await update.message.reply_text(translate("auto_detect"))
    elif chosen in ["en", "id"]:
        AUTO_DETECT_LANG = False
        BOT_LANGUAGE = chosen
        await update.message.reply_text(translate("set_lang_success").format(lang=chosen))
    else:
        await update.message.reply_text(translate("set_lang_usage"))
    log_activity("CMD_SET_LANG", f"Language changed to: {chosen}", "success")


async def tweets_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global TWITTER_FALLBACK_MODE
    log_activity("CMD_TWEETS_FALLBACK", f"User triggered tweets_fallback with args: {context.args}")

    if not context.args or context.args[0].lower() not in ["auto", "on", "off"]:
        await update.message.reply_text(translate("tweets_fallback_usage"))
        return

    TWITTER_FALLBACK_MODE = context.args[0].lower()
    await update.message.reply_text(translate("tweets_fallback_set").format(mode=TWITTER_FALLBACK_MODE))
    log_activity("CMD_TWEETS_FALLBACK", f"FallBack mode set to: {TWITTER_FALLBACK_MODE}", "success")


async def tweets_fallback_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_TWEETS_FALLBACK_STATUS", "User requested tweets_fallback_status")
    twitter_configured = bool(TWITTER_BEARER_TOKEN)
    status_text = translate("tweets_fallback_status").format(
        mode=TWITTER_FALLBACK_MODE,
        twitter="yes" if twitter_configured else "no",
    )
    await update.message.reply_text(status_text)
    log_activity("CMD_TWEETS_FALLBACK_STATUS", f"Status displayed: mode={TWITTER_FALLBACK_MODE}, twitter={twitter_configured}", "success")


async def trust_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_TRUST_LIST", "User requested trusted accounts list")
    if TRUSTED_TWITTER_ACCOUNTS:
        accounts = "\n".join([f"• @{acc}" for acc in TRUSTED_TWITTER_ACCOUNTS])
        await update.message.reply_text(f"🐦 *Trusted Twitter Accounts:*\n{accounts}")
    else:
        await update.message.reply_text("Belum ada trusted accounts. Tambahkan via /trust_add")
    log_activity("CMD_TRUST_LIST", f"Listed {len(TRUSTED_TWITTER_ACCOUNTS)} trusted accounts", "success")


async def trust_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_TRUST_ADD", f"User triggered trust_add with args: {context.args}")
    if not context.args:
        await update.message.reply_text("Cara pakai: /trust_add @username")
        return
    username = context.args[0].strip().replace('@', '').lower()
    if username in [x.lower() for x in TRUSTED_TWITTER_ACCOUNTS]:
        await update.message.reply_text(f"@{username} sudah ada di trusted list.")
        return
    TRUSTED_TWITTER_ACCOUNTS.append(username)
    await update.message.reply_text(f"✅ @{username} ditambahkan ke trusted accounts.")
    log_activity("CMD_TRUST_ADD", f"Added @{username} to trusted accounts", "success")


async def trust_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_TRUST_REMOVE", f"User triggered trust_remove with args: {context.args}")
    if not context.args:
        await update.message.reply_text("Cara pakai: /trust_remove @username")
        return
    username = context.args[0].strip().replace('@', '').lower()
    if username not in [x.lower() for x in TRUSTED_TWITTER_ACCOUNTS]:
        await update.message.reply_text(f"@{username} tidak ada di trusted list.")
        return
    TRUSTED_TWITTER_ACCOUNTS = [x for x in TRUSTED_TWITTER_ACCOUNTS if x.lower() != username]
    await update.message.reply_text(f"❌ @{username} dihapus dari trusted accounts.")
    log_activity("CMD_TRUST_REMOVE", f"Removed @{username} from trusted accounts", "success")


async def wallet_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_WALLET_LIST", "User requested wallet list")
    all_wallets = SOLANA_SMART_WALLETS + USER_ADDED_WALLETS
    if all_wallets:
        msg = "🐋 *Smart Wallets Tracker*\n\n*Built-in:*\n"
        for w in SOLANA_SMART_WALLETS:
            msg += f"• `{w[:20]}...`\n"
        if USER_ADDED_WALLETS:
            msg += "\n*User added:*\n"
            for w in USER_ADDED_WALLETS:
                msg += f"• `{w[:20]}...`\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("Belum ada smart wallets. Tambahkan via /wallet_add")
    log_activity("CMD_WALLET_LIST", f"Listed {len(all_wallets)} wallets", "success")


async def wallet_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_WALLET_ADD", f"User triggered wallet_add with args: {context.args}")
    if not context.args:
        await update.message.reply_text("Cara pakai: /wallet_add <solana_address>\nContoh: /wallet_add 7xKXtg2CW87d97TXJSDpbD5jBkHuTWrPqCg44dFYrCE8")
        return
    
    wallet = context.args[0].strip()
    
    # Basic validation - Solana address is base58, 32-44 chars
    if len(wallet) < 32 or len(wallet) > 44:
        await update.message.reply_text("Invalid Solana address format.")
        return
    
    if wallet in USER_ADDED_WALLETS:
        await update.message.reply_text("Wallet sudah ada di list.")
        return
    
    USER_ADDED_WALLETS.append(wallet)
    await update.message.reply_text(f"✅ Wallet ditambahkan ke smart wallet tracker:\n`{wallet}`", parse_mode="Markdown")
    log_activity("CMD_WALLET_ADD", f"Added wallet: {wallet}", "success")


async def wallet_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_WALLET_REMOVE", f"User triggered wallet_remove with args: {context.args}")
    if not context.args:
        await update.message.reply_text("Cara pakai: /wallet_remove <solana_address>")
        return
    
    wallet = context.args[0].strip()
    if wallet not in USER_ADDED_WALLETS:
        await update.message.reply_text("Wallet tidak ada di user list.")
        return
    
    USER_ADDED_WALLETS.remove(wallet)
    await update.message.reply_text(f"❌ Wallet dihapus: `{wallet}`", parse_mode="Markdown")
    log_activity("CMD_WALLET_REMOVE", f"Removed wallet: {wallet}", "success")


async def wallet_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyze a wallet's recent activity"""
    log_activity("CMD_WALLET_ANALYZE", f"User triggered wallet_analyze with args: {context.args}")
    await update.message.reply_chat_action(action="typing")
    
    if not context.args:
        await update.message.reply_text(
            "Cara pakai: /wallet_analyze <solana_address>\n"
            "Contoh: /wallet_analyze DNfuF1L62WWyW3pNakVkyGGFzVVhj4Yr52jSmdTyeBHm\n"
            "\nAtau tanpa address untuk analyse semua user-added wallets"
        )
        return
    
    wallet = context.args[0].strip()
    
    # Check if it's a known wallet
    all_wallets = SOLANA_SMART_WALLETS + USER_ADDED_WALLETS
    is_known = wallet in SOLANA_SMART_WALLETS
    is_user_added = wallet in USER_ADDED_WALLETS
    
    await update.message.reply_text(f"🔍 Analyzing wallet...\n`{wallet}`")
    
    activity = analyze_wallet_activity(wallet)
    
    if not activity:
        await update.message.reply_text(
            "❌ Tidak dapat mengambil data transaksi.\n"
            "Kemungkinan:\n"
            "- RPC node sedang masalah\n"
            "- Wallet tidak ada di mainnet"
        )
        return
    
    msg = f"📊 *Wallet Analysis*\n"
    msg += f"`{wallet[:32]}...`\n\n"
    
    if is_known:
        msg += "🟢 Built-in smart wallet\n"
    elif is_user_added:
        msg += "🟡 User-added wallet\n"
    
    msg += f"📈 Recent transactions: {activity['recent_txs']}\n"
    
    # Add token details
    if activity.get('token_details'):
        msg += "\n🪙 *Tokens Traded:*\n"
        for token in activity['token_details'][:5]:
            symbol = token.get('symbol', '?')
            name = token.get('name', '')
            price = token.get('price', '0')
            
            if price and price != '0':
                msg += f"• {symbol}: ${float(price):.6f}\n"
            else:
                msg += f"• {symbol}\n"
    else:
        msg += "\n❓ Tidak ada token terdeteksi (mungkin hanya transfer SOL)"
    
    msg += f"\n💰 Est. Volume: ~{activity['total_volume']:.2f} SOL"
    
    if activity.get('last_activity'):
        from datetime import datetime
        dt = datetime.fromtimestamp(activity['last_activity'])
        msg += f"\n🕐 Last activity: {dt.strftime('%Y-%m-%d %H:%M')}"
    
    await update.message.reply_text(msg, parse_mode="Markdown")
    log_activity("CMD_WALLET_ANALYZE", f"Analyzed wallet {wallet}, found {activity['recent_txs']} txs", "success")


async def wallet_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scan all tracked wallets for new activity"""
    log_activity("CMD_WALLET_SCAN", "User triggered wallet_scan")
    await update.message.reply_chat_action(action="typing")
    
    all_wallets = SOLANA_SMART_WALLETS + USER_ADDED_WALLETS
    
    if not all_wallets:
        await update.message.reply_text("Tidak ada wallets untuk discan.")
        return
    
    await update.message.reply_text(f"🔍 Scanning {len(all_wallets)} wallets...")
    
    results = []
    for wallet in all_wallets[:5]:  # Limit to 5 for speed
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
            "Mungkin:\n"
            "- Wallets sedang tidak trading\n"
            "- Hanya hold posisi"
        )
        return
    
    msg = "🐋 *Wallet Scanner Results*\n\n"
    for r in results[:10]:
        price = float(r['price']) if r['price'] != '0' else 0
        price_str = f"${price:.6f}" if price < 0.01 else f"${price:.4f}"
        msg += f"• {r['symbol']}: {price_str} (by {r['wallet']}...)\n"
    
    msg += "\n💡 Ganti /wallet_analyze <address> untuk detail"
    
    await update.message.reply_text(msg, parse_mode="Markdown")
    log_activity("CMD_WALLET_SCAN", f"Found {len(results)} token activities", "success")


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_SEARCH", f"User triggered search with args: {context.args}")
    await update.message.reply_chat_action(action="typing")
    if not context.args:
        await update.message.reply_text(translate("search_usage"))
        return
    query = " ".join(context.args)
    results = search_knowledge(query, limit=5)
    if not results:
        await update.message.reply_text(translate("search_no_results"))
        log_activity("CMD_SEARCH", f"No results for query: {query}", "success")
        return
    lines = [translate("search_results").format(query=query)]
    for i, item in enumerate(results):
        preview = item['text'][:200].replace('\n', ' ')
        lines.append(f"{i+1}. [{item['source']}] {preview}...")
    await update.message.reply_text("\n".join(lines))
    log_activity("CMD_SEARCH", f"Search completed for query: {query}, found {len(results)} results", "success")


async def tweets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_TWEETS", f"User triggered tweets with args: {context.args}")
    await update.message.reply_chat_action(action="typing")
    if not context.args:
        await update.message.reply_text(translate("tweets_usage"))
        return

    use_coingecko_only = any(a.lower() == "--coingecko-only" for a in context.args)
    use_twitter_only = any(a.lower() == "--twitter-only" for a in context.args)
    use_trusted_only = any(a.lower() == "--trusted" for a in context.args)

    args = [a for a in context.args if a.lower() not in ["--coingecko-only", "--twitter-only", "--trusted"]]
    query = " ".join(args).strip()
    if not query:
        await update.message.reply_text(translate("tweets_usage"))
        return

    if use_coingecko_only:
        news = fetch_latest_news(limit=5)
        if not news or news in ["No recent news found.", "Failed to fetch news."]:
            await update.message.reply_text("Tidak ada berita CoinGecko yang ditemukan. Coba lagi nanti.")
            log_activity("CMD_TWEETS", "No CoinGecko news available for fallback", "warning")
            return
        insight_prompt = f"Fallback CoinGecko for '{query}' (coingecko-only request). Summarize this crypto news in 3 points:\n\n{news}"
        insight = openrouter_chat(insight_prompt, system=system_prompt("general"))
        await update.message.reply_text(f"Fallback <Coingecko> for '{query}':\n{news}\n\nInsight:\n{insight}")
        log_activity("CMD_TWEETS", f"Used CoinGecko fallback for query: {query}", "success")
        return

    if not TWITTER_BEARER_TOKEN:
        await update.message.reply_text("X/Twitter integration not configured.")
        log_activity("CMD_TWEETS", "Twitter not configured", "warning")
        return

    tweets_data = fetch_tweets(query, max_results=5, trusted_only=use_trusted_only)

    if not tweets_data:
        if TWITTER_ERROR_MSG:
            err = TWITTER_ERROR_MSG
            code = TWITTER_ERROR_CODE
            do_fallback = (TWITTER_FALLBACK_MODE in ["auto", "on"]) and not use_twitter_only
            if code in (402, 403, 429) and do_fallback:
                news = fetch_latest_news(limit=5)
                if news and news not in ["No recent news found.", "Failed to fetch news."]:
                    fallback_prompt = (
                        f"X/Twitter API returned {code} for query '{query}'. "
                        f"Use CoinGecko crypto news for fallback summarization:\n\n{news}"
                    )
                    fallback_summary = openrouter_chat(fallback_prompt, system=system_prompt("general"))
                    await update.message.reply_text(
                        f"X API error {code}: {err}.\nBerikut fallback berita CoinGecko:\n{news}\n\nInsight:\n{fallback_summary}"
                    )
                    log_activity("CMD_TWEETS", f"Used fallback due to X API error {code}", "success")
                else:
                    await update.message.reply_text(
                        f"X API error {code}: {err}. Gagal ambil fallback dari CoinGecko, coba lagi nanti."
                    )
                    log_activity("CMD_TWEETS", "Failed to use fallback", "error")
                return
            await update.message.reply_text(
                f"X API error {code if code else ''}: {err}. Pastikan akun X Anda memiliki credit/restrictions di API. "
                f"(fallback mode: {TWITTER_FALLBACK_MODE})"
            )
            log_activity("CMD_TWEETS", f"X API error: {code} - {err}", "error")
            return
        await update.message.reply_text(translate("tweets_no_results"))
        log_activity("CMD_TWEETS", "No tweets found", "success")
        return

    lines = [translate("tweets_results").format(query=query)]
    for i, tweet in enumerate(tweets_data):
        # Store tweet in knowledge base for later search
        store_knowledge(f"tweet:@{tweet['author']}", tweet['text'])
        
        # Truncate and format tweet text
        tweet_text = tweet['text'][:150].replace('\n', ' ')
        lines.append(f"{i+1}. @{tweet['author']}: {tweet_text}...")
    
    await update.message.reply_text("\n".join(lines))
    
    # Optionally: fetch more tweets and get AI insight
    if len(tweets_data) > 0:
        combined_tweets = "\n".join([f"- @{t['author']}: {t['text']}" for t in tweets_data[:3]])
        if BOT_LANGUAGE == "id":
            insight_prompt = f"Summarize these crypto tweets in 3 bullet points. Respond entirely in Indonesian:\n{combined_tweets}"
        else:
            insight_prompt = f"Summarize these crypto tweets in 3 bullet points:\n{combined_tweets}"
        
        insight = openrouter_chat(insight_prompt, system="You are a crypto analyst reviewing tweets.")
        await update.message.reply_text(f"📊 Tweet Insight:\n{insight}")
        log_activity("CMD_TWEETS", f"Successfully fetched and summarized {len(tweets_data)} tweets", "success")


async def sentiment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_SENTIMENT", f"User triggered sentiment with args: {context.args}")
    await update.message.reply_chat_action(action="typing")
    
    if not context.args:
        await update.message.reply_text(translate("sentiment_usage"))
        return
    
    coin = " ".join(context.args).strip()
    await update.message.reply_text(translate("sentiment_analyzing").format(coin=coin))
    
    try:
        # Fetch news about the coin
        news = fetch_latest_news(limit=10)
        
        # Also try to get tweets
        tweets_data = []
        if TWITTER_BEARER_TOKEN and TWEEPY_AVAILABLE:
            tweets_data = fetch_tweets(f"{coin} crypto", max_results=5)
        
        # Build prompt for sentiment analysis
        all_data = []
        if news and news not in ["No recent news found.", "Failed to fetch news."]:
            all_data.append(f"=== NEWS ===\n{news}")
        if tweets_data:
            tweets_text = "\n".join([f"- @{t['author']}: {t['text'][:200]}" for t in tweets_data])
            all_data.append(f"=== TWEETS ===\n{tweets_text}")
        
        if not all_data:
            await update.message.reply_text(f"Tidak ada news atau tweet untuk {coin}.")
            return
        
        combined_data = "\n\n".join(all_data)
        
        # Analyze sentiment
        if BOT_LANGUAGE == "id":
            sentiment_prompt = (
                f"Analisis sentiment market untuk {coin} berdasarkan data berikut. "
                f"Berikan:\n"
                f"1. Overall sentiment (Bullish/Bearish/Neutral)\n"
                f"2. Key highlights (3 poin penting)\n"
                f"3. Risk factors (2 risiko utama)\n"
                f"4. Kesimpulan singkat\n\n"
                f"Data:\n{combined_data}"
            )
        else:
            sentiment_prompt = (
                f"Analyze market sentiment for {coin} based on the following data. "
                f"Provide:\n"
                f"1. Overall sentiment (Bullish/Bearish/Neutral)\n"
                f"2. Key highlights (3 important points)\n"
                f"3. Risk factors (2 main risks)\n"
                f"4. Brief conclusion\n\n"
                f"Data:\n{combined_data}"
            )
        
        analysis = openrouter_chat(sentiment_prompt, system="You are a crypto sentiment analyst.")
        
        result = translate("sentiment_result").format(coin=coin)
        result += analysis
        result += f"\n\n_Sumber: {len(all_data)} sources_"
        
        await update.message.reply_text(result, parse_mode="Markdown")
        log_activity("CMD_SENTIMENT", f"Successfully analyzed sentiment for {coin}", "success")
        
    except Exception as e:
        await update.message.reply_text(f"Gagal analisis sentiment: {e}")
        log_activity("CMD_SENTIMENT", f"Error: {e}", "error")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    log_activity("CMD_START", f"User {user.id} started the bot")
    await update.message.reply_text(
        translate("start_both").format(name=user.first_name or "User"),
        parse_mode="Markdown"
    )
    log_activity("CMD_START", f"Sent start greeting to user {user.id}", "success")

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_SUMMARY", "User triggered /summary command")
    await update.message.reply_chat_action(action="typing")
    news = fetch_latest_news(limit=5)
    if not news or news == "No recent news found.":
        await update.message.reply_text("No recent crypto news found.")
        log_activity("CMD_SUMMARY", "No news available", "warning")
        return
    
    if BOT_LANGUAGE == "id":
        prompt = f"Ringkaslah berita kripto berikut dari 24 jam terakhir dalam 3-4 poin bullet, dengan highlight event kunci dan dampak pasar potensial. RESPOND ENTIRELY IN INDONESIAN:\n\n{news}"
    else:
        prompt = f"Summarize the following crypto news from the last 24 hours in 3-4 bullet points, highlighting key events and potential market impact:\n\n{news}"
    
    summary_text = openrouter_chat(prompt, system=system_prompt("summary"))
    await update.message.reply_text(summary_text)
    log_activity("CMD_SUMMARY", "Successfully generated news summary", "success")

async def screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_SCREEN", "User triggered /screen command")
    await update.message.reply_chat_action(action="typing")
    
    if BOT_LANGUAGE == "id":
        prompt = (
            "Berikan daftar singkat 3 cryptocurrency yang potentially undervalued (market cap < $2B) "
            "dengan alasan berdasarkan recent whale accumulation, fundamentals, atau technical indicators. "
            "Untuk setiap coin, sarankan entry zone, stop-loss, dan take-profit target. Respond entirely in Indonesian."
        )
    else:
        prompt = (
            "Give me a short list of 3 potentially undervalued cryptocurrencies (market cap < $2B) "
            "with reasons based on recent whale accumulation, fundamentals, or technical indicators. "
            "For each coin, suggest an entry zone, stop-loss, and take-profit target. Keep it brief."
        )
    advice = openrouter_chat(prompt, system=system_prompt("screen"))
    await update.message.reply_text(advice)
    log_activity("CMD_SCREEN", "Successfully generated screening advice", "success")

async def memecoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_MEMECOIN", "User triggered /memecoin command")
    await update.message.reply_chat_action(action="typing")
    
    if BOT_LANGUAGE == "id":
        prompt = (
            "Identifikasi dua recent memecoin yang telah melihat early smart-wallet accumulation. "
            "Sediakan token name, contract address (jika diketahui), dan alasan singkat mengapa smart wallet activity ini bullish. "
            "Keep the answer concise. Respond entirely in Indonesian."
        )
    else:
        prompt = (
            "Identify two recent memecoins that have seen early smart‑wallet accumulation. "
            "Provide the token name, contract address (if known), and a short reason why the smart wallet activity is bullish. "
            "Keep the answer concise."
        )
    advice = openrouter_chat(prompt, system=system_prompt("memecoin"))
    await update.message.reply_text(advice)
    log_activity("CMD_MEMECOIN", "Successfully generated memecoin advice", "success")

async def learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_LEARN", "User triggered /learn command")
    await update.message.reply_chat_action(action="typing")
    await update.message.reply_text(translate("learn_prompt"))
    log_activity("CMD_LEARN", "Sent learn instructions to user", "success")

async def create_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_CREATE_AGENT", f"User triggered /create_agent with args: {context.args}")
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
    purpose = " ".join(args[1:]) if len(args) > 1 else ("crypto screening and market insight" if BOT_LANGUAGE == "en" else "crypto screening dan market insight")
    
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
    
    if BOT_LANGUAGE == "id":
        await update.message.reply_text(
            f"Profil agen untuk '{agent_name}':\n{agent_profile}\n\n"
            "Gunakan ini sebagai identitas bot dan runbook Anda."
        )
    else:
        await update.message.reply_text(
            f"Agent profile for '{agent_name}':\n{agent_profile}\n\n"
            "Use this as your bot identity and runbook."
        )
    log_activity("CMD_CREATE_AGENT", f"Successfully created agent profile for '{agent_name}'", "success")

async def memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_MEMORY", "User triggered /memory command")
    await update.message.reply_chat_action(action="typing")
    total = count_knowledge()
    if total == 0:
        await update.message.reply_text("Knowledge base is empty.")
        log_activity("CMD_MEMORY", "Knowledge base is empty", "success")
        return

    try:
        count = int(context.args[0]) if context.args else 3
        count = max(1, min(20, count))
    except ValueError:
        count = 3

    items = get_recent_knowledge(count)
    lines = []
    for i, item in enumerate(items):
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item['timestamp']))
        preview = item['text'][:280].replace('\n', ' ')
        lines.append(f"{i+1}. [{ts}] {item['source']}: {preview}...")

    await update.message.reply_text("Memory entries (latest first):\n" + "\n".join(lines))
    log_activity("CMD_MEMORY", f"Displayed {count} memory entries", "success")


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("CMD_HEALTH", "User triggered /health command")
    await update.message.reply_chat_action(action="typing")
    test_prompt = "Say OK in three words."
    openrouter_answer = openrouter_chat(test_prompt, system="You are a simple health-check assistant.")
    stored = count_knowledge()

    # Get chat ID for scheduling
    chat_id = update.effective_chat.id
    
    await update.message.reply_text(
        f"Health check:\n"
        f"- Bot process connected and handling commands.\n"
        f"- Telegram token: {'set' if TELEGRAM_TOKEN and TELEGRAM_TOKEN != 'YOUR_TELEGRAM_BOT_TOKEN' else 'missing or default'}\n"
        f"- OpenRouter key: {'set' if OPENROUTER_API_KEY and OPENROUTER_API_KEY != 'YOUR_OPENROUTER_API_KEY' else 'missing or default'}\n"
        f"- OpenRouter test prompt response: {openrouter_answer[:200]!s}\n"
        f"- Knowledge entries: {stored}\n"
        f"- Schedule: {'enabled' if SCHEDULE_ENABLED else 'disabled'} at {SCHEDULE_HOUR}:{SCHEDULE_MINUTE:02d} WITA\n"
        f"- Your chat_id: `{chat_id}` (use /setschedule to enable daily news)"
    )
    log_activity("CMD_HEALTH", "Health check completed successfully", "success")


async def set_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the chat ID for scheduled messages and enable/disable schedule"""
    global SCHEDULE_CHAT_ID, SCHEDULE_HOUR, SCHEDULE_MINUTE, SCHEDULE_ENABLED, SCAN_CHAT_ID
    log_activity("CMD_SET_SCHEDULE", f"User triggered /setschedule with args: {context.args}")
    
    chat_id = update.effective_chat.id
    
    if not context.args:
        # Show current status
        await update.message.reply_text(
            f"📅 Schedule Status:\n"
            f"- Enabled: {'Yes' if SCHEDULE_ENABLED else 'No'}\n"
            f"- Time: {SCHEDULE_HOUR}:{SCHEDULE_MINUTE:02d} WITA\n"
            f"- Your chat_id: `{chat_id}`\n\n"
            f"Usage:\n"
            f"/setschedule on - Enable daily news to this chat\n"
            f"/setschedule off - Disable daily news\n"
            f"/setschedule time 8:30 - Set time to 8:30 WITA"
        )
        return
    
    action = context.args[0].lower()
    
    if action == "on":
        SCHEDULE_CHAT_ID = str(chat_id)
        SCHEDULE_ENABLED = True
        await update.message.reply_text(
            f"✅ Daily news enabled!\n"
            f"Setiap hari jam {SCHEDULE_HOUR}:{SCHEDULE_MINUTE:02d} WITA, "
            f"saya akan mengirim ringkasan crypto ke chat ini."
        )
        log_activity("CMD_SET_SCHEDULE", f"Enabled schedule for chat {chat_id}", "success")
        
    elif action == "off":
        SCHEDULE_ENABLED = False
        await update.message.reply_text("❌ Daily news disabled.")
        log_activity("CMD_SET_SCHEDULE", "Disabled schedule", "success")
        
    elif action == "time" and len(context.args) > 1:
        try:
            time_str = context.args[1]
            hour, minute = map(int, time_str.split(':'))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                SCHEDULE_HOUR = hour
                SCHEDULE_MINUTE = minute
                await update.message.reply_text(
                    f"⏰ Schedule time updated to {hour:02d}:{minute:02d} WITA"
                )
                log_activity("CMD_SET_SCHEDULE", f"Updated schedule time to {hour:02d}:{minute:02d}", "success")
            else:
                await update.message.reply_text("Invalid time format. Use HH:MM (0-23 for hour, 0-59 for minute)")
        except:
            await update.message.reply_text("Invalid time format. Use HH:MM, contoh: 08:30")
    
    else:
        await update.message.reply_text(
            "Usage:\n"
            "/setschedule on - Enable daily news\n"
            "/setschedule off - Disable daily news\n"
            "/setschedule time 8:30 - Set time"
        )

# Coin Scanner Commands
async def scan_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual coin scan command"""
    global SCAN_CHAT_ID
    log_activity("CMD_SCAN", "User triggered /scan command")
    
    chat_id = update.effective_chat.id
    SCAN_CHAT_ID = str(chat_id)  # Set chat for alerts
    
    await update.message.reply_chat_action(action="typing")
    await update.message.reply_text("🔍 Scanning for potential gems...")
    
    gems = scan_potential_coins()
    
    if not gems:
        await update.message.reply_text(
            "❌ No potential gems found at the moment.\n"
            "Try again later or adjust scan criteria."
        )
        return
    
    message = "🔍 *POTENTIAL GEMS FOUND*\n\n"
    
    for gem in gems:
        price_str = f"${gem['price']:.6f}" if gem['price'] < 1 else f"${gem['price']:.2f}"
        change_1h = f"+{gem['change_1h']:.2f}%" if gem['change_1h'] > 0 else f"{gem['change_1h']:.2f}%"
        change_24h = f"+{gem['change_24h']:.2f}%" if gem['change_24h'] > 0 else f"{gem['change_24h']:.2f}%"
        volume_str = f"${gem['volume']/1_000_000:.1f}M"
        
        message += f"{gem['gem_type']}\n"
        message += f"*{gem['name']} ({gem['symbol']})*\n"
        message += f"💰 Price: {price_str} | 1h: {change_1h} | 24h: {change_24h}\n"
        message += f"📊 Vol: {volume_str}\n"
        message += f"🔗 [CoinGecko]({gem['coingecko_url']}) | [CMC]({gem['coinmarketcap_url']})\n"
        if gem.get('analysis'):
            message += f"💡 *Analisis:* {gem['analysis'][:150]}...\n\n"
        else:
            message += "\n"
        
        # Store to knowledge base for backtest
        scan_record = (
            f"[GEM SCAN] {gem['name']} ({gem['symbol']}) - "
            f"Price: {price_str}, 24h: {change_24h}, Volume: {volume_str}, "
            f"Type: {gem['gem_type']}, Analysis: {gem.get('analysis', 'N/A')[:200]}"
        )
        store_knowledge(f"scan:{gem['symbol']}", scan_record)
    
    message += "_\n⚠️ Do your own research before investing!_"
    
    await update.message.reply_text(message, parse_mode="Markdown")
    log_activity("CMD_SCAN", f"Found {len(gems)} gems and stored in memory", "success")

async def set_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable/disable automatic coin scanner"""
    global SCAN_ENABLED, SCAN_CHAT_ID, SCAN_INTERVAL_MINUTES, SOLANA_ENABLED, SOLANA_CHAT_ID
    log_activity("CMD_SET_SCAN", f"User triggered /setscan with args: {context.args}")
    
    chat_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text(
            f"📊 Scanner Status:\n"
            f"- Auto Scan: {'Enabled' if SCAN_ENABLED else 'Disabled'}\n"
            f"- Interval: Every {SCAN_INTERVAL_MINUTES} minutes\n"
            f"- Your chat_id: `{chat_id}`\n\n"
            f"Usage:\n"
            f"/setscan on - Enable auto scan\n"
            f"/setscan off - Disable auto scan\n"
            f"/setscan interval 15 - Set scan every 15 minutes"
        )
        return
    
    action = context.args[0].lower()
    
    if action == "on":
        SCAN_ENABLED = True
        SCAN_CHAT_ID = str(chat_id)
        await update.message.reply_text(
            f"✅ Auto scanner enabled!\n"
            f"Scan setiap {SCAN_INTERVAL_MINUTES} menit, "
            f"aku akan alert jika ada potential gem!"
        )
        log_activity("CMD_SET_SCAN", f"Enabled auto scan for chat {chat_id}", "success")
        
    elif action == "off":
        SCAN_ENABLED = False
        await update.message.reply_text("❌ Auto scanner disabled.")
        log_activity("CMD_SET_SCAN", "Disabled auto scan", "success")
        
    elif action == "interval" and len(context.args) > 1:
        try:
            interval = int(context.args[1])
            if 5 <= interval <= 1440:
                SCAN_INTERVAL_MINUTES = interval
                await update.message.reply_text(
                    f"⏰ Scan interval updated to {interval} minutes"
                )
                log_activity("CMD_SET_SCAN", f"Updated interval to {interval} minutes", "success")
            else:
                await update.message.reply_text("Invalid interval. Use 5-1440 minutes")
        except:
            await update.message.reply_text("Invalid interval. Use: /setscan interval 15")

# Solana Scanner Commands
async def scan_solana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual Solana smart wallet scan"""
    global SOLANA_CHAT_ID
    log_activity("CMD_SOLANA", "User triggered /solana command")
    
    chat_id = update.effective_chat.id
    SOLANA_CHAT_ID = str(chat_id)
    
    await update.message.reply_chat_action(action="typing")
    await update.message.reply_text("🐋 Scanning Solana for smart wallet activity...")
    
    alerts = scan_smart_wallets()
    
    if not alerts:
        await update.message.reply_text(
            "❌ No significant Solana activity found.\n"
            "Try again later."
        )
        return
    
    message = "🐋 *SOLANA EARLY GEM ALERTS*\n\n"
    
    for alert in alerts:
        price = alert.get('price', '0')
        price_str = f"${float(price):.6f}" if float(price) < 1 else f"${float(price):.2f}"
        liquidity_str = f"${alert['liquidity']/1_000:.1f}K"
        volume_str = f"${alert['volume_24h']/1_000:.1f}K"
        
        message += f"{alert['alert_type']}\n"
        message += f"*{alert['name']} ({alert['symbol']})*\n"
        message += f"💰 Price: {price_str} | 24h: +{alert['price_change_24h']:.1f}%\n"
        message += f"💧 Liq: {liquidity_str} | 📊 Vol: {volume_str}\n"
        message += f"🔗 [DexScreener]({alert['dex_screener_url']}) | [Swap]({alert['raydium_url']})\n\n"
        
        # Store to knowledge base for backtest
        solana_record = (
            f"[SOLANA GEM] {alert['name']} ({alert['symbol']}) - "
            f"Price: {price_str}, 24h: +{alert['price_change_24h']:.1f}%, "
            f"Liquidity: {liquidity_str}, Volume: {volume_str}, "
            f"Type: {alert['alert_type']}, Token: {alert['token_address']}"
        )
        store_knowledge(f"solana:{alert['symbol']}", solana_record)
    
    message += "_\n⚠️ Always do your own research!_"
    
    await update.message.reply_text(message, parse_mode="Markdown")
    log_activity("CMD_SOLANA", f"Found {len(alerts)} Solana alerts and stored in memory", "success")

async def set_solana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable/disable Solana smart wallet scanner"""
    global SOLANA_ENABLED, SOLANA_CHAT_ID
    log_activity("CMD_SET_SOLANA", f"User triggered /setsolana with args: {context.args}")
    
    chat_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text(
            f"🐋 Solana Scanner Status:\n"
            f"- Auto Scan: {'Enabled' if SOLANA_ENABLED else 'Disabled'}\n"
            f"- Your chat_id: `{chat_id}`\n\n"
            f"Usage:\n"
            f"/setsolana on - Enable Solana auto scan\n"
            f"/setsolana off - Disable Solana auto scan"
        )
        return
    
    action = context.args[0].lower()
    
    if action == "on":
        SOLANA_ENABLED = True
        SOLANA_CHAT_ID = str(chat_id)
        await update.message.reply_text(
            "✅ Solana smart wallet scanner enabled!\n"
            "Aku akan alert jika ada early gem di Solana!"
        )
        log_activity("CMD_SET_SOLANA", f"Enabled Solana scan for chat {chat_id}", "success")
        
    elif action == "off":
        SOLANA_ENABLED = False
        await update.message.reply_text("❌ Solana scanner disabled.")
        log_activity("CMD_SET_SOLANA", "Disabled Solana scan", "success")
    else:
        await update.message.reply_text(
            "Usage:\n"
            "/setsolana on - Enable\n"
            "/setsolana off - Disable"
        )


async def scan_gmgn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual GMGN scan for trending memecoins"""
    global SOLANA_CHAT_ID
    log_activity("CMD_GMGN", "User triggered /gmgn command")
    
    chat_id = update.effective_chat.id
    SOLANA_CHAT_ID = str(chat_id)
    
    await update.message.reply_chat_action(action="typing")
    await update.message.reply_text("💎 Scanning GMGN for trending memecoins...")
    
    alerts = scan_gmgn_tokens()
    
    if not alerts:
        await update.message.reply_text(
            "❌ No trending memecoins found.\n"
            "GMGN API mungkin perlu API key (403)."
        )
        return
    
    message = "💎 *GMGN TRENDING MEMECOINS*\n\n"
    
    for alert in alerts:
        price = alert.get('price', 0)
        price_str = f"${price:.6f}" if price < 0.01 else f"${price:.4f}"
        liquidity_str = f"${alert['liquidity']/1_000:.1f}K"
        volume_str = f"${alert['volume_24h']/1_000:.1f}K"
        smart_buys = alert.get('smart_buy_24h', 0)
        holders = alert.get('holder_count', 0)
        
        safety = "✅" if not alert.get('is_honeypot') else "⚠️HONEYPOT"
        
        message += f"{alert['alert_type']} {safety}\n"
        message += f"*{alert['name']} ({alert['symbol']})*\n"
        message += f"💰 Price: {price_str} | 1h: {'+' if alert['price_change_1h'] > 0 else ''}{alert['price_change_1h']:.1f}%\n"
        message += f"📊 Vol: {volume_str} | 💧 Liq: {liquidity_str}\n"
        message += f"🐋 Smart Buys: {smart_buys} | 👥 Holders: {holders}\n"
        message += f"🔗 [GMGN]({alert['gmgn_url']})\n\n"
        
        gmgn_record = (
            f"[GMGN GEM] {alert['name']} ({alert['symbol']}) - "
            f"Price: {price_str}, 1h: {alert['price_change_1h']:.1f}%, "
            f"Smart Buys: {smart_buys}, Holders: {holders}"
        )
        store_knowledge(f"gmgn:{alert['symbol']}", gmgn_record)
    
    message += "_\n⚠️ Always do your own research!_"
    
    await update.message.reply_text(message, parse_mode="Markdown")
    log_activity("CMD_GMGN", f"Found {len(alerts)} GMGN alerts", "success")


async def run_backtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run backtest to check signal performance"""
    global BACKTEST_CHAT_ID
    log_activity("CMD_BACKTEST", "User triggered /backtest command")
    
    chat_id = update.effective_chat.id
    BACKTEST_CHAT_ID = str(chat_id)
    
    await update.message.reply_chat_action(action="typing")
    await update.message.reply_text("📊 Running backtest analysis...")
    
    try:
        run_backtest(None)
        await update.message.reply_text(
            "✅ Backtest complete!\n"
            "Check your chat for the detailed report."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Backtest error: {e}")
        log_activity("CMD_BACKTEST", f"Error: {e}", "error")

# Handle document uploads (PDF/Image) and text messages with URLs
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_LANGUAGE
    log_activity("MSG_RECEIVED", f"User sent message: {update.message.text[:50] if update.message.text else 'document/photo'}")
    
    # Auto-detect language if enabled
    if AUTO_DETECT_LANG and update.message.text:
        detected = detect_language(update.message.text)
        if detected:
            BOT_LANGUAGE = detected
    
    msg = update.message
    if msg.document:
        log_activity("MSG_DOCUMENT", f"Received document: {msg.document.file_name}")
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
                log_activity("MSG_DOCUMENT", "Unsupported file type", "warning")
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
                if BOT_LANGUAGE == "id":
                    await msg.reply_text(
                        f"Extracted {len(text)} characters dari {file_name}.\nRingkasan:\n{summary}"
                    )
                else:
                    await msg.reply_text(
                        f"Extracted {len(text)} characters from {file_name}.\nSummary:\n{summary}"
                    )
                log_activity("MSG_DOCUMENT", f"Successfully processed PDF: {file_name}", "success")
            else:
                await msg.reply_text("PDF extracted no text.")
                log_activity("MSG_DOCUMENT", "PDF had no extractable text", "warning")
        finally:
            try:
                os.remove(temp_file.name)
            except OSError:
                pass
        return

    if msg.photo:
        log_activity("MSG_PHOTO", "Received photo for OCR")
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
                if BOT_LANGUAGE == "id":
                    await msg.reply_text(f"OCR extracted {len(text)} chars.\nRingkasan:\n{summary}")
                else:
                    await msg.reply_text(f"OCR extracted {len(text)} chars.\nSummary:\n{summary}")
                log_activity("MSG_PHOTO", "Successfully processed image OCR", "success")
            else:
                await msg.reply_text("No text found in image.")
                log_activity("MSG_PHOTO", "Image had no text", "warning")
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

        # Check for YouTube link
        if "youtube.com" in text.lower() or "youtu.be" in text.lower():
            log_activity("MSG_YOUTUBE", f"Received YouTube link: {text[:50]}...")
            await msg.reply_text("YouTube link detected! Fetching video info and learning...")
            
            try:
                video_info = extract_text_from_youtube(text)
                if video_info.startswith("YouTube extraction failed"):
                    await msg.reply_text(video_info)
                    log_activity("MSG_YOUTUBE", f"Failed: {video_info}", "error")
                    return
                
                # Store in knowledge base
                store_knowledge(f"youtube:{text}", video_info)
                
                # Generate summary
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
                
                if BOT_LANGUAGE == "id":
                    await msg.reply_text(f"📺 Video learned!\n\nRingkasan:\n{summary}")
                else:
                    await msg.reply_text(f"📺 Video learned!\n\nSummary:\n{summary}")
                
                log_activity("MSG_YOUTUBE", "Successfully processed YouTube video", "success")
            except Exception as e:
                await msg.reply_text(f"Error processing YouTube: {e}")
                log_activity("MSG_YOUTUBE", f"Error: {e}", "error")
            return

        # Check for X/Twitter link
        if "x.com" in text.lower() or "twitter.com" in text.lower():
            log_activity("MSG_TWITTER_LINK", f"Received Twitter/X link: {text[:50]}...")
            await msg.reply_text("🐦 Link Twitter/X detected! Mengambil dan menganalisa...")
            
            try:
                # Extract tweet info from URL
                tweet_id = None
                username = None
                
                # Parse URL to get username and tweet_id
                if "/status/" in text:
                    parts = text.split("/status/")
                    if len(parts) > 1:
                        tweet_id = parts[-1].split("?")[0]
                    # Extract username from URL
                    path_parts = text.split("/")
                    for i, p in enumerate(path_parts):
                        if p == "status" and i > 0:
                            username = path_parts[i-1]
                            break
                
                # Get tweet content if we have API
                tweet_content = ""
                if tweet_id and TWITTER_BEARER_TOKEN and TWEEPY_AVAILABLE:
                    try:
                        client = get_twitter_client()
                        tweet = client.get_tweet(tweet_id, expansions=["author_id"])
                        if tweet.data:
                            tweet_content = f"Tweet by @{tweet.data.username}: {tweet.data.text}"
                    except Exception as tw_e:
                        log_activity("MSG_TWITTER_LINK", f"API error: {tw_e}", "warning")
                
                # Try OEmbed API - free and public!
                if not tweet_content and "/status/" in text:
                    try:
                        oembed_url = f"https://publish.twitter.com/oembed?url={text}"
                        resp = requests.get(oembed_url, timeout=10)
                        if resp.status_code == 200:
                            data = resp.json()
                            html_content = data.get('html', '')
                            # Extract text from embedded HTML
                            import re
                            # Remove HTML tags to get plain text
                            clean_text = re.sub(r'<[^>]+>', '', html_content)
                            # Clean up
                            clean_text = clean_text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                            if clean_text and len(clean_text) > 10:
                                tweet_content = f"Tweet embed:\n{clean_text}"
                                log_activity("MSG_TWITTER_LINK", "Got tweet via OEmbed!", "success")
                    except Exception as oembed_e:
                        log_activity("MSG_TWITTER_LINK", f"OEmbed error: {oembed_e}", "warning")
                
                # Try web scraping as fallback
                if not tweet_content and "/status/" in text:
                    try:
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        }
                        resp = requests.get(text, headers=headers, timeout=10)
                        if resp.status_code == 200:
                            html = resp.text
                            # Try to find tweet content in HTML
                            import re
                            # Look for meta tags or data attributes
                            content_match = re.search(r'"text":"([^"]+)"', html)
                            if content_match:
                                tweet_content = content_match.group(1).replace('\\n', '\n')
                            if not tweet_content:
                                # Try alternative pattern
                                meta_match = re.search(r'<meta name="description" content="([^"]+)"', html)
                                if meta_match:
                                    tweet_content = meta_match.group(1)
                    except Exception as scrape_e:
                        log_activity("MSG_TWITTER_LINK", f"Scraping error: {scrape_e}", "warning")
                
                # Fallback: Ask user for tweet content
                if not tweet_content:
                    if username and tweet_id:
                        tweet_content = f"""📝 *Info Tweet:*
• Username: @{username}
• Tweet ID: {tweet_id}
• Link: {text}

⚠️ Saya tidak dapat mengambil konten tweet langsung. 
Silakan copy-paste isi tweet nya di sini agar saya bisa analisa!"""
                    else:
                        tweet_content = f"Link: {text}\n\n⚠️ Silakan share isi tweet nya langsung untuk analisa."
                
                # Store in knowledge base
                store_knowledge(f"twitter:{text}", tweet_content)
                
                # If we don't have actual tweet content, ask user
                if "saya tidak dapat" in tweet_content.lower() or "silakan" in tweet_content.lower() or "cannot" in tweet_content.lower():
                    if BOT_LANGUAGE == "id":
                        await msg.reply_text(tweet_content, parse_mode="Markdown")
                    else:
                        await msg.reply_text(tweet_content)
                    log_activity("MSG_TWITTER_LINK", "No tweet content, asked user for input", "success")
                    return
                
                # Analyze with AI
                if BOT_LANGUAGE == "id":
                    agent_prompt = (
                        "Anda adalah crypto analyst yang menganalisa tweet/X. "
                        "BERIKAN ANALISA LENGKAP dengan:\n"
                        "1. 📌 RINGKASAN: Apa isi utama dari tweet ini?\n"
                        "2. 🎯 IMPLIKASI: Apa dampakpotensial ke market/coin tertentu?\n"
                        "3. ⚠️ RISK: Apa risiko atau warning yang perlu diperhatikan?\n"
                        "4. 💡 REKOMENDASI: Apakah ini bullish, bearish, atau neutral?\n\n"
                        f"Tweet content:\n{tweet_content}\n\n"
                        "Respond entirely in Indonesian dengan detail."
                    )
                else:
                    agent_prompt = (
                        "You are a crypto analyst analyzing a tweet/X post. "
                        "PROVIDE DETAILED ANALYSIS with:\n"
                        "1. 📌 SUMMARY: What is the main point?\n"
                        "2. 🎯 IMPLICATION: What's the potential market/coin impact?\n"
                        "3. ⚠️ RISK: What risks or warnings to note?\n"
                        "4. 💡 RECOMMENDATION: Is this bullish, bearish, or neutral?\n\n"
                        f"Tweet content:\n{tweet_content}"
                    )
                
                analysis = openrouter_chat(agent_prompt, system="You are a crypto analyst expert.")
                
                if BOT_LANGUAGE == "id":
                    await msg.reply_text(f"🐦 *Analisa Tweet/X*\n\n{analysis}", parse_mode="Markdown")
                else:
                    await msg.reply_text(f"🐦 *Tweet/X Analysis*\n\n{analysis}", parse_mode="Markdown")
                
                log_activity("MSG_TWITTER_LINK", "Successfully analyzed Twitter/X link", "success")
            except Exception as e:
                await msg.reply_text(f"Error processing Twitter/X: {e}")
                log_activity("MSG_TWITTER_LINK", f"Error: {e}", "error")
            return

        if text.startswith("http"):
            log_activity("MSG_LINK", f"Received link: {text[:50]}...")
            await msg.reply_text(f"Link received: {text}. In a full bot I would scrape/transcribe it.")
            return

        # Enhanced: Use full knowledge base for learning
        recent = get_recent_knowledge(10)  # Get more knowledge
        history = "\n".join([f"[{item['source']}] {item['text'][:300]}" for item in recent])
        
        # Also get user interaction history from logs
        user_history = ""
        try:
            conn = sqlite3.connect(KNOWLEDGE_DB)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT text FROM knowledge WHERE source LIKE 'user:%' ORDER BY created_at DESC LIMIT 5"
            )
            user_msgs = cursor.fetchall()
            if user_msgs:
                user_history = "\n📝 Pertanyaan sebelumnya dari user:\n" + "\n".join([m[0][:150] for m in user_msgs])
            conn.close()
        except:
            pass
        
        # Build enhanced context
        full_context = f"""
🧠 *KONTEKS KNOWLEDGE BASE*

📚 *Data yang sudah dipelajari:*
{history}

{user_history}

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
        log_activity("MSG_CHAT", "Generated response to user message", "success")
        
        # Store user question for learning
        store_knowledge(f"user:question", text)

def main():
    log_activity("BOT_START", "Starting Crypto Agent Bot")
    load_knowledge()
    if TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or OPENROUTER_API_KEY == "YOUR_OPENROUTER_API_KEY":
        logger.error("Please set TELEGRAM_TOKEN and OPENROUTER_API_KEY environment variables or edit the script.")
        log_activity("BOT_START", "Missing required API keys", "error")
        return
    
    # Use a custom request with longer timeouts to avoid network hiccups
    # Set bot commands using post_init callback
    async def setup_bot_commands(app):
        commands = [
            BotCommand("start", "🏠 Menu Utama / Help"),
            BotCommand("summary", "📰 News Harian"),
            BotCommand("sentiment", "📊 Analisis Sentiment"),
            BotCommand("screen", "💎 Screening Coin"),
            BotCommand("scan", "🔍 Scan Gems"),
            BotCommand("memecoin", "🐕 Trending Memecoin"),
            BotCommand("gmgn", "💎 GMGN Scanner"),
            BotCommand("solana", "🐋 Solana Activity"),
            BotCommand("wallet_analyze", "👛 Analisa Wallet"),
            BotCommand("wallet_scan", "🔄 Scan Semua Wallet"),
            BotCommand("wallet_list", "📝 List Wallet"),
            BotCommand("wallet_add", "➕ Tambah Wallet"),
            BotCommand("tweets", "🐦 Tweets/X"),
            BotCommand("learn", "📚 Learn PDF/Link"),
            BotCommand("memory", "🧠 Knowledge Base"),
            BotCommand("search", "🔎 Cari di KB"),
            BotCommand("backtest", "📈 Cek Performa"),
            BotCommand("health", "💚 Status Bot"),
            BotCommand("set_lang", "🌐 Ganti Bahasa"),
        ]
        await app.bot.set_my_commands(commands)
    
    request = HTTPXRequest(connect_timeout=10.0, read_timeout=20.0)
    app = (ApplicationBuilder()
           .token(TELEGRAM_TOKEN)
           .request(request)
           .post_init(setup_bot_commands)
           .build())
    
    # Add error handler to the application
    async def error_handler(update, context):
        log_activity("ERROR", f"{update} - {context.error}", "error")
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))  # /help aliases to /start
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("screen", screen))
    app.add_handler(CommandHandler("memecoin", memecoin))
    app.add_handler(CommandHandler("learn", learn))
    app.add_handler(CommandHandler("create_agent", create_agent))
    app.add_handler(CommandHandler("set_lang", set_lang))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("tweets", tweets))
    app.add_handler(CommandHandler("sentiment", sentiment))
    app.add_handler(CommandHandler("tweets_fallback", tweets_fallback))
    app.add_handler(CommandHandler("tweets_fallback_status", tweets_fallback_status))
    app.add_handler(CommandHandler("trust_list", trust_list))
    app.add_handler(CommandHandler("trust_add", trust_add))
    app.add_handler(CommandHandler("trust_remove", trust_remove))
    app.add_handler(CommandHandler("wallet_list", wallet_list))
    app.add_handler(CommandHandler("wallet_add", wallet_add))
    app.add_handler(CommandHandler("wallet_remove", wallet_remove))
    app.add_handler(CommandHandler("wallet_analyze", wallet_analyze))
    app.add_handler(CommandHandler("wallet_scan", wallet_scan))
    app.add_handler(CommandHandler("memory", memory))
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("setschedule", set_schedule))
    app.add_handler(CommandHandler("scan", scan_coins))
    app.add_handler(CommandHandler("setscan", set_scan))
    app.add_handler(CommandHandler("solana", scan_solana))
    app.add_handler(CommandHandler("setsolana", set_solana))
    app.add_handler(CommandHandler("gmgn", scan_gmgn_command))
    app.add_handler(CommandHandler("backtest", run_backtest_command))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.TEXT & (~filters.COMMAND), handle_message))

    # Ensure there is a running event loop for PTB v20 on some platforms
    import asyncio
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Start coin scanner in background thread if enabled
    if SCAN_ENABLED:
        scanner_thread = threading.Thread(target=run_coin_scanner, args=(app,), daemon=True)
        scanner_thread.start()
        log_activity("BOT_START", "Coin scanner thread started", "success")
    
    # Start Solana scanner in background thread if enabled
    if SOLANA_ENABLED:
        solana_thread = threading.Thread(target=run_solana_scanner, args=(app,), daemon=True)
        solana_thread.start()
        log_activity("BOT_START", "Solana scanner thread started", "success")
    
    # Start GMGN scanner in background thread if enabled
    if GMGN_ENABLED:
        gmgn_thread = threading.Thread(target=run_gmgn_scanner, args=(app,), daemon=True)
        gmgn_thread.start()
        log_activity("BOT_START", "GMGN scanner thread started", "success")
    
    # Start backtest scheduler in background thread if enabled
    if BACKTEST_ENABLED:
        backtest_thread = threading.Thread(target=run_backtest_scheduler, args=(app,), daemon=True)
        backtest_thread.start()
        log_activity("BOT_START", "Backtest scheduler thread started", "success")
    
    # Start daily news scheduler if enabled
    if SCHEDULE_ENABLED:
        schedule_thread = threading.Thread(target=run_scheduler, daemon=True)
        schedule_thread.start()
        log_activity("BOT_START", "Daily news scheduler thread started", "success")

    logger.info("Bot started...")
    log_activity("BOT_START", "Bot successfully started and polling for updates", "success")
    
    # Set bot commands menu using sync approach
    def set_bot_commands():
        try:
            bot = app.bot
            commands = [
                BotCommand("start", "🏠 Menu Utama / Help"),
                BotCommand("summary", "📰 News Harian"),
                BotCommand("sentiment", "📊 Analisis Sentiment"),
                BotCommand("screen", "💎 Screening Coin"),
                BotCommand("scan", "🔍 Scan Gems"),
                BotCommand("memecoin", "🐕 Trending Memecoin"),
                BotCommand("gmgn", "💎 GMGN Scanner"),
                BotCommand("solana", "🐋 Solana Activity"),
                BotCommand("wallet_analyze", "👛 Analisa Wallet"),
                BotCommand("wallet_scan", "🔄 Scan Semua Wallet"),
                BotCommand("wallet_list", "📝 List Wallet"),
                BotCommand("wallet_add", "➕ Tambah Wallet"),
                BotCommand("tweets", "🐦 Tweets/X"),
                BotCommand("learn", "📚 Learn PDF/Link"),
                BotCommand("memory", "🧠 Knowledge Base"),
                BotCommand("search", "🔎 Cari di KB"),
                BotCommand("backtest", "📈 Cek Performa"),
                BotCommand("health", "💚 Status Bot"),
                BotCommand("set_lang", "🌐 Ganti Bahasa"),
            ]
            # Use sync call
            from telegram.request import RequestParameter
            import json
            # Get bot info first to get chat_id for commands
            resp = bot._request.post(f"{bot.token}/getMe", {}, None)
            bot_id = resp['id']
            bot._request.post(f"{bot.token}/setMyCommands", 
                            {'commands': [(c.command, c.description) for c in commands]},
                            None)
        except Exception as e:
            logger.warning(f"Could not set commands menu: {e}")
    
    set_bot_commands()
    
    # Run with error handling for conflict
    try:
        app.run_polling()
    except Exception as e:
        logger.error(f"Bot error: {e}")
        log_activity("BOT_ERROR", str(e), "error")

if __name__ == "__main__":
    main()