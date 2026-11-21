@echo off
chcp 65001 >nul
title Uy Savat bot
cd /d "%~dp0"
set UYBOT_LAUNCHER=1
:loop
python bot.py
echo Bot to'xtadi (kod %errorlevel%), 10 soniyadan keyin qayta ishga tushadi...
timeout /t 10 /nobreak >nul
goto loop
