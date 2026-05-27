import os
import sys
from github import Github

token = os.environ.get("GH_TOKEN")
if not token:
    print("GH_TOKEN не найден. Вставьте свой GitHub personal access token:")
    print("Settings -> Developer settings -> Personal access tokens -> Tokens (classic)")
    print("Дайте права repo и write:packages")
    sys.exit(1)

g = Github(token)
repo = g.get_repo("Skiro1/vpn-fre-client")

release = repo.create_git_release(
    tag="v1.6.0",
    name="v1.6.0",
    message="VPN Client v1.6.0\n\n- Opera Proxy с выбором региона (EU/AS/AM)\n- Cloudflare WARP (AmneziaWG)\n- TCP-пинг в реальном времени\n- Автообновление бинарников\n- Автоустановка AmneziaWG\n- Экстренный сброс соединений",
    draft=True,
    prerelease=False,
)

# Загружаем бинарники
for exe_name in ["VPN-Client.exe", "VPN-Client-Debug.exe"]:
    path = os.path.join("dist", exe_name)
    if os.path.exists(path):
        print(f"Загружаю {path}...")
        release.upload_asset(path, label=exe_name)
        print(f"  {exe_name} загружен")
    else:
        print(f"  {path} не найден, пропускаю")

print(f"\nРелиз создан: {release.html_url}")
print(f"Откройте ссылку и нажмите 'Publish release' чтобы опубликовать.")