@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
echo === VPN-Client update ===
echo This script refreshes all external binaries to their latest published
echo versions. The Python virtual environment and pip packages are NOT touched.
echo Use setup.bat instead if you need to recreate the venv from scratch.
echo.

REM ---------------------------------------------------------------
REM 1) External proxies
REM ---------------------------------------------------------------
echo [1/4] Refreshing external proxies (latest releases)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\download_proxies.ps1" -ProjectRoot "%CD%"
if errorlevel 1 echo   WARNING: download_proxies.ps1 had errors, check output above

REM ---------------------------------------------------------------
REM 2) Zapret binaries and lists
REM ---------------------------------------------------------------
echo.
echo [2/4] Refreshing Zapret binaries, lists and lua scripts (latest releases)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\download_zapret.ps1" -ProjectRoot "%CD%"
if errorlevel 1 echo   WARNING: download_zapret.ps1 had errors, check output above

REM ---------------------------------------------------------------
REM 3-4) Strategy presets (youtubediscord + Flowseal + AntiZapret)
REM ---------------------------------------------------------------
echo.
echo [3/4] Refreshing Zapret strategy presets...
if not exist ".venv\Scripts\python.exe" (
    echo   .venv not found - bootstrapping with system python
    set "PY=python"
) else (
    call ".venv\Scripts\activate.bat"
    set "PY=python"
)

%PY% "tools\fetch_zapret_presets.py"
if errorlevel 1 echo   WARNING: fetch_zapret_presets.py had errors, check output above

echo.
echo [4/5] Refreshing Flowseal/AntiZapret presets...
%PY% "tools\fetch_flowseal_presets.py"
if errorlevel 1 echo   WARNING: fetch_flowseal_presets.py had errors, check output above
%PY% "tools\fetch_antizapret_presets.py"
if errorlevel 1 echo   WARNING: fetch_antizapret_presets.py had errors, check output above

echo.
echo [5/5] Refreshing Zapret2Setup .bin assets (winws, fakes, dbankcloud, list-extended)...
%PY% "tools\fetch_zapret_setup.py"
if errorlevel 1 echo   WARNING: fetch_zapret_setup.py had errors, check output above

REM ---------------------------------------------------------------
REM Done
REM ---------------------------------------------------------------
echo.
echo ============================================================
echo  VPN-Client update complete.
echo.
echo  Rebuild the executable with:  build_release.bat
echo  or (debug build):            build_debug.bat
echo ============================================================
echo.
pause
