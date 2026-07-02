
@echo off
REM Double-clickable launcher: opens a fresh window running Claude Code on
REM Z.ai GLM, using the shared org key from Secret Manager (glm-api-key).
REM See glm-bypass-mode.ps1 next to this file.
powershell -NoProfile -NoExit -ExecutionPolicy Bypass -File "%~dp0glm-bypass-mode.ps1" %*
