@echo off
rem ============================================================
rem  JiGeJieTi - self test (core logic + UI end-to-end)
rem  No network or real model needed: a fake SSE server is used.
rem  Keep this file ASCII-only.
rem ============================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo ===== 1/2 core logic =====
".venv\Scripts\python.exe" tools\smoke_test.py

echo.
echo ===== 2/2 UI end-to-end =====
".venv\Scripts\python.exe" tools\ui_smoke.py

echo.
echo Rendered screenshots are saved in _verify\ for manual review.
echo.
echo Other .cmd files in this folder - the 4-suite full self-test is among them:
for %%F in ("%~dp0*.cmd") do if /i not "%%~nxF"=="%~nx0" echo     %%~nxF
pause
