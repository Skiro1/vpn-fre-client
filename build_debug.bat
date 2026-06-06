@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
echo === VPN-Client DEBUG BUILD ===
echo.

REM ---------------------------------------------------------------
REM Step 1: ensure venv + latest external binaries exist.
REM Always calls tools\setup.bat (or tools\update.bat on subsequent
REM runs) so that the latest published versions of zapret, zapret2,
REM lua scripts, lists and proxy executables are pulled in.
REM ---------------------------------------------------------------
echo [setup] Preparing environment with the latest external binaries...
if not exist ".venv\Scripts\python.exe" (
    call "tools\setup.bat"
    if errorlevel 1 exit /b 1
) else (
    REM Re-run only the binary-download steps to guarantee latest versions.
    call "tools\update.bat"
    if errorlevel 1 exit /b 1
)

call ".venv\Scripts\activate.bat"

REM ---------------------------------------------------------------
REM Step 1b: ensure dev dependencies (pyinstaller) are installed
REM ---------------------------------------------------------------
echo [dev] Installing/updating build dependencies (pyinstaller)...
pip install -q -r requirements-dev.txt
if errorlevel 1 (
    echo.
    echo *** PIP INSTALL FAILED ***
    exit /b 1
)

REM ---------------------------------------------------------------
REM Step 2: PyInstaller (console mode for debug output)
REM ---------------------------------------------------------------
set "DPI_DATA="
if exist "zapret\bin\winws.exe"      set "DPI_DATA=--add-data "zapret;zapret""
if exist "zapret\zapret2\bin\winws2.exe" set "DPI_DATA=%DPI_DATA% --add-data "zapret\zapret2;zapret\zapret2""
if not defined DPI_DATA echo WARNING: Zapret not bundled - DPI bypass will not be available.

pyinstaller --noconfirm --onefile --console --uac-admin ^
  --name "VPN-Client-Debug" ^
  --icon "IMG\icon.ico" ^
  --add-data "IMG;IMG" ^
  --add-binary "opera-proxy.exe;." ^
  --add-binary "warp-awg-gen.exe;." ^
  --add-binary "hola-proxy.exe;." ^
  %DPI_DATA% ^
  vpn_client.py

if errorlevel 1 (
    echo.
    echo *** BUILD FAILED ***
    exit /b 1
)
echo.
echo Build complete. EXE: dist\VPN-Client-Debug.exe
pause
