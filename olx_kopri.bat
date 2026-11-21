@echo off
chcp 65001 >nul
title OLX ko'prigi
cd /d "%~dp0"
set SERVER=ubuntu@129.213.212.130
set KEY=%USERPROFILE%\.ssh\olx_relay_key

if not exist "%USERPROFILE%\.ssh" mkdir "%USERPROFILE%\.ssh"
if not exist "%KEY%" (
  copy /Y "olx_relay_key" "%KEY%" >nul || (echo olx_relay_key fayli topilmadi & pause & exit /b 1)
  icacls "%KEY%" /inheritance:r >nul
  icacls "%KEY%" /grant:r "%USERNAME%:R" >nul
)

if exist kopri_ok.txt goto loop

echo ============================================================
echo  Birinchi ishga tushirish: bot serverga ko'chirilmoqda
echo ============================================================
echo [1/4] Shu kompyuterdagi bot to'xtatilmoqda...
taskkill /FI "WINDOWTITLE eq Uy Savat bot*" /T /F >nul 2>&1
if exist bot.pid for /f %%p in (bot.pid) do taskkill /PID %%p /F >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\uy_bot.bat" >nul 2>&1
timeout /t 3 /nobreak >nul

echo [2/4] Baza serverga yuklanmoqda...
scp -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 seen.db %SERVER%:~/uy-bot/seen.db || (echo Serverga ulanib bo'lmadi & pause & exit /b 1)

echo [3/4] Bot serverda ishga tushirilmoqda...
ssh -i "%KEY%" %SERVER% "sudo systemctl restart uybot" || (echo Botni yoqib bo'lmadi & pause & exit /b 1)

echo [4/4] Ko'prik kompyuter yoqilganda o'zi ishga tushadigan qilinmoqda...
(
  echo @echo off
  echo start "OLX ko'prigi" /min "%~f0"
) > "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\olx_kopri.bat"
echo ok> kopri_ok.txt
echo.
echo TAYYOR! Bot endi serverda. Bu oyna OLX ko'prigi - uni YOPMANG (kichraytirib qo'ying).
echo.

:loop
echo %date% %time% Ko'prik ulanmoqda...
ssh -i "%KEY%" -N -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o ConnectTimeout=20 -R 1080 %SERVER%
echo %date% %time% Ko'prik uzildi, 15 soniyadan keyin qayta ulanadi...
timeout /t 15 /nobreak >nul
goto loop
