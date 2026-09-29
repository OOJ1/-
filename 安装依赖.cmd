@echo off
rem ============================================================
rem  JiGeJieTi - install dependencies
rem  Creates .venv (Python 3.10+) and installs requirements.
rem  NOTE: keep this file ASCII-only to avoid codepage issues.
rem ============================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH.
  echo         Install Python 3.10 or newer, check "Add python.exe to PATH", then retry.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating virtual environment .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create venv.
    pause
    exit /b 1
  )
) else (
  echo [1/4] Existing .venv found, reuse it.
)

rem ------------------------------------------------------------------
rem [2/4] Make sure pip is usable.
rem Do NOT blindly run "--upgrade pip": that uninstalls the old pip first,
rem and if it fails midway it leaves the venv with NO pip at all
rem (seen in practice - recovery then needs ensurepip).
rem We only need a *working* pip, not the newest one.
rem ------------------------------------------------------------------
echo [2/4] Checking pip ...
".venv\Scripts\python.exe" -m pip --version >nul 2>nul
if errorlevel 1 (
  echo       pip is missing, bootstrapping it with ensurepip ...
  ".venv\Scripts\python.exe" -m ensurepip --default-pip
  if errorlevel 1 (
    echo [ERROR] Could not bootstrap pip. Recreate the venv: rmdir /s /q .venv
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip --version

echo [3/4] Installing requirements ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.org/simple
rem NOTE: never put round brackets inside an "if (...)" block - not even inside an
rem echo string. cmd treats them as block delimiters, so a bracket closes the block
rem early and the remaining lines run UNCONDITIONALLY and silently.
if errorlevel 1 (
  echo.
  echo [WARN] Install failed. Network issue? Try another index manually:
  echo        .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple
  echo        Note: the tsinghua mirror may answer pip with HTTP 403 on some
  echo              networks, while curl on the same URL still returns 200 - so it
  echo              is easy to misread as "package not found". If you see
  echo              "from versions: none", try another mirror.
  pause
  exit /b 1
)

rem ------------------------------------------------------------------
rem [4/4] Really import the packages. pip's exit code only means
rem "installation commands succeeded" - this actually proves the app
rem can start, which is what the user cares about.
rem ------------------------------------------------------------------
echo [4/4] Verifying imports ...
".venv\Scripts\python.exe" -c "import PySide6, pynput, httpx; print('      deps ok:', PySide6.__version__)"
if errorlevel 1 (
  echo [ERROR] Dependencies installed but cannot be imported.
  pause
  exit /b 1
)

echo.
echo Done. Double-click the launcher .cmd below to start:
rem List by walking the filesystem instead of hardcoding the name,
rem so this stays ASCII-only and never goes stale.
for %%F in ("%~dp0*.cmd") do if /i not "%%~nxF"=="%~nx0" echo     %%~nxF
pause
