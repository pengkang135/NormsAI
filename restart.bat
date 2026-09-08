@echo off
cd /d "%~dp0"
echo Stopping server on port 18080...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18080.*LISTENING"') do (
    echo Killing PID %%a
    taskkill /F /PID %%a 2>nul
)
echo Starting server...
echo   http://localhost:18080/norms_browser.html
echo   Press Ctrl+C to stop
echo.
python "%~dp0start.py"
