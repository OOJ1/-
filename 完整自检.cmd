@echo off
rem ============================================================
rem  JiGeJieTi - FULL self test (all four suites, ~2-4 minutes)
rem
rem  Suites 1-3 are offline (no network, no model).
rem  Suite 4 needs a running local Ollama with a vision model; if it
rem  is unavailable that suite is reported as skipped, not failed.
rem
rem  NOTE: keep this file ASCII-only to avoid codepage issues.
rem ============================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Run install-deps.cmd first.
  pause
  exit /b 1
)

echo ===== 1/4 core logic (offline) =====
".venv\Scripts\python.exe" -u tools\smoke_test.py
set RC1=%errorlevel%

echo.
echo ===== 2/4 UI end-to-end (offline, built-in fake SSE server) =====
".venv\Scripts\python.exe" -u tools\ui_smoke.py
set RC2=%errorlevel%

echo.
echo ===== 3/4 live: real global hotkey + real app launch =====
".venv\Scripts\python.exe" -u tools\verify_live.py
set RC3=%errorlevel%

echo.
echo ===== 4/4 real model end-to-end =====
echo       needs a running local Ollama plus a vision model.
echo       a small white probe window may flash on screen - that is expected.
".venv\Scripts\python.exe" -u tools\verify_real_model.py
set RC4=%errorlevel%

rem Deliberately no "if (...)" block here. Batch blocks are easy to break:
rem a round bracket inside an echo string closes the block early, and the lines
rem after it then run UNCONDITIONALLY and silently. The exit code is reported
rem as-is in the summary below instead, which needs no branching at all.
echo.
echo ===== summary =====
echo   smoke_test        = %RC1%      0 means pass
echo   ui_smoke          = %RC2%      0 means pass
echo   verify_live       = %RC3%      0 means pass - 2 items may show SKIP on sandboxed machines
echo   verify_real_model = %RC4%      0 means pass - 2 means Ollama was not running, so it did not run
echo.
echo Rendered UI previews are in _verify\ (gitignored, safe to delete).
pause
