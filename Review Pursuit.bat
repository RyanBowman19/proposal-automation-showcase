@echo off
rem Checks an LOI for mistakes, then compares it against all 3 ranked
rem competitors for a pursuit - runs tools 2 and 5 together.
rem Double-click and answer the prompt, or drag a draft LOI PDF onto this
rem file first if it hasn't been filed under reference/ yet.
cd /d "%~dp0"
set DRAFT=%~1
set /p PURSUIT=Which pursuit to benchmark against? (e.g. 2605 Item 5):
if "%DRAFT%"=="" (
    py -m src.review "%PURSUIT%"
) else (
    py -m src.review "%PURSUIT%" --vs "%DRAFT%"
)
pause
