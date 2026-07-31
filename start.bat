@echo off
cd /d "%~dp0"

echo.
echo   Norms Browser starting...
echo   http://localhost:8080/norms_browser.html
echo   Press Ctrl+C to stop
echo.

python "%~dp0start.py" %*
pause
