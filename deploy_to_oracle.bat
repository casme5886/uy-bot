@echo off
chcp 65001 >nul
title Uy bot - Oracle serverga ko'chirish
cd /d "%~dp0"

set SERVER=ubuntu@129.213.212.130
set KEY=%USERPROFILE%\.ssh\oracle_dv.key
set SRCKEY=%USERPROFILE%\Downloads\ssh-key-2026-08-28.key

echo ============================================================
echo  Uy bot Oracle serverga ko'chirilmoqda (3-5 daqiqa)
echo ============================================================
echo.

echo [1/4] SSH kalit tekshirilmoqda...
if not exist "%KEY%" (
  if not exist "%USERPROFILE%\.ssh" mkdir "%USERPROFILE%\.ssh"
  copy /Y "%SRCKEY%" "%KEY%" >nul || (echo Kalit topilmadi: %SRCKEY% & pause & exit /b 1)
  icacls "%KEY%" /inheritance:r >nul
  icacls "%KEY%" /grant:r "%USERNAME%:R" >nul
)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 %SERVER% "mkdir -p ~/uy-bot" || (echo Serverga ulanib bo'lmadi & pause & exit /b 1)

echo [2/4] Kompyuterdagi bot to'xtatilmoqda...
if exist bot.pid (
  for /f %%p in (bot.pid) do taskkill /PID %%p /F >nul 2>&1
)
timeout /t 3 /nobreak >nul

echo [3/4] Fayllar serverga yuklanmoqda...
scp -i "%KEY%" bot.py .env setup.sh seen.db %SERVER%:~/uy-bot/ || (echo Yuklashda xato & pause & exit /b 1)

echo [4/4] Serverda o'rnatilmoqda...
ssh -i "%KEY%" %SERVER% "sed -i 's/\r$//' ~/uy-bot/setup.sh ~/uy-bot/.env && chmod 600 ~/uy-bot/.env && bash ~/uy-bot/setup.sh" || (echo O'rnatishda xato & pause & exit /b 1)

ren start.bat start_ISHLATMANG.bat >nul 2>&1
echo.
echo ============================================================
echo  Tugadi! Bot endi Oracle serverda 24/7 ishlaydi.
echo  Kompyuterdagi botni boshqa ISHGA TUSHIRMANG
echo  (start.bat nomi start_ISHLATMANG.bat ga o'zgartirildi).
echo ============================================================
pause
