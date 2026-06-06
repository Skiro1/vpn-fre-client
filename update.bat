@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
echo === VPN-Client update ===
echo Refreshing all external binaries to the latest published releases.
echo.

call "tools\update.bat"
if errorlevel 1 exit /b 1

echo.
echo Done. Rebuild with build_release.bat or build_debug.bat to apply.
pause
