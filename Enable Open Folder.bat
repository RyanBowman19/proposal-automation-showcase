@echo off
REM Run this ONCE on any computer that uses the VS Search page but isn't the
REM one hosting it. It teaches Windows what a vsfolder: link is, so the
REM "Open folder" button on the search page opens Explorer on THIS computer.
REM
REM No administrator rights needed - it only writes to your own account.
REM The host PC doesn't need this; the server opens Explorer there itself.

setlocal
set "TARGET=%LOCALAPPDATA%\VS Search"

if not exist "%~dp0open-folder.vbs" (
  echo Couldn't find open-folder.vbs next to this file.
  echo Copy the whole proposal-automation folder, not just the .bat.
  pause
  exit /b 1
)

REM Keep our own copy so this keeps working when the network drive is away.
if not exist "%TARGET%" mkdir "%TARGET%"
copy /y "%~dp0open-folder.vbs" "%TARGET%\open-folder.vbs" >nul
if errorlevel 1 (
  echo Couldn't copy the helper to "%TARGET%".
  pause
  exit /b 1
)

reg add "HKCU\Software\Classes\vsfolder" /ve /d "URL:VS Search folder" /f >nul
reg add "HKCU\Software\Classes\vsfolder" /v "URL Protocol" /t REG_SZ /d "" /f >nul
reg add "HKCU\Software\Classes\vsfolder\shell\open\command" /ve /d "wscript.exe \"%TARGET%\open-folder.vbs\" \"%%1\"" /f >nul
if errorlevel 1 (
  echo Couldn't write the setting. Nothing was changed.
  pause
  exit /b 1
)

echo.
echo Done. "Open folder" on the search page now works on this computer.
echo.
echo The first time you click it, the browser asks for permission - tick
echo "Always allow" so it stops asking every time.
echo.
pause
