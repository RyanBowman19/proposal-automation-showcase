@echo off
rem Drag a finished LOI PDF onto this file to check it for mistakes.
cd /d "%~dp0"
if "%~1"=="" (
    echo Drag a PDF onto this file to check it.
) else (
    py -m src.check %1
)
pause
