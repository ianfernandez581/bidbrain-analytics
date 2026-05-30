@echo off
REM Double-clickable launcher: runs run-export-job.ps1 (sitting next to this file)
REM without execution-policy hassle. Double-clicking uses the safe interactive
REM mode (prompts before writing to prod). For -DryRun / -Force, call the .ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-export-job.ps1"
pause
