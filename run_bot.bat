@echo off
cd /d C:\Users\ASUS\DuckScreener
call venv\Scripts\activate.bat
python -c "import schedule; print('Schedule module OK')"
venv\Scripts\python.exe crypto_bot.py
pause