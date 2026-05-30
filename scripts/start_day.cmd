@echo off
REM Double-clickable launcher: runs start_day.ps1 (sitting next to this file)
REM without execution-policy hassle.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_day.ps1"
pause
 
