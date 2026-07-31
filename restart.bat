@echo off
cd /d "%~dp0"
echo Stopping server on port 8080...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080.*LISTENING"') do (
    echo Killing PID %%a
    taskkill /F /PID %%a 2>nul
)
echo Starting server...
start "Norms-AI" python start.py
echo Done. Server restarted at http://localhost:8080
