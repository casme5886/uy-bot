@echo off
chcp 65001 >nul
title Uy bot - serverdan qaytarish
cd /d "%~dp0"
set SERVER=ubuntu@129.213.212.130
set KEY=%USERPROFILE%\.ssh\oracle_dv.key
echo [1/2] Oracle serverdagi uy bot to'xtatilmoqda (DV botga tegilmaydi)...
ssh -i "%KEY%" -o ConnectTimeout=15 %SERVER% "sudo systemctl disable --now uybot" || (echo Serverga ulanib bo'lmadi & pause & exit /b 1)
echo [2/2] Serverdagi baza (foydalanuvchilar, sozlamalar) qaytarib olinmoqda...
scp -i "%KEY%" %SERVER%:~/uy-bot/seen.db seen.db || echo Baza olinmadi - eski baza bilan davom etiladi
if exist start_ISHLATMANG.bat ren start_ISHLATMANG.bat start.bat
echo.
echo Tayyor. Endi start.bat bilan botni kompyuterda ishga tushirish mumkin.
pause
