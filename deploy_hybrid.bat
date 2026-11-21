@echo off
chcp 65001 >nul
title Uy bot - Oracle serverga (gibrid)
cd /d "%~dp0"
set SERVER=ubuntu@129.213.212.130
set KEY=%USERPROFILE%\.ssh\oracle_dv.key
echo [1/3] Fayllar serverga yuklanmoqda...
ssh -i "%KEY%" -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new %SERVER% "mkdir -p ~/uy-bot" || (echo Serverga ulanib bo'lmadi & pause & exit /b 1)
scp -i "%KEY%" bot.py .env setup.sh relay_key.pub %SERVER%:~/uy-bot/ || (echo Yuklashda xato & pause & exit /b 1)
echo [2/3] Serverda o'rnatilmoqda...
ssh -i "%KEY%" %SERVER% "sed -i 's/\r$//' ~/uy-bot/setup.sh && bash ~/uy-bot/setup.sh nostart" || (echo O'rnatishda xato & pause & exit /b 1)
echo [3/3] Tayyor.
echo.
echo Endi ESKI kompyuterda olx_kopri.bat ni ishga tushiring - u botni serverda yoqadi.
pause
