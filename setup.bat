@echo off
REM One-time setup for Windows: Python venv + dependencies, npm install, .env files.
cd /d "%~dp0"

where python >nul 2>&1 || (echo Python 3.12+ is required. Install it from python.org and tick "Add to PATH". & exit /b 1)
where node >nul 2>&1 || (echo Node.js 20+ is required. Install it from nodejs.org. & exit /b 1)

echo ==^> Backend: virtual environment and packages
cd backend
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt || (echo pip install failed & exit /b 1)
if not exist .env copy .env.example .env >nul
cd ..

echo ==^> Frontend: npm packages
cd frontend
if not exist .env copy .env.example .env >nul
call npm install --no-audit --no-fund || (echo npm install failed & exit /b 1)
cd ..

echo.
echo Setup finished. Next: start.bat
