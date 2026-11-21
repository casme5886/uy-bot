@echo off
chcp 65001 >nul
title Server test
cd /d "%~dp0"
set SERVER=root@89.31.29.132
set KEY=%USERPROFILE%\.ssh\serverspace_key
if not exist "%USERPROFILE%\.ssh" mkdir "%USERPROFILE%\.ssh"
copy /Y "keys\serverspace_key" "%KEY%" >nul
icacls "%KEY%" /inheritance:r >nul
icacls "%KEY%" /grant:r "%USERNAME%:R" >nul
scp -i "%KEY%" -o StrictHostKeyChecking=accept-new test_srv.py %SERVER%:/root/ > test_srv_natija.txt 2>&1
ssh -i "%KEY%" %SERVER% "python3 /root/test_srv.py" >> test_srv_natija.txt 2>&1
type test_srv_natija.txt
echo.
echo TAYYOR
pause
