@echo off
REM Start everything on Windows. Opens two windows (backend, frontend). Close them to stop.
cd /d "%~dp0"

if not exist backend\.venv (echo Run setup.bat first. & exit /b 1)
if not exist frontend\node_modules (echo Run setup.bat first. & exit /b 1)

echo ==^> Checking MongoDB
cd backend
call .venv\Scripts\activate.bat
python -c "import asyncio,sys; from pymongo import AsyncMongoClient; from app.config import get_settings; exec('async def m():\n c=AsyncMongoClient(get_settings().mongodb_uri,serverSelectionTimeoutMS=1500)\n try:\n  await c.admin.command(\"ping\")\n except Exception:\n  sys.exit(1)\n finally:\n  await c.close()'); asyncio.run(m())" >nul 2>&1
if errorlevel 1 (
  where docker >nul 2>&1
  if not errorlevel 1 (
    echo MongoDB is not running; starting it with Docker...
    cd ..
    docker compose up -d mongo
    timeout /t 8 >nul
    cd backend
  )
)
python -c "import asyncio,sys; from pymongo import AsyncMongoClient; from app.config import get_settings; exec('async def m():\n c=AsyncMongoClient(get_settings().mongodb_uri,serverSelectionTimeoutMS=3000)\n try:\n  await c.admin.command(\"ping\")\n except Exception:\n  sys.exit(1)\n finally:\n  await c.close()'); asyncio.run(m())" >nul 2>&1
if errorlevel 1 (
  echo Cannot reach MongoDB at MONGODB_URI in backend\.env.
  echo Start MongoDB, or run: docker compose up -d mongo, or use a MongoDB Atlas connection string. See README.md.
  exit /b 1
)

echo ==^> Loading the demo campus (safe to repeat)
python -m app.network_model.seed
echo ==^> Loading 24 hours of demo history if there is none yet (so every graph is full)
python -m app.demo --if-empty
cd ..

echo ==^> Starting backend and frontend in new windows
start "Campus NOC backend" cmd /k "cd /d %~dp0backend && call .venv\Scripts\activate.bat && uvicorn app.main:app --port 8000"
start "Campus NOC frontend" cmd /k "cd /d %~dp0frontend && npm run dev -- --host 127.0.0.1"
echo.
echo Open http://localhost:5173   (API docs: http://localhost:8000/docs)
