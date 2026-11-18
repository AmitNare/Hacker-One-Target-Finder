@echo off
setlocal
set "TARGET=%~dp0START_HACKERONE_TARGET_FINDER.bat"
set "WORKDIR=%~dp0"
set "SHORTCUT=%USERPROFILE%\Desktop\HackerOne Target Finder.lnk"
if not exist "%TARGET%" (
  echo [ERROR] START_HACKERONE_TARGET_FINDER.bat was not found.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut('%SHORTCUT%'); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%WORKDIR%'; $s.Description='Run HackerOne Target Finder'; $s.Save()"
if errorlevel 1 (
  echo [ERROR] Could not create the desktop shortcut.
  pause
  exit /b 1
)
echo.
echo [SUCCESS] Desktop shortcut created:
echo %SHORTCUT%
echo You can now double-click it to run HackerOne Target Finder.
echo.
pause
