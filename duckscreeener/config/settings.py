import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "stepfun/step-3.5-flash:free")
BOT_LANGUAGE = os.getenv("BOT_LANGUAGE", "en")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
TRUSTED_TWITTER_ACCOUNTS = [x.strip().replace('@', '') for x in os.getenv("TRUSTED_TWITTER_ACCOUNTS", "").split(",") if x.strip()]
AUTO_DETECT_LANG = os.getenv("AUTO_DETECT_LANG", "false").lower() == "true"

COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
COINGECKO_NEWS_URL = "https://api.coingecko.com/api/v3/news"

SCAN_ENABLED = os.getenv("SCAN_ENABLED", "false").lower() == "true"
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))
SCAN_CHAT_ID = os.getenv("SCAN_CHAT_ID", "")
SCAN_MIN_VOLUME_USD = float(os.getenv("SCAN_MIN_VOLUME_USD", "100000"))
SCAN_MIN_PRICE_CHANGE = float(os.getenv("SCAN_MIN_PRICE_CHANGE", "5"))

SOLANA_ENABLED = os.getenv("SOLANA_ENABLED", "false").lower() == "true"
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
SOLANA_CHAT_ID = os.getenv("SOLANA_CHAT_ID", "")
SOLANA_MIN_TRADE_VALUE = float(os.getenv("SOLANA_MIN_TRADE_VALUE", "10"))
SOLANA_SCAN_INTERVAL = int(os.getenv("SOLANA_SCAN_INTERVAL", "60"))
SOLANA_RPC_HEADERS = {"Content-Type": "application/json"}

GMGN_ENABLED = os.getenv("GMGN_ENABLED", "false").lower() == "true"
GMGN_API_URL = "https://gmgn.ai/defi/quotation/v1/rank"

BACKTEST_ENABLED = os.getenv("BACKTEST_ENABLED", "true").lower() == "true"
BACKTEST_HOUR = int(os.getenv("BACKTEST_HOUR", "22"))
BACKTEST_MINUTE = int(os.getenv("BACKTEST_MINUTE", "0"))
BACKTEST_CHAT_ID = os.getenv("BACKTEST_CHAT_ID", "")
BACKTEST_SUCCESS_THRESHOLD = float(os.getenv("BACKTEST_SUCCESS_THRESHOLD", "10"))
BACKTEST_FAILURE_THRESHOLD = float(os.getenv("BACKTEST_FAILURE_THRESHOLD", "-20"))

SCHEDULE_ENABLED = os.getenv("SCHEDULE_ENABLED", "true").lower() == "true"
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "8"))
SCHEDULE_MINUTE = int(os.getenv("SCHEDULE_MINUTE", "0"))
SCHEDULE_TIMEZONE = os.getenv("SCHEDULE_TIMEZONE", "Asia/Makassar")
SCHEDULE_CHAT_ID = os.getenv("SCHEDULE_CHAT_ID", "")

KNOWLEDGE_DB = os.getenv("KNOWLEDGE_DB", "knowledge_base.db")
LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_FILE = os.path.join(LOG_DIR, "agent_activity.log")

TWITTER_FALLBACK_MODE = os.getenv("TWITTER_FALLBACK_MODE", "auto").lower()

SOLANA_SMART_WALLETS = [
    "7xKXtg2CW87d97TXJSDpbD5jBkHuTWrPqCg44dFYrCE8",
    "BLToaDD4iYS3F5W6Kdx4p5UTyiZWxyPnDKhMTqGgy3x",
]

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY", "")
SOLANAFM_API_KEY = os.getenv("SOLANAFM_API_KEY", "")
