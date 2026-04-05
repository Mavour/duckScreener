@echo off
cd /d C:\Users\ASUS\DuckScreener
call venv\Scripts\activate.bat
python -c "import duckscreeener; print('DuckScreener modules OK')"
venv\Scripts\python.exe -m duckscreeener.main
pause