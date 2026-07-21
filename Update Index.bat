@echo off
cd /d "%~dp0"
echo Rescanning project profiles - takes a few minutes...
py -m src.profiles index "Z:\Shared\Documents\Departments\Marketing\Project Profiles"
echo.
echo Rescanning resumes...
py -m src.resumes index "P:\Marketing\RESUMES\Master Resumes_Multidisciplines"
echo.
echo Done. The search page now includes any new or changed files.
pause
