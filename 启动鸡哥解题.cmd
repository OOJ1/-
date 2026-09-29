@echo off
rem ============================================================
rem  JiGeJieTi - launcher (no console window kept open)
rem  Uses pythonw.exe so nothing stays in the taskbar as a black window.
rem  Keep this file ASCII-only.
rem ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo [ERROR] .venv not found. Please run the dependency installer first.
  echo         See README.md for details.
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "main.py"
exit /b 0
