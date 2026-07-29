@echo off
cd /d "%~dp0"
echo Rescanning project profiles - takes a few minutes...
py -m src.profiles index "<drive>:\path\to\Project Profiles"
echo.
echo Rescanning resumes...
py -m src.resumes index "<drive>:\path\to\Master Resumes"
echo.
echo Done. The search page now includes any new or changed files.
pause
