@echo off
setlocal

where uv >nul 2>&1
if errorlevel 1 (
    echo uv was not found. Install uv and try again.
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo npm was not found. Install Node.js 22 LTS and try again.
    pause
    exit /b 1
)

if not exist "%~dp0frontend\node_modules" (
    echo Frontend dependencies are missing. Run "cd frontend ^&^& npm install" first.
    pause
    exit /b 1
)

start "Instrument Capture API" /D "%~dp0" cmd.exe /k "uv run uvicorn app.asgi:app --app-dir src/backend --host 127.0.0.1 --port 8001"

for /f %%P in ('powershell -NoProfile -Command "$port = 5173; try { $response = Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 2; if ($response.Content -match '/@vite/client') { 'EXISTING'; exit 0 } } catch {}; while ($port -le 5199) { $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port); try { $listener.Start(); $listener.Stop(); Write-Output $port; exit 0 } catch { $port++ } }; exit 1"') do set "FRONTEND_PORT=%%P"

if /i "%FRONTEND_PORT%"=="EXISTING" (
    echo Reusing the existing frontend at http://127.0.0.1:5173
    set "FRONTEND_PORT=5173"
) else if defined FRONTEND_PORT (
    start "Instrument Capture Frontend" /D "%~dp0frontend" cmd.exe /k "npm run dev -- --port %FRONTEND_PORT%"
) else (
    echo Could not find an available frontend port from 5173 to 5199.
    pause
    exit /b 1
)

timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:%FRONTEND_PORT%"

echo API:      http://127.0.0.1:8001/docs
echo Frontend: http://127.0.0.1:%FRONTEND_PORT%
endlocal