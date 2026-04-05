# DuckScreener - Crypto Agent Bot

Telegram AI agent untuk screening crypto, deteksi whale accumulation, dan analisis memecoin.

## Features

| Feature | Description |
|---|---|
| Whale Accumulation Detection | Deteksi coin CEX yang lagi diakumulasi whale sebelum pump |
| Memecoin Scanner | Scan memecoin baru di Solana sebelum hype |
| AI Analysis | Analisis narasi dan potensi setiap coin |
| Backtest | Laporan performa sinyal harian dengan win rate |
| Daily News | Ringkasan berita crypto 24 jam terakhir |
| Knowledge Base | Belajar dari PDF, gambar, YouTube, Twitter |
| Conversational AI | Ngobrol natural, bot paham konteks |
| Wallet Tracker | Track smart wallet Solana untuk referensi memecoin |

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/Mavour/duckScreener.git
cd duckScreener
```

### 2. Setup Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# atau
venv\Scripts\activate     # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Setup Environment Variables

Copy template dan isi dengan API key kamu:

```bash
cp .env.example .env
```

Lalu edit `.env`:

```bash
nano .env  # atau pakai editor favorit kamu
```

### 5. Run Bot

```bash
python -m duckscreeener.main
```

---

## Cara Mendapatkan API Keys

### Telegram Bot Token
1. Buka Telegram, chat ke [@BotFather](https://t.me/BotFather)
2. Ketik `/newbot`
3. Ikuti instruksi sampai dapat token
4. Copy token ke `TELEGRAM_TOKEN` di `.env`

### OpenRouter API Key
1. Daftar di [openrouter.ai](https://openrouter.ai/)
2. Masuk ke [Keys](https://openrouter.ai/keys)
3. Klik "Create Key"
4. Copy key ke `OPENROUTER_API_KEY` di `.env`

### Twitter Bearer Token (opsional)
1. Daftar developer di [developer.twitter.com](https://developer.twitter.com/)
2. Buat project/app
3. Copy Bearer Token ke `TWITTER_BEARER_TOKEN` di `.env`

---

## Penjelasan Parameter `.env`

### Core Settings

| Parameter | Deskripsi | Contoh |
|---|---|---|
| `TELEGRAM_TOKEN` | Token bot Telegram dari BotFather | `123456:ABC-DEF...` |
| `OPENROUTER_API_KEY` | API key untuk LLM (analisis AI) | `sk-or-v1-...` |
| `OPENROUTER_MODEL` | Model AI yang dipakai | `qwen/qwen3.6-plus:free` |
| `BOT_LANGUAGE` | Bahasa default bot (`id` atau `en`) | `id` |
| `AUTO_DETECT_LANG` | Auto-detect bahasa user | `true` |

### Knowledge Base

| Parameter | Deskripsi | Contoh |
|---|---|---|
| `KNOWLEDGE_DB` | Nama file database SQLite | `knowledge_base.db` |

### Twitter/X (opsional)

| Parameter | Deskripsi | Contoh |
|---|---|---|
| `TWITTER_BEARER_TOKEN` | Bearer token Twitter API | `AAAAAAAAAAAA...` |
| `TRUSTED_TWITTER_ACCOUNTS` | Akun Twitter terpercaya (comma-separated) | `cryptowhale,sophon` |

### On-Chain API (opsional)

| Parameter | Deskripsi | Link |
|---|---|---|
| `ETHERSCAN_API_KEY` | API key Etherscan (ETH) | [etherscan.io/apis](https://etherscan.io/apis) |
| `BSCSCAN_API_KEY` | API key BscScan (BSC) | [bscscan.com/apis](https://bscscan.com/apis) |
| `SOLANAFM_API_KEY` | API key SolanaFM | [solana.fm](https://solana.fm/) |

### Logging

| Parameter | Deskripsi | Contoh |
|---|---|---|
| `LOG_DIR` | Folder untuk log | `logs` |
| `LOG_FILE` | Nama file log | `agent_activity.log` |

### Daily News Scheduler

| Parameter | Deskripsi | Contoh |
|---|---|---|
| `SCHEDULE_ENABLED` | Aktifkan daily news | `true` |
| `SCHEDULE_HOUR` | Jam kirim news (24h format) | `8` |
| `SCHEDULE_MINUTE` | Menit kirim news | `30` |
| `SCHEDULE_TIMEZONE` | Timezone | `Asia/Makassar` |
| `SCHEDULE_CHAT_ID` | Chat ID untuk kirim news | `YOUR_CHAT_ID` |

### Coin Scanner

| Parameter | Deskripsi | Contoh |
|---|---|---|
| `SCAN_ENABLED` | Aktifkan auto scan | `true` |
| `SCAN_INTERVAL_MINUTES` | Interval scan (menit) | `360` |
| `SCAN_MIN_VOLUME_USD` | Minimum volume ($) | `100000` |
| `SCAN_MIN_PRICE_CHANGE` | Minimum price change (%) | `10` |
| `SCAN_CHAT_ID` | Chat ID untuk kirim alert | `YOUR_CHAT_ID` |

### GMGN / Memecoin Scanner

| Parameter | Deskripsi | Contoh |
|---|---|---|
| `GMGN_ENABLED` | Aktifkan GMGN scanner | `true` |

### Backtest

| Parameter | Deskripsi | Contoh |
|---|---|---|
| `BACKTEST_ENABLED` | Aktifkan backtest | `true` |
| `BACKTEST_HOUR` | Jam run backtest (24h) | `22` |
| `BACKTEST_MINUTE` | Menit run backtest | `0` |
| `BACKTEST_CHAT_ID` | Chat ID untuk kirim report | `YOUR_CHAT_ID` |
| `BACKTEST_SUCCESS_THRESHOLD` | Threshold sukses (%) | `10` |
| `BACKTEST_FAILURE_THRESHOLD` | Threshold gagal (%) | `-20` |

---

## Cara Menjalankan di VPS

### Opsi 1: Systemd (Recommended)

```bash
# Copy service file
sudo cp duckscreeener.service /etc/systemd/system/
# Edit path sesuai lokasi project
sudo nano /etc/systemd/system/duckscreeener.service
# Enable dan start
sudo systemctl daemon-reload
sudo systemctl enable duckscreeener
sudo systemctl start duckscreeener
# Cek status
sudo systemctl status duckscreeener
# Lihat log
journalctl -u duckscreeener -f
```

### Opsi 2: Nohup

```bash
nohup python -m duckscreeener.main > bot.log 2>&1 &
# Cek log
tail -f bot.log
# Stop bot
pkill -f duckscreeener.main
```

### Opsi 3: Screen

```bash
screen -S bot
python -m duckscreeener.main
# Detach: Ctrl+A lalu D
# Reattach: screen -r bot
```

---

## Commands

| Command | Deskripsi |
|---|---|
| `/start` | Menu utama |
| `/summary` | Ringkasan berita crypto 24 jam |
| `/scan` | Scan whale accumulation di CEX (auto 6 jam + manual) |
| `/memecoin` | Scan memecoin baru sebelum pump |
| `/memecoin_ai` | Scan + AI analysis |
| `/wallet_analyze <addr>` | Analisa wallet Solana |
| `/wallet_scan` | Scan semua tracked wallet |
| `/wallet_list` | List tracked wallets |
| `/wallet_add <addr>` | Tambah wallet |
| `/wallet_remove <addr>` | Hapus wallet |
| `/memory` | AI rangkum semua yang sudah dipelajari |
| `/backtest` | Cek performa sinyal hari ini |
| `/health` | Status bot |
| `/set_lang <en|id>` | Ganti bahasa |

### Natural Language (tanpa command)

Bot paham ngobrol biasa, contoh:
- "cari coin yang bagus buat scalping" → jalankan `/scan`
- "ada memecoin baru yang menarik?" → jalankan `/memecoin`
- "apa yang kamu sudah pelajari?" → jalankan `/memory`
- "gimana performa sinyal hari ini?" → jalankan `/backtest`

---

## Project Structure

```
duckscreeener/
├── config/settings.py      # Environment & settings
├── db/
│   ├── database.py         # SQLite layer + FTS5 + signals
│   └── vector_search.py    # Semantic search
├── services/
│   └── external_apis.py    # API clients
├── scanners/
│   ├── coin_scanner.py     # CEX whale detection
│   ├── memecoin_scanner.py # Memecoin scanner
│   └── backtest.py         # Backtest engine
├── handlers/
│   └── commands.py         # Telegram handlers
├── scheduler/
│   └── tasks.py            # Scheduled tasks
├── agent/
│   ├── intent_parser.py    # Natural language → action
│   ├── reflection.py       # Self-analysis
│   └── proactive.py        # Proactive insights
├── utils/
│   └── message_split.py    # Long message handler
└── main.py                 # Entry point
```
