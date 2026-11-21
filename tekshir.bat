@echo off
chcp 65001 >nul
title Server tekshiruvi
cd /d "%~dp0"
set SERVER=ubuntu@129.213.212.130
set KEY=%USERPROFILE%\.ssh\oracle_dv.key
ssh -i "%KEY%" -o ConnectTimeout=15 %SERVER% "echo == OLX kopri orqali: ; curl -s -o /dev/null -w '%%{http_code}\n' --max-time 20 -x socks5h://127.0.0.1:1080 -A Mozilla/5.0 'https://www.olx.uz/api/v1/offers/?limit=1'; echo == Bot holati: ; systemctl is-active uybot; echo == Log: ; tail -n 25 ~/uy-bot/bot.log" > tekshir_natija.txt 2>&1
type tekshir_natija.txt
pause
