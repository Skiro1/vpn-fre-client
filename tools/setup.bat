@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
echo === VPN-Client setup ===
echo This script downloads and prepares everything needed to build the VPN client.
echo All external binaries are pulled at their latest published versions.
echo.

REM ---------------------------------------------------------------
REM 1) Python venv + requirements
REM ---------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [1/7] Creating Python virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :error
) else (
    echo [1/7] Using existing .venv
)
call ".venv\Scripts\activate.bat"

echo [1/6] Installing Python dependencies...
pip install -q -r requirements.txt
if errorlevel 1 goto :error

REM ---------------------------------------------------------------
REM 2) External proxies (opera-proxy, warp-awg-gen, hola-proxy)
REM ---------------------------------------------------------------
echo.
echo [2/7] Downloading external proxies (latest releases)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\download_proxies.ps1" -ProjectRoot "%CD%"
if errorlevel 1 echo   WARNING: download_proxies.ps1 had errors, check output above

REM ---------------------------------------------------------------
REM 3) Zapret binaries and lists (v1 + v2) - latest releases
REM ---------------------------------------------------------------
echo.
echo [3/7] Downloading Zapret binaries, lists and lua scripts (latest releases)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\download_zapret.ps1" -ProjectRoot "%CD%"
if errorlevel 1 echo   WARNING: download_zapret.ps1 had errors, check output above

REM ---------------------------------------------------------------
REM 4) Zapret strategy presets (youtubediscord + Flowseal + AntiZapret)
REM ---------------------------------------------------------------
echo.
echo [4/7] Generating Zapret strategy presets (youtubediscord/zapret)...
python "tools\fetch_zapret_presets.py"
if errorlevel 1 echo   WARNING: fetch_zapret_presets.py had errors, check output above

echo.
echo [5/6] Generating Zapret strategy presets (Flowseal general*)...
python "tools\fetch_flowseal_presets.py"
if errorlevel 1 echo   WARNING: fetch_flowseal_presets.py had errors, check output above

echo.
echo [6/7] Generating Zapret strategy presets (pumPCin/AntiZapret)...
python "tools\fetch_antizapret_presets.py"
if errorlevel 1 echo   WARNING: fetch_antizapret_presets.py had errors, check output above

echo.
echo [7/7] Fetching Zapret2Setup .bin assets (winws, fakes, dbankcloud, list-extended)...
python "tools\fetch_zapret_setup.py"
if errorlevel 1 echo   WARNING: fetch_zapret_setup.py had errors, check output above

REM ---------------------------------------------------------------
REM Done
REM ---------------------------------------------------------------
echo.
echo ============================================================
echo  VPN-Client setup complete.
echo.
echo  Build the executable with:  build_release.bat
echo  or (debug build):          build_debug.bat
echo  Update only binaries:      update.bat
echo ============================================================
echo.
pause
goto :eof

:error
echo.
echo *** SETUP FAILED ***
echo Please check the messages above and retry.
exit /b 1
