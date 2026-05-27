@echo off
echo === DEBUG BUILD ===

if not exist ".venv\Scripts\python.exe" (
    echo Creating venv...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Installing deps...
pip install -q -r requirements.txt

if not exist "opera-proxy.exe" (
    echo Downloading opera-proxy...
    curl -sL -o opera-proxy.exe "https://github.com/Alexey71/opera-proxy/releases/download/v1.17.0/opera-proxy.windows-amd64.exe"
)
if not exist "warp-awg-gen.exe" (
    echo Downloading warp-awg-gen...
    curl -sL -o warp-awg-gen.exe "https://github.com/Skiro1/warp-awg-gen/releases/download/v1.0.0/warp-awg-gen-windows-amd64.exe"
)

pyinstaller --noconfirm --onefile --console --uac-admin ^
  --name "VPN-Client-Debug" ^
  --icon "IMG\icon.ico" ^
  --add-binary "opera-proxy.exe;." ^
  --add-binary "warp-awg-gen.exe;." ^
  vpn_client.py

echo Done! exe in dist\VPN-Client-Debug.exe
pause
