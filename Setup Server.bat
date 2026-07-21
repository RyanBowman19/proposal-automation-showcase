@echo off
rem Run this ONCE on the laptop that hosts the search.
rem Right-click -> Run as administrator.
cd /d "%~dp0"

echo Installing packages...
py -m pip install -r requirements.txt

echo Opening port 8765 in the firewall...
netsh advfirewall firewall add rule name="VS Search" dir=in action=allow protocol=TCP localport=8765

echo Telling the PC to never sleep...
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

echo Making the search start whenever the PC boots...
schtasks /create /f /tn "VS Search" /sc onstart /ru SYSTEM /tr "\"%~dp0Search Projects.bat\""

echo Starting it now...
schtasks /run /tn "VS Search"

echo.
echo Done. The search page is at http://%COMPUTERNAME%:8765
echo It keeps running after you sign out or reboot.
pause
