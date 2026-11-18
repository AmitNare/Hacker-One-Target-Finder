@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python Launcher py was not found. Install Python 3.10+.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating project virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)
echo [INFO] Installing dependencies into the project .venv...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
echo.
echo [INFO] Starting HackerOne Target Finder...
".venv\Scripts\python.exe" main.py %*
set EXITCODE=%ERRORLEVEL%
echo.
pause
exit /b %EXITCODE%
:error
echo [ERROR] Setup failed. Check internet access and the error above.
pause
exit /b 1
