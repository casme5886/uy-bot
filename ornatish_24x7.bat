@echo off
chcp 65001 >nul
title Uy bot - 24/7 o'rnatish
cd /d "%~dp0"
echo ============================================================
echo  Uy botni shu kompyuterda 24/7 ishlashga sozlash
echo ============================================================
echo.
echo [1/4] Python tekshirilmoqda...
python --version >nul 2>&1
if errorlevel 1 (
  echo Python topilmadi, o'rnatilmoqda...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  echo.
  echo Python o'rnatildi. Shu oynani YOPING va ornatish_24x7.bat ni QAYTA ishga tushiring.
  pause
  exit /b
)
echo [2/4] Kutubxonalar o'rnatilmoqda...
python -m pip install -q requests python-dotenv
echo [3/4] Kompyuter uyquga ketmasligi sozlanmoqda...
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 10
echo [4/4] Kompyuter yoqilganda bot o'zi ishga tushishi sozlanmoqda...
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
(
  echo @echo off
  echo cd /d "%~dp0"
  echo start "Uy Savat bot" /min "%~dp0start.bat"
) > "%STARTUP%\uy_bot.bat"
echo.
echo Bot hozir ishga tushirilmoqda...
start "Uy Savat bot" /min "%~dp0start.bat"
echo.
echo ============================================================
echo  TAYYOR! Bot ishlayapti va kompyuter qayta yoqilganda o'zi ishga tushadi.
echo  Kompyuterni o'chirmang, faqat monitorni o'chirsangiz bo'ladi.
echo ============================================================
pause
