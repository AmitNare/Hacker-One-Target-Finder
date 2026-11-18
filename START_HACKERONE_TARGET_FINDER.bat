@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo       HACKERONE AUTOMATED BUG BOUNTY TARGET FINDER
echo ============================================================
echo.
echo This launcher will prepare the project environment if needed,
echo install/check required Python packages, and start the tool.
echo.
call "%~dp0RUN_WINDOWS.bat" %*
exit /b %ERRORLEVEL%
