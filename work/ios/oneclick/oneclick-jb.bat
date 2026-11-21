@echo off
chcp 936 >nul
cd /d "%~dp0"
echo ============================================
echo   SuperLocator  one-click jailbreak helper
echo   keep this window open until it finishes
echo ============================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0jb.ps1" -Run
echo.
pause
