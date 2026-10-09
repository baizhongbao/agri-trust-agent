@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   Agri Trust Agent - Launcher
echo ========================================

echo [1/2] Starting backend API ...
start "agri-backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend"

echo [2/2] Starting frontend Vite ...
start "agri-frontend" cmd /k "cd /d frontend && npm run dev"

echo.
echo Backend: http://127.0.0.1:8000  (docs: /docs)
echo Frontend: http://127.0.0.1:5173
echo.
pause