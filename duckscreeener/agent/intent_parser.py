"""
Intent Parser — maps natural language to bot actions.
Instead of requiring /commands, the bot understands what the user wants.
"""
import re
import logging

logger = logging.getLogger(__name__)

INTENT_PATTERNS = {
    "scan_coins": [
        r"(cari|scan|screen|detect|find|cek|lihat).*(coin|token|gem|scalp|accumulasi|whale)",
        r"(coin|token|gem).*(bagus|potensial|murah|undiervalue|akumulasi)",
        r"(ada|ada.*ga|ada.*nggak|ada.*tidak).*(coin|token|gem).*(bagus|potensi|naik|pump)",
        r"whale.*(accumulasi|beli|buy|masuk)",
        r"(coin|token).*(whale|akumulasi|volume)",
        r"scalping|scalp",
    ],
    "scan_memecoins": [
        r"(memecoin|meme|coin.*baru|hype|pump|early).*(cari|scan|ada|bagus|potensi)",
        r"(ada|cari|scan).*(memecoin|meme|coin.*baru)",
        r"coin.*baru.*naik|coin.*baru.*potensi|coin.*baru.*hype",
        r"narasi.*trending|trending.*narasi|narasi.*apa",
    ],
    "backtest": [
        r"(backtest|performa|hasil|win.*rate|akurasi|laporan|report)",
        r"(gimana|bagaimana|how).*(performa|hasil|signal|sinyal)",
        r"(signal|sinyal).*(kemarin|sebelumnya|lalu|performance)",
    ],
    "summary": [
        r"(berita|news|update|briefing|ringkasan|summary).*(crypto|kripto|hari|24)",
        r"(apa|what).*(news|berita|terjadi|terjadi.*hari)",
        r"(crypto|kripto).*(news|berita|update|briefing)",
    ],
    "wallet_analyze": [
        r"(analisa|analyze|cek|lihat|scan).*(wallet|dompet|address|alamat)",
        r"(wallet|dompet|address|alamat).*(analisa|analyze|cek|lihat)",
    ],
    "sentiment": [
        r"(sentiment|sentimen|analisis|analisa).*(coin|token|market|pasar)",
        r"(coin|token|market|pasar).*(sentiment|sentimen|bullish|bearish)",
        r"(bagaimana|gimana|how).*(sentiment|sentimen|outlook)",
    ],
    "search_knowledge": [
        r"(cari|search|ingat|ingat.*apa|ada.*info).*(tentang|ttg|about)",
    ],
    "show_memory": [
        r"(apa|what).*(kamu|lo|lu|you|agent|bot).*(ingat|tahu|know|pelajari|learn|hafal)",
        r"(pelajaran|lesson|belajar|knowledge|memory|ingatan|yang.*dipelajari|yang.*kamu.*tahu)",
        r"(apa.*saja|what.*all|everything|semua).*(yang.*kamu|that.*you|yang.*udah|yang.*sudah).*(pelajari|learn|tahu|know)",
        r"apa.*yang.*kamu.*pelajari|what.*did.*you.*learn|apa.*yang.*kamu.*tahu",
        r"apa.*yang.*udah.*kamu.*pelajari|apa.*yang.*sudah.*kamu.*pelajari",
        r"apa.*yang.*kamu.*sudah.*pelajari|apa.*yang.*kamu.*udah.*pelajari",
        r"(show|tampilkan|lihat).*(memory|ingatan|pengetahuan|knowledge)",
    ],
    "help": [
        r"(bisa.*apa|bisa.*ngapain|fitur|help|bantuan|command|menu)",
        r"(how|cara|gimana).*(pakai|pake|use|kerja|work)",
    ],
}

INTENT_DESCRIPTIONS = {
    "scan_coins": "Scan CEX for whale accumulation signals",
    "scan_memecoins": "Scan for new memecoins with hype potential",
    "backtest": "Check signal performance and backtest results",
    "summary": "Get 24h crypto news summary",
    "wallet_analyze": "Analyze a Solana wallet",
    "sentiment": "Analyze market sentiment for a coin",
    "search_knowledge": "Search the knowledge base",
    "help": "Show available commands",
}


def parse_intent(message):
    """
    Parse user message to determine intent.
    Returns (intent, extracted_params) or (None, None) if no match.
    """
    text = message.lower().strip()

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                params = _extract_params(text, intent)
                logger.info(f"Intent detected: {intent} (params: {params})")
                return intent, params

    return None, None


def _extract_params(text, intent):
    """Extract relevant parameters from the message based on intent"""
    params = {}

    if intent == "wallet_analyze":
        addr_match = re.search(r'[1-9A-HJ-NP-Za-km-z]{32,44}', text)
        if addr_match:
            params['address'] = addr_match.group(0)

    if intent == "sentiment":
        coin_match = re.search(r'(?:coin|token|sentiment|sentimen|analisa|analyze)\s+([A-Za-z0-9]+)', text)
        if coin_match:
            params['coin'] = coin_match.group(1).upper()

    if intent == "search_knowledge":
        query_match = re.search(r'(?:tentang|ttg|about)\s+(.+)', text, re.IGNORECASE)
        if query_match:
            params['query'] = query_match.group(1).strip()
        else:
            params['query'] = text

    return params


def get_natural_response(intent, success=True, data=None):
    """Generate natural language response for an intent"""
    responses = {
        "scan_coins": {
            "success": "Saya menemukan beberapa coin yang sedang diakumulasi whale. Ini detailnya:",
            "empty": "Saat ini tidak ada sinyal akumulasi whale yang terdeteksi. Whale mungkin sedang diam. Coba lagi nanti.",
        },
        "scan_memecoins": {
            "success": "Ada beberapa memecoin baru yang berpotensi hype. Cek detailnya:",
            "empty": "Tidak ada memecoin baru yang menarik dalam 12 jam terakhir. Market lagi sepi.",
        },
        "backtest": {
            "success": "Ini laporan performa sinyal kita:",
            "empty": "Belum ada sinyal yang bisa dievaluasi. Jalankan /scan atau /memecoin dulu.",
        },
        "summary": {
            "success": "Ini ringkasan berita crypto 24 jam terakhir:",
            "empty": "Tidak ada berita crypto terbaru.",
        },
        "wallet_analyze": {
            "success": "Ini hasil analisa wallet:",
            "empty": "Gagal menganalisa wallet. Pastikan address benar.",
        },
        "sentiment": {
            "success": "Ini analisis sentiment:",
            "empty": "Tidak cukup data untuk analisis sentiment.",
        },
        "search_knowledge": {
            "success": "Ini yang saya temukan:",
            "empty": "Tidak ada hasil pencarian.",
        },
        "help": {
            "success": "Ini yang bisa saya lakukan:",
            "empty": "",
        },
    }

    if intent in responses:
        if success:
            return responses[intent].get("success", "")
        else:
            return responses[intent].get("empty", "")
    return ""
