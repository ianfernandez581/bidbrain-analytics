
@echo off
REM Double-clickable launcher: runs setup.ps1 (sitting next to this file)
REM without execution-policy hassle.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
pause
 