#!/bin/bash
cd ~/screener/duckScreener
source venv/bin/activate
python3 crypto_bot.py > bot.log 2>&1 &
echo "Bot started! Check bot.log for output"
