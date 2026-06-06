# -*- coding: utf-8 -*-
"""
VPN Client v2.0.0 — мульти-движковый бесплатный VPN/прокси (Windows)

Движки:
  Прокси-выход (HTTP, ровно один активен, делят системный прокси-слот Windows):
    - Opera Proxy        (opera-proxy.exe,        127.0.0.1:18080)
    - Hola Proxy         (hola-proxy.exe,         127.0.0.1:24080)
  Дополнительно (комбинируются с любым прокси и друг с другом):
    - Cloudflare WARP    (AmneziaWG, туннель L3)
    - Обход DPI          (Zapret, WinDivert, без смены IP)

Изменения в v2.0.0:
  - Добавлен Hola Proxy (без регистрации)
  - Добавлен обход DPI на базе GoodbyeDPI (авто-загрузка + распаковка)
  - Прокси-движки взаимоисключающие за системный прокси-слот, WARP и DPI — поверх
  - Минималистичный Ч/Б интерфейс, тумблеры на каждый движок, настройки внешнего вида

Изменения в v1.6.0:
  - Автоустановка AmneziaWG (скачивание MSI + msiexec /quiet)
  - TCP-пинг вместо ICMP (работает через файрволы)
  - Прогресс пинга в реальном времени
"""

import os
import sys
import json
import time
import ctypes
import logging
import threading
import subprocess
import tempfile
import re
import socket
import platform
import zipfile
import urllib.request
from datetime import datetime
from dataclasses import dataclass

try:
    import winreg
except ImportError:
    winreg = None

try:
    import atexit
except ImportError:
    atexit = None

try:
    import signal
except ImportError:
    signal = None

import webview

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
LOG_FILE = os.path.join(tempfile.gettempdir(), "vpn_client_debug.log")


def _autoclear_logs_enabled():
    try:
        _sf = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()), "VPNClient", "settings.json")
        if os.path.exists(_sf):
            with open(_sf, "r", encoding="utf-8") as _f:
                return bool(json.load(_f).get("auto_clear_logs", False))
    except Exception:
        pass
    return False


_LOG_MODE = "w" if _autoclear_logs_enabled() else "a"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode=_LOG_MODE, encoding="utf-8"),
        (logging.StreamHandler(sys.stdout) if sys.stdout is not None else logging.NullHandler()) if "--debug" in sys.argv else logging.NullHandler(),
    ],
)
log = logging.getLogger("vpn-client")
log.info(f"Лог-файл: {LOG_FILE}")

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------
APP_NAME = "VPN Client"
APP_VERSION = "2.0.0"

OPERA_EXE = "opera-proxy.exe"
WARP_GEN_EXE = "warp-awg-gen.exe"
HOLA_EXE = "hola-proxy.exe"
WARP_CONF_NAME = "warp.conf"

ZAPRET_DIR = "zapret"
ZAPRET_WINWS = "winws.exe"
ZAPRET2_DIR = "zapret2"           # подпапка внутри zapret/
ZAPRET2_WINWS = "winws2.exe"

AMNEZIAWG_VERSION = "2.0.0"
OPERA_PROXY_VERSION = "v1.17.0"
WARP_AWG_GEN_VERSION = "v1.0.0"
# Версии можно при необходимости обновить вручную (см. github releases)
HOLA_VERSION = "v1.18.2"
ZAPRET_VERSION = "1.9.9a"

BINARY_ARCH_MAP = {"amd64": "amd64", "arm64": "arm64", "x86": "386"}


def _amnezia_arch():
    m = platform.machine().lower()
    if m in ("amd64", "x86_64"):
        return "amd64"
    elif m == "arm64":
        return "arm64"
    else:
        return "x86"


_AWG_ARCH = _amnezia_arch()                          # amd64 | arm64 | x86
_BIN_ARCH = BINARY_ARCH_MAP.get(_AWG_ARCH, "amd64")  # amd64 | arm64 | 386

AMNEZIAWG_MSI_URL = (
    "https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/"
    f"{AMNEZIAWG_VERSION}/amneziawg-{_AWG_ARCH}-{AMNEZIAWG_VERSION}.msi"
)
OPERA_PROXY_URL = (
    "https://github.com/Alexey71/opera-proxy/releases/download/"
    f"{OPERA_PROXY_VERSION}/opera-proxy.windows-{_BIN_ARCH}.exe"
)
WARP_AWG_GEN_URL = (
    "https://github.com/Skiro1/warp-awg-gen/releases/download/"
    f"{WARP_AWG_GEN_VERSION}/warp-awg-gen-windows-{_BIN_ARCH}.exe"
)
HOLA_URL = (
    "https://github.com/Snawoot/hola-proxy/releases/download/"
    f"{HOLA_VERSION}/hola-proxy.windows-{_BIN_ARCH}.exe"
)
ZAPRET_TEST_URLS = [
    ("YouTube", "https://www.youtube.com/"),
    ("Discord", "https://discord.com/"),
    ("Instagram", "https://www.instagram.com/"),
    ("Cloudflare", "https://www.cloudflare.com/"),
    ("Cloudflare WARP", "https://api.cloudflareclient.com/v0a1604021500/reg"),
    ("Cloudflare 1.1.1.1", "https://1.1.1.1/"),
    ("Cloudflare Workers", "https://workers.dev/"),
    ("Cloudflare Blog", "https://blog.cloudflare.com/"),
    ("Cloudflare Trace", "https://www.cloudflare.com/cdn-cgi/trace"),
    ("Cloudflare Turnstile", "https://challenges.cloudflare.com/"),
    ("Cloudflare Dashboard", "https://dash.cloudflare.com/"),
    ("GitHub", "https://github.com/"),
    ("Twitter/X", "https://x.com/"),
    ("Facebook", "https://www.facebook.com/"),
    ("Reddit", "https://www.reddit.com/"),
    ("Twitch", "https://www.twitch.tv/"),
    ("OpenAI", "https://chat.openai.com/"),
    # Заблокированные в РФ российские сервисы (itdoginfo/allow-domains outside-raw)
    ("Ozon", "https://www.ozon.ru/"),
    ("Gosuslugi", "https://www.gosuslugi.ru/"),
    ("Mos.ru", "https://www.mos.ru/"),
    ("Nalog.ru", "https://www.nalog.ru/"),
    ("RZD", "https://www.rzd.ru/"),
    ("Pochta.ru", "https://www.pochta.ru/"),
    ("Leroy Merlin", "https://leroymerlin.ru/"),
    ("Yandex Net", "https://yandex.net/"),
    ("Mosreg", "https://mosreg.ru/"),
    ("Rosreestr", "https://rosreestr.gov.ru/"),
    ("FSSP", "https://fssp.gov.ru/"),
    ("Russianpost", "https://www.russianpost.ru/"),
    ("Emex", "https://emex.ru/"),
    # Заблокированные в РФ крупные сервисы (1andrevich/Re-filter-lists domains_all.lst)
    # Мессенджеры / AI
    ("Telegram", "https://telegram.org/"),
    ("T.me", "https://t.me/"),
    ("Signal", "https://signal.org/"),
    ("WhatsApp", "https://www.whatsapp.com/"),
    ("Snapchat", "https://www.snapchat.com/"),
    ("Claude", "https://claude.ai/"),
    ("ChatGPT", "https://chatgpt.com/"),
    ("Google Meet", "https://meet.google.com/"),
    ("Notion", "https://www.notion.so/"),
    ("LinkedIn", "https://www.linkedin.com/"),
    # Медиа / развлечения
    ("Netflix", "https://www.netflix.com/"),
    ("Spotify", "https://open.spotify.com/"),
    ("SoundCloud", "https://soundcloud.com/"),
    ("TikTok", "https://www.tiktok.com/"),
    ("RuTracker", "https://rutracker.org/"),
    # VPN / email / privacy / payments
    ("NordVPN", "https://nordvpn.com/"),
    ("Mullvad", "https://mullvad.net/"),
    ("Proton", "https://proton.me/"),
    ("Tutanota", "https://tutanota.com/"),
    ("PayPal", "https://www.paypal.com/"),
    # Альт. платформы / новости / gaming
    ("BBC", "https://www.bbc.com/"),
    ("Rumble", "https://rumble.com/"),
    ("Odysee", "https://odysee.com/"),
    ("Chess.com", "https://www.chess.com/"),
    ("Nintendo", "https://www.nintendo.com/"),
]

# Режимы авто-подбора (настройка zapret_auto_mode в settings.json):
#   "both" — тестировать и v1, и v2 (по умолчанию)
#   "v1"   — только v1 (zapret)
#   "v2"   — только v2 (zapret2)
ZAPRET_AUTO_MODES = ("both", "v1", "v2")

# Tier 1 (smoke): 5 must-work URL для быстрого отсева 261 стратегий.
# Если smoke < MIN_SMOKE_FOR_DETAILED — Tier 2 не запускаем (явно плохая).
# Если smoke = 5/5 — Tier 2 всё равно запускаем (для точного счёта 55/55),
# но early-exit при detailed 55/55.
ZAPRET_SMOKE_URLS = [
    ("YouTube", "https://www.youtube.com/"),
    ("Discord", "https://discord.com/"),
    ("Cloudflare", "https://www.cloudflare.com/"),
    ("GitHub", "https://github.com/"),
    ("Twitter/X", "https://x.com/"),
]
SMOKE_TIMEOUT = 2         # секунд на URL в Tier 1
SMOKE_WORKERS = 5         # параллельных HEAD/GET (по числу URL)
DETAILED_TIMEOUT = 3      # секунд на URL в Tier 2
DETAILED_WORKERS = 10     # параллельных HEAD/GET для 55 URL
MIN_SMOKE_FOR_DETAILED = 3  # 3/5 = 60% — порог для Tier 2

OPERA_REGIONS = {
    "EU": "\u0415\u0432\u0440\u043e\u043f\u0430",
    "AS": "\u0410\u0437\u0438\u044f",
    "AM": "\u0410\u043c\u0435\u0440\u0438\u043a\u0430",
}

SETTINGS_FILE = os.path.join(
    os.environ.get("APPDATA", tempfile.gettempdir()),
    "VPNClient", "settings.json",
)

PROXY_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

# ---------------------------------------------------------------------------
# Умный поиск AmneziaWG
# ---------------------------------------------------------------------------
def find_amnezia_exe() -> str:
    candidates = [
        r"C:\Program Files\AmneziaWG\amneziawg.exe",
        r"C:\Program Files (x86)\AmneziaWG\amneziawg.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\AmneziaWG\amneziawg.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\AmneziaWG\amneziawg.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            log.info(f"AmneziaWG найден: {p}")
            return p

    try:
        r = subprocess.run(
            ["where.exe", "amneziawg.exe"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode == 0 and r.stdout.strip():
            path = r.stdout.strip().split("\n")[0].strip()
            if os.path.exists(path):
                log.info(f"AmneziaWG найден через PATH: {path}")
                return path
    except Exception as e:
        log.debug(f"where.exe failed: {e}")

    if winreg is not None:
        uninstall_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, base_path in uninstall_paths:
            try:
                with winreg.OpenKey(hive, base_path) as key:
                    for i in range(1024):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            try:
                                with winreg.OpenKey(key, subkey_name) as subkey:
                                    display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                                    if "amnezia" in str(display_name).lower() and "wg" in str(display_name).lower():
                                        install_loc, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                                        candidate = os.path.join(str(install_loc), "amneziawg.exe")
                                        if os.path.exists(candidate):
                                            log.info(f"AmneziaWG найден через реестр: {candidate}")
                                            return candidate
                            except (FileNotFoundError, OSError):
                                continue
                        except OSError:
                            break
            except (FileNotFoundError, OSError):
                continue

    log.warning("AmneziaWG не найден ни в одном из стандартных мест")
    return ""


AMNEZIA_EXE = find_amnezia_exe()

# ---------------------------------------------------------------------------
# Бинарники (opera-proxy, warp-awg-gen, hola-proxy, GoodbyeDPI)
# скачиваются на этапе СБОРКИ в build_debug.bat / build_release.bat и
# упаковываются рядом с программой (--add-binary / --add-data в PyInstaller).
# Авто-загрузка при запуске убрана — приложение ожидает готовые бинарники.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------
def get_resource_path(filename: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        candidate = os.path.join(sys._MEIPASS, filename)
        if os.path.exists(candidate):
            return candidate
    candidate = os.path.join(os.path.abspath("."), filename)
    if os.path.exists(candidate):
        return candidate
    if getattr(sys, "frozen", False):
        candidate = os.path.join(os.path.dirname(sys.executable), filename)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(os.path.abspath("."), filename)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def safe_json(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)


def decode_output(data) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        for enc in ("utf-8", "cp866", "cp1251", "latin-1"):
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, AttributeError):
                continue
        return data.decode("utf-8", errors="replace")
    try:
        fixed = data.encode("latin-1").decode("cp866")
        if "\ufffd" not in fixed:
            return fixed
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    return data


HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8" />
<title>VPN Client</title>
<style>
body[data-theme="dark"]{--bg:#0b0b0c;--text:#f5f5f7;--muted:#8a8a90;--line:rgba(255,255,255,.12);
  --surface:rgba(255,255,255,.05);--on:#f5f5f7;--inv:#0b0b0c;--shadow:rgba(0,0,0,.55);--accent:#34d27b;}
body[data-theme="light"]{--bg:#f6f6f8;--text:#0b0b0c;--muted:#86868b;--line:rgba(0,0,0,.12);
  --surface:rgba(0,0,0,.04);--on:#0b0b0c;--inv:#f6f6f8;--shadow:rgba(0,0,0,.15);--accent:#1ea862;}
*{box-sizing:border-box;margin:0;padding:0;scrollbar-width:thin;scrollbar-color:var(--line) transparent;}
html,body{height:100%;}
body{font-family:'Inter','Segoe UI',-apple-system,system-ui,sans-serif;background:var(--bg);color:var(--text);
  min-height:100vh;overflow-x:hidden;user-select:none;-webkit-app-region:drag;transition:background .3s,color .3s;}
button,select,input,.no-drag{-webkit-app-region:no-drag;}
body.no-anim *,body.no-anim *::before,body.no-anim *::after{transition:none!important;animation:none!important;}
body.no-fx *{box-shadow:none!important;}
body.no-fx .overlay{backdrop-filter:none!important;}

/* кастомный скроллбар */
::-webkit-scrollbar{width:10px;height:10px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:var(--line);border-radius:8px;border:2px solid transparent;background-clip:content-box;}
::-webkit-scrollbar-thumb:hover{background:var(--muted);background-clip:content-box;}
::-webkit-scrollbar-corner{background:transparent;}

.wrap{max-width:410px;margin:0 auto;padding:22px 18px;min-height:100vh;display:flex;flex-direction:column;gap:16px;}
header{display:flex;align-items:center;justify-content:space-between;}
.logo{font-size:17px;font-weight:800;letter-spacing:.04em;}
.logo span{color:var(--muted);font-weight:500;}
.gear{width:36px;height:36px;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--text);
  cursor:pointer;display:grid;place-items:center;transition:.2s;}
.gear:hover{background:var(--surface);}

.status{display:flex;align-items:center;gap:14px;padding:20px;border:1px solid var(--line);border-radius:16px;background:var(--surface);}
.dot{width:14px;height:14px;border-radius:50%;border:2px solid var(--muted);flex:0 0 auto;transition:.3s;}
.dot.on{background:var(--accent);border-color:var(--accent);box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 22%,transparent);}
.dot.connecting{border-color:var(--text);animation:pulse 1.2s infinite;}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:.25;}}
.st-main{font-size:19px;font-weight:750;letter-spacing:-.2px;}
.st-sub{font-size:12.5px;color:var(--muted);margin-top:3px;}

.list{border:1px solid var(--line);border-radius:16px;overflow:hidden;}
.item{padding:16px;display:flex;flex-direction:column;gap:12px;}
.item+.item{border-top:1px solid var(--line);}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;}
.it-name{font-size:15px;font-weight:650;}
.it-sub{font-size:11.5px;color:var(--muted);margin-top:3px;}

.sw{position:relative;width:46px;height:26px;border-radius:999px;border:1px solid var(--line);background:transparent;
  cursor:pointer;flex:0 0 auto;transition:.25s;}
.sw>span{position:absolute;top:2px;left:2px;width:20px;height:20px;border-radius:50%;background:var(--muted);transition:.25s;}
.sw.on{background:var(--accent);border-color:var(--accent);}
.sw.on>span{left:22px;background:#fff;}
.sw.connecting>span{left:12px;background:var(--text);animation:blink 1s infinite;}
.sw.disabled{opacity:.4;cursor:not-allowed;}
@keyframes blink{50%{opacity:.35;}}

.pills{display:flex;gap:6px;}
.pill{flex:1;padding:8px 4px;border-radius:9px;border:1px solid var(--line);background:transparent;color:var(--muted);
  font-size:12px;font-weight:600;cursor:pointer;font-family:inherit;letter-spacing:.05em;transition:.2s;}
.pill:hover{color:var(--text);}
.pill.active{background:var(--on);color:var(--inv);border-color:var(--on);}
.sel{width:100%;padding:9px 11px;border-radius:9px;background:transparent;border:1px solid var(--line);
  color:var(--text);font-size:13px;outline:none;font-family:inherit;}
.sel:focus{border-color:var(--text);}
.sel option{background:var(--bg);color:var(--text);}

footer{text-align:center;color:var(--muted);font-size:11px;margin-top:auto;letter-spacing:.03em;}

.toasts{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);z-index:1100;display:flex;flex-direction:column;
  gap:8px;pointer-events:none;max-width:92vw;}
.toast{background:var(--bg);border:1px solid var(--line);border-left:3px solid var(--accent);padding:11px 15px;border-radius:10px;
  font-size:12.5px;min-width:220px;max-width:360px;box-shadow:0 12px 30px var(--shadow);animation:slideUp .28s ease;}
.toast.error{border-left-color:#e5484d;}
@keyframes slideUp{from{opacity:0;transform:translateY(14px);}to{opacity:1;transform:translateY(0);}}

.overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);display:none;align-items:center;justify-content:center;
  z-index:900;backdrop-filter:blur(5px);}
.overlay.show{display:flex;}
.sheet{width:90%;max-width:380px;max-height:88vh;overflow-y:auto;background:var(--bg);border:1px solid var(--line);
  border-radius:16px;padding:22px;box-shadow:0 24px 60px var(--shadow);animation:pop .22s ease;}
@keyframes pop{from{opacity:0;transform:scale(.96);}to{opacity:1;transform:scale(1);}}
.sheet h3{font-size:16px;font-weight:750;margin-bottom:16px;}
.sheet h4{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin:18px 0 8px;}
.field label{display:block;font-size:10px;color:var(--muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.1em;font-weight:600;}
.opt{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-top:1px solid var(--line);}
.opt b{font-size:13.5px;font-weight:600;display:block;}
.opt span{font-size:11px;color:var(--muted);}
.svc{display:flex;flex-direction:column;gap:8px;margin-top:6px;}
.svc button{width:100%;padding:11px;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--text);
  font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;transition:.2s;}
.svc button:hover:not(:disabled){background:var(--surface);}
.svc button:disabled{opacity:.4;cursor:not-allowed;}
.svc .danger{color:var(--muted);}
.svc .danger:hover:not(:disabled){color:#e5484d;border-color:#e5484d;}
.logrow{display:flex;align-items:center;gap:8px;}
.logrow #btnLogs{flex:1;width:auto;}
.logrow #optAutoClear{flex:0 0 46px;width:46px;height:26px;min-width:0;padding:0;border-radius:999px;}
.done{width:100%;margin-top:18px;padding:12px;border-radius:10px;border:1px solid var(--on);background:var(--on);color:var(--inv);
  font-size:13.5px;font-weight:650;cursor:pointer;font-family:inherit;}
.actions{display:flex;gap:9px;margin-top:14px;}
.actions button{flex:1;padding:11px;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--text);
  font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;transition:.2s;}
.actions button:hover:not(:disabled){background:var(--surface);}
.actions .primary{background:var(--on);color:var(--inv);border-color:var(--on);}
.actions button:disabled{opacity:.5;cursor:not-allowed;}

.ping-list{margin:14px 0 2px;border:1px solid var(--line);border-radius:10px;max-height:210px;overflow-y:auto;}
.ping-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 12px;font-size:13px;}
.ping-row+.ping-row{border-top:1px solid var(--line);}
.ping-host{color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.ping-ms{font-variant-numeric:tabular-nums;font-weight:650;flex:0 0 auto;}
.ping-ms.good{color:var(--accent);}
.ping-ms.mid{color:#e6a93b;}
.ping-ms.bad{color:#e5484d;}
.ping-ms.dim{color:var(--muted);font-weight:500;}
.ping-empty{color:var(--muted);font-size:13px;text-align:center;padding:18px;}

.spinner{width:13px;height:13px;border-radius:50%;border:2px solid var(--line);border-top-color:var(--text);
  animation:spin .8s linear infinite;display:inline-block;vertical-align:-2px;}
@keyframes spin{to{transform:rotate(360deg);}}
</style>
</head>
<body data-theme="dark">
<div class="wrap">
  <header>
    <div class="logo">VPN <span>Client</span></div>
    <button class="gear" id="btnSettings" title="Настройки"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg></button>
  </header>

  <div class="status">
    <div class="dot" id="stateDot"></div>
    <div>
      <div class="st-main" id="stateText">Не защищено</div>
      <div class="st-sub" id="stateSub">Все модули выключены</div>
    </div>
  </div>

  <div class="list">
    <div class="item">
      <div class="row">
        <div><div class="it-name">Opera Proxy</div><div class="it-sub" id="operaSub">Выключено</div></div>
        <button class="sw" id="operaSwitch" role="switch"><span></span></button>
      </div>
      <div class="pills" id="regionSeg">
        <button class="pill" data-region="EU">EU</button>
        <button class="pill" data-region="AS">AS</button>
        <button class="pill" data-region="AM">AM</button>
      </div>
    </div>
    <div class="item">
      <div class="row">
        <div><div class="it-name">Hola Proxy</div><div class="it-sub" id="holaSub">Выключено</div></div>
        <button class="sw" id="holaSwitch" role="switch"><span></span></button>
      </div>
      <select class="sel" id="holaSel"></select>
    </div>
    <div class="item">
      <div class="row">
        <div><div class="it-name">Cloudflare WARP</div><div class="it-sub" id="warpSub">Выключено</div></div>
        <button class="sw" id="warpSwitch" role="switch"><span></span></button>
      </div>
    </div>
    <div class="item">
      <div class="row">
        <div><div class="it-name">Обход DPI</div><div class="it-sub" id="dpiSub">Без смены IP</div></div>
        <button class="sw" id="dpiSwitch" role="switch"><span></span></button>
      </div>
    </div>
  </div>

  <footer>VPN Client v<span id="appVersion">2.0.0</span></footer>
</div>

<div class="overlay" id="settingsModal">
  <div class="sheet">
    <h3>Настройки</h3>
    <h4>Обход DPI (Zapret)</h4>
    <div class="field">
      <label>Стратегия</label>
      <select class="sel" id="selZapret">
        <option value="">— Выберите стратегию —</option>
        <option value="__auto__">Авто-подбор</option>
      </select>
    </div>
    <div class="field">
      <label>Режим авто-подбора</label>
      <select class="sel" id="selAutoMode">
        <option value="both">Zapret v1 + Zapret2 v2</option>
        <option value="v1">Только Zapret v1</option>
        <option value="v2">Только Zapret2 v2</option>
      </select>
    </div>
    <h4>Внешний вид</h4>
    <div class="field">
      <label>Тема</label>
      <div class="pills" id="themeSeg">
        <button class="pill" data-theme="dark">Тёмная</button>
        <button class="pill" data-theme="light">Светлая</button>
      </div>
    </div>
    <div class="opt"><div><b>Анимации</b><span>Переходы и движение</span></div><button class="sw" id="optAnim"><span></span></button></div>
    <div class="opt"><div><b>Эффекты</b><span>Тени и размытие</span></div><button class="sw" id="optFx"><span></span></button></div>
    <h4>Сервис</h4>
    <div class="svc">
      <div class="logrow">
        <button id="btnLogs">Просмотр логов</button>
        <button class="sw" id="optAutoClear" title="Автоочистка логов при запуске"><span></span></button>
      </div>
      <button id="btnWarpGen">Сгенерировать конфиг WARP</button>
      <button id="btnPing">Проверить пинг серверов</button>
      <button class="danger" id="btnKill">Аварийный сброс</button>
    </div>
    <button class="done" id="btnSettingsClose">Готово</button>
  </div>
</div>

<div class="overlay" id="pingModal">
  <div class="sheet">
    <h3>Пинг серверов</h3>
    <div class="pills" id="pingSrc">
      <button class="pill active" data-src="opera">Opera</button>
      <button class="pill" data-src="hola">Hola</button>
    </div>
    <div class="field" id="pingOperaWrap" style="margin-top:12px;">
      <label>Регион Opera</label>
      <div class="pills" id="pingRegion">
        <button class="pill" data-region="EU">EU</button>
        <button class="pill" data-region="AS">AS</button>
        <button class="pill" data-region="AM">AM</button>
      </div>
    </div>
    <div class="field" id="pingHolaWrap" style="margin-top:12px;display:none;">
      <label>Страна Hola</label>
      <select class="sel" id="pingHolaSel"></select>
    </div>
    <div class="ping-list" id="pingList"><div class="ping-empty">Нажмите «Запустить»</div></div>
    <div class="actions">
      <button id="btnPingClose">Закрыть</button>
      <button class="primary" id="btnPingRun">Запустить</button>
    </div>
  </div>
</div>

<div class="toasts" id="toasts"></div>

<script>
const $ = s => document.querySelector(s);
const REGION_NAMES = { EU:'Европа', AS:'Азия', AM:'Америка' };
const state = {
  opera:'disconnected', warp:'disconnected', hola:'disconnected', dpi:'disconnected',
  warpConfExists:false,
  settings:{ region:'EU', port:18080, hola_country:'us', hola_port:24080,
             zapret_strategy:'', zapret_auto_mode:'both',
             theme:'dark', anim:true, fx:true, auto_clear_logs:false },
  busy:{ opera:false, warp:false, hola:false, dpi:false },
  zapretStrategy:'',
  ping:{ source:'opera', region:null, hola:null, running:false, rows:{} },
};

function toast(msg, type='info', ttl=3400){
  const el=document.createElement('div'); el.className='toast'+(type==='error'?' error':''); el.textContent=msg;
  $('#toasts').appendChild(el);
  setTimeout(()=>{ el.style.transition='opacity .28s,transform .28s'; el.style.opacity='0';
    el.style.transform='translateY(14px)'; setTimeout(()=>el.remove(),280); }, ttl);
}
function setSwitch(el,on,connecting,disabled){
  if(!el) return;
  el.classList.toggle('on', !!on && !connecting);
  el.classList.toggle('connecting', !!connecting);
  el.classList.toggle('disabled', !!disabled);
}
async function callApi(name, ...args){
  if(!window.pywebview?.api){ toast('API ещё не готов'); return null; }
  try{ return await window.pywebview.api[name](...args); }
  catch(e){ console.error(name,e); toast('Ошибка: '+(e&&e.message||e),'error'); return null; }
}
async function persist(){ await callApi('save_settings', JSON.stringify(state.settings)); }
function subText(st, onText){
  return st==='connected'?(onText||'Активно') : st==='connecting'?'Подключение…' : st==='error'?'Ошибка' : 'Выключено';
}
function applyVisuals(){
  document.body.dataset.theme = state.settings.theme==='light'?'light':'dark';
  document.body.classList.toggle('no-anim', state.settings.anim===false);
  document.body.classList.toggle('no-fx', state.settings.fx===false);
  document.querySelectorAll('#themeSeg .pill').forEach(b=>b.classList.toggle('active', b.dataset.theme===(state.settings.theme||'dark')));
  setSwitch($('#optAnim'), state.settings.anim!==false, false, false);
  setSwitch($('#optFx'), state.settings.fx!==false, false, false);
}

function render(){
  const {opera:op, warp:wp, hola:hl, dpi:dp} = state;
  const all=[]; if(op==='connected')all.push('Opera'); if(hl==='connected')all.push('Hola');
  if(wp==='connected')all.push('WARP'); if(dp==='connected')all.push('DPI');
  const connecting=[op,wp,hl,dp].includes('connecting');
  const dot=$('#stateDot'), main=$('#stateText'), sub=$('#stateSub');
  dot.classList.remove('on','connecting');
  if(connecting){ dot.classList.add('connecting'); main.textContent='Подключение…'; sub.textContent='Устанавливаем соединение'; }
  else if(all.length){ dot.classList.add('on'); main.textContent='Защищено'; sub.textContent=all.join(' + '); }
  else { main.textContent='Не защищено'; sub.textContent='Все модули выключены'; }

  setSwitch($('#operaSwitch'), op==='connected', op==='connecting', state.busy.opera&&op!=='connecting');
  setSwitch($('#holaSwitch'),  hl==='connected', hl==='connecting', state.busy.hola&&hl!=='connecting');
  setSwitch($('#warpSwitch'),  wp==='connected', wp==='connecting', state.busy.warp&&wp!=='connecting');
  setSwitch($('#dpiSwitch'),   dp==='connected', dp==='connecting', state.busy.dpi&&dp!=='connecting');

  $('#operaSub').textContent = op==='connected'?('Активно · '+(REGION_NAMES[state.settings.region]||state.settings.region)):subText(op);
  $('#holaSub').textContent  = hl==='connected'?('Активно · '+((state.settings.hola_country||'us').toUpperCase())):subText(hl);
  $('#warpSub').textContent  = subText(wp,'Туннель активен');
  $('#dpiSub').textContent   = dp==='connected'?('Активно · '+(state.zapretStrategy||'авто')):'Без смены IP';

  document.querySelectorAll('#regionSeg .pill').forEach(b=>b.classList.toggle('active', b.dataset.region===state.settings.region));
}

function mkStatus(engine){
  return function(data){
    state[engine]=data.status;
    if(data.status!=='connecting') state.busy[engine]=false;
    if(data.strategy!==undefined) state.zapretStrategy=data.strategy;
    if(data.message) toast(data.message, data.status==='error'?'error':'info');
    render();
  };
}
window.onOperaStatus = mkStatus('opera');
window.onHolaStatus  = mkStatus('hola');
window.onWarpStatus  = mkStatus('warp');
window.onDpiStatus   = mkStatus('dpi');

window.onStatusPoll = function(d){
  ['opera','warp','hola','dpi'].forEach(k=>{
    if(d[k]!==undefined && state[k]!=='connecting' && d[k]!==state[k]) state[k]=d[k];
  });
  if(d.opera_region) state.settings.region=d.opera_region;
  if(d.opera_port) state.settings.port=d.opera_port;
  if(d.zapret_strategy) state.zapretStrategy=d.zapret_strategy;
  if(d.warp_conf!==undefined) state.warpConfExists=d.warp_conf;
  render();
};
window.onSettingsLoaded = function(s){
  state.settings=Object.assign(state.settings,s);
  if(state.settings.zapret_strategy) state.zapretStrategy=state.settings.zapret_strategy;
  const z=$('#selZapret'); if(z) z.value=state.settings.zapret_strategy||'';
  const am=$('#selAutoMode');
  if(am) am.value=(state.settings.zapret_auto_mode||'both');
  const h=$('#holaSel'); if(h) h.value=state.settings.hola_country||'us';
  setSwitch($('#optAutoClear'), state.settings.auto_clear_logs===true, false, false);
  applyVisuals(); render();
};

async function toggleEngine(engine, connectFn, disconnectName){
  if(state.busy[engine]) return;
  state.busy[engine]=true;
  if(state[engine]==='connected'){ state[engine]='connecting'; render(); await callApi(disconnectName); }
  else { state[engine]='connecting'; render(); await connectFn(); }
}
$('#operaSwitch').addEventListener('click', ()=>toggleEngine('opera',
  async ()=>{ await callApi('start_connect', state.settings.region, state.settings.port); }, 'start_disconnect'));
$('#holaSwitch').addEventListener('click', ()=>toggleEngine('hola',
  async ()=>{ await callApi('start_connect_hola'); }, 'start_disconnect_hola'));
$('#warpSwitch').addEventListener('click', ()=>{
  if(state.warp!=='connected' && !state.warpConfExists){
    toast('Сначала сгенерируйте конфиг WARP в настройках','error'); openSettings(); return;
  }
  toggleEngine('warp', async ()=>{ await callApi('start_connect_warp'); }, 'start_disconnect_warp');
});
$('#dpiSwitch').addEventListener('click', ()=>{
  if(state.dpi!=='connected'){
    const strat=(state.settings.zapret_strategy||'').trim();
    if(!strat){ toast('Сначала выберите стратегию в настройках','error'); openSettings(); return; }
  }
  toggleEngine('dpi', async ()=>{ await callApi('start_connect_dpi', state.settings.zapret_strategy||''); }, 'start_disconnect_dpi');
});

document.querySelectorAll('#regionSeg .pill').forEach(btn=>{
  btn.addEventListener('click', async ()=>{
    if(btn.dataset.region===state.settings.region) return;
    state.settings.region=btn.dataset.region; render(); await persist();
    if(state.opera==='connected') toast('Регион применится при следующем подключении');
  });
});
const holaSel=$('#holaSel');
if(holaSel) holaSel.addEventListener('change', async (e)=>{
  state.settings.hola_country=(e.target.value||'us').toLowerCase(); await persist();
  if(state.hola==='connected') toast('Страна применится при следующем подключении');
});

function openSettings(){ $('#settingsModal').classList.add('show'); }
$('#btnSettings').addEventListener('click', openSettings);
$('#btnSettingsClose').addEventListener('click', ()=>$('#settingsModal').classList.remove('show'));

const selZ=$('#selZapret');
if(selZ) selZ.addEventListener('change', async ()=>{ state.settings.zapret_strategy=selZ.value||''; await persist(); });
const selAM=$('#selAutoMode');
if(selAM) selAM.addEventListener('change', async ()=>{ state.settings.zapret_auto_mode=selAM.value||'both'; await persist(); });
document.querySelectorAll('#themeSeg .pill').forEach(b=>{
  b.addEventListener('click', ()=>{ state.settings.theme=b.dataset.theme; applyVisuals(); persist(); });
});
$('#optAnim').addEventListener('click', ()=>{ state.settings.anim=!(state.settings.anim!==false); applyVisuals(); persist(); });
$('#optFx').addEventListener('click', ()=>{ state.settings.fx=!(state.settings.fx!==false); applyVisuals(); persist(); });

$('#btnWarpGen').addEventListener('click', async ()=>{
  if(state.busy.warp) return; state.busy.warp=true; render();
  await callApi('start_generate_warp'); state.busy.warp=false;
});
$('#btnLogs').addEventListener('click', async ()=>{ await callApi('open_logs'); });
$('#optAutoClear').addEventListener('click', async ()=>{
  state.settings.auto_clear_logs = !(state.settings.auto_clear_logs===true);
  setSwitch($('#optAutoClear'), state.settings.auto_clear_logs===true, false, false);
  await persist();
  toast(state.settings.auto_clear_logs ? 'Автоочистка логов включена (при следующем запуске)' : 'Автоочистка логов выключена');
});
$('#btnKill').addEventListener('click', async ()=>{
  if(!confirm('Сбросить все подключения и системный прокси?')) return;
  await callApi('force_kill_all');
  ['opera','warp','hola','dpi'].forEach(k=>{ state[k]='disconnected'; state.busy[k]=false; });
  render(); toast('Все процессы остановлены');
});

/* ----- Пинг ----- */
function syncPingUI(){
  document.querySelectorAll('#pingSrc .pill').forEach(b=>b.classList.toggle('active', b.dataset.src===state.ping.source));
  $('#pingOperaWrap').style.display = state.ping.source==='opera'?'block':'none';
  $('#pingHolaWrap').style.display  = state.ping.source==='hola'?'block':'none';
  document.querySelectorAll('#pingRegion .pill').forEach(b=>b.classList.toggle('active', b.dataset.region===state.ping.region));
  const ph=$('#pingHolaSel'); if(ph && state.ping.hola) ph.value=state.ping.hola;
}
function openPing(){
  state.ping.region = state.ping.region || state.settings.region || 'EU';
  state.ping.hola   = state.ping.hola   || state.settings.hola_country || 'us';
  state.ping.rows={};
  $('#pingList').innerHTML='<div class="ping-empty">Нажмите «Запустить»</div>';
  syncPingUI();
  $('#settingsModal').classList.remove('show');
  $('#pingModal').classList.add('show');
}
function pingEmpty(msg){
  state.ping.rows={};
  const e=document.createElement('div'); e.className='ping-empty'; e.textContent=msg;
  const list=$('#pingList'); list.innerHTML=''; list.appendChild(e);
}
function pingRow(host){
  let row=state.ping.rows[host];
  if(!row){
    const empty=$('#pingList').querySelector('.ping-empty'); if(empty) empty.remove();
    row=document.createElement('div'); row.className='ping-row';
    const h=document.createElement('span'); h.className='ping-host'; h.textContent=host;
    const v=document.createElement('span'); v.className='ping-ms dim';
    row.appendChild(h); row.appendChild(v);
    $('#pingList').appendChild(row);
    state.ping.rows[host]=row;
  }
  return row;
}
function msClass(ms){ return ms<100?'good':ms<250?'mid':'bad'; }
let _pingTimer=null;
function finishPing(){
  state.ping.running=false; clearTimeout(_pingTimer);
  const b=$('#btnPingRun'); if(b){ b.disabled=false; b.textContent='Запустить'; }
}
async function runPing(){
  if(state.ping.running) return;
  state.ping.running=true; state.ping.rows={};
  $('#pingList').innerHTML='<div class="ping-empty">Проверяем…</div>';
  const b=$('#btnPingRun'); b.disabled=true; b.innerHTML='<span class="spinner"></span> Проверка…';
  const key = state.ping.source==='hola' ? state.ping.hola : state.ping.region;
  clearTimeout(_pingTimer);
  _pingTimer=setTimeout(()=>{ if(state.ping.running){ pingEmpty('Истекло время ожидания'); finishPing(); } }, 50000);
  await callApi('start_ping', state.ping.source, key);
}
window.onPingProgress = function(d){
  if(!d || !d.server) return;
  const v=pingRow(d.server).querySelector('.ping-ms');
  if(d.status==='checking'){ v.className='ping-ms dim'; v.innerHTML='<span class="spinner"></span>'; }
  else if(d.status==='timeout'){ v.className='ping-ms bad'; v.textContent='нет ответа'; }
  else if(d.status==='ok'){ v.className='ping-ms '+msClass(d.ms); v.textContent=d.ms+' мс'; }
};
window.onPingResult = function(d){
  finishPing();
  if(d.error){ pingEmpty(d.error); toast(d.error,'error'); return; }
  toast('Лучший: '+d.ping+' мс'+(d.server?(' · '+d.server):''));
};
document.querySelectorAll('#pingSrc .pill').forEach(b=>{
  b.addEventListener('click', ()=>{ state.ping.source=b.dataset.src; syncPingUI(); });
});
document.querySelectorAll('#pingRegion .pill').forEach(b=>{
  b.addEventListener('click', ()=>{ state.ping.region=b.dataset.region; syncPingUI(); });
});
const pingHolaSel=$('#pingHolaSel');
if(pingHolaSel) pingHolaSel.addEventListener('change', e=>{ state.ping.hola=(e.target.value||'us').toLowerCase(); });
$('#btnPing').addEventListener('click', openPing);
$('#btnPingClose').addEventListener('click', ()=>$('#pingModal').classList.remove('show'));
$('#btnPingRun').addEventListener('click', runPing);

async function populateServers(){
  try{
    const hc = await callApi('list_hola_countries');
    const list = hc ? (typeof hc==='string'?JSON.parse(hc):hc) : [];
    if(list.length){
      [holaSel, $('#pingHolaSel')].forEach(sel=>{
        if(!sel) return;
        sel.innerHTML='';
        list.forEach(c=>{ const o=document.createElement('option'); o.value=c.code;
          o.textContent=c.name+' ('+String(c.code).toUpperCase()+')'; sel.appendChild(o); });
      });
      if(holaSel) holaSel.value=state.settings.hola_country||'us';
      const ph=$('#pingHolaSel'); if(ph) ph.value=state.ping.hola||state.settings.hola_country||'us';
    }
  }catch(e){ console.error('hola list',e); }
  try{
    const zs = await callApi('list_zapret_strategies');
    const strats = zs ? (typeof zs==='string'?JSON.parse(zs):zs) : [];
    if(selZ){
      selZ.innerHTML='<option value="">— Выберите стратегию —</option><option value="__auto__">Авто-подбор</option>';
      strats.forEach(s=>{
        const o=document.createElement('option');
        // Сервер может вернуть либо массив строк (старый формат), либо массив объектов {name, version}
        if (typeof s === 'string') {
          o.value = s;
          o.textContent = s;
        } else if (s && s.name) {
          o.value = s.name;
          o.textContent = (s.display || s.name) + (s.version ? ` [Zapret ${s.version}]` : '');
        }
        selZ.appendChild(o);
      });
      selZ.value=state.settings.zapret_strategy||'';
    }
  }catch(e){ console.error('zapret list',e); }
}

async function init(){
  let tries=0;
  while(!window.pywebview?.api && tries<30){ await new Promise(r=>setTimeout(r,200)); tries++; }
  if(!window.pywebview?.api){ toast('API не доступен','error',99999); return; }
  $('#appVersion').textContent = await callApi('get_version') || '2.0.0';
  const s = await callApi('get_settings');
  if(s){ try{ state.settings=Object.assign(state.settings, typeof s==='string'?JSON.parse(s):s); }catch(e){} }
  window.onSettingsLoaded(state.settings);
  render();
  populateServers();
  setInterval(async ()=>{ const d=await callApi('get_status'); if(d) window.onStatusPoll(typeof d==='string'?JSON.parse(d):d); }, 2000);
}
let _initDone=false;
async function initSafe(){ if(_initDone) return; _initDone=true; await init(); }
window.addEventListener('pywebviewready', initSafe);
if(document.readyState==='complete' || document.readyState==='interactive') setTimeout(initSafe,100);
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# WebView API
# ---------------------------------------------------------------------------
class Api:
    def __init__(self, window):
        self.window = window
        self.opera_process = None
        self.opera_status = "disconnected"
        self.warp_status  = "disconnected"
        self.hola_process = None
        self.hola_status = "disconnected"
        self.dpi_process = None
        self.dpi_status = "disconnected"
        self.current_zapret_strategy = ""
        self.current_zapret_version = 1
        # какой HTTP-прокси сейчас владеет системным прокси-слотом
        self.active_http_engine = None
        self.current_region = "EU"
        self.current_port = 18080
        self.current_warp_service = None
        self.opera_proxies_cache = {}
        self.settings = {
            "region": "EU", "port": 18080,
            "hola_country": "us", "hola_port": 24080,
            "zapret_strategy": "",
            "zapret_auto_mode": "both",
            "auto_clear_logs": False,
        }
        self._settings_lock = threading.Lock()

        self._warp_lock = threading.Lock()
        self._opera_lock = threading.Lock()
        self._hola_lock = threading.Lock()
        self._dpi_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._load_settings()
        with self._settings_lock:
            self.current_region = self.settings.get("region", "EU")
            self.current_port   = int(self.settings.get("port", 18080))

    def _js(self, cb_name, payload):
        try:
            js = f"typeof {cb_name}==='function' && {cb_name}({safe_json(payload)})"
            self.window.evaluate_js(js)
        except Exception as e:
            log.warning(f"evaluate_js({cb_name}) failed: {e}")

    def _load_settings(self):
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    try:
                        s = json.load(f)
                    except json.JSONDecodeError:
                        log.warning("settings.json пов#реждён, используем значения по умолчанию")
                        s = {}
                s.pop("pingHost", None)
                if s.get("region") not in OPERA_REGIONS:
                    s["region"] = "EU"
                with self._settings_lock:
                    self.settings.update(s)
                log.info(f"Настройки загружены: {self.settings}")
        except Exception as e:
            log.warning(f"Ошибка загрузки настроек: {e}")

    def get_version(self):
        return APP_VERSION

    def get_settings(self):
        with self._settings_lock:
            return safe_json(self.settings.copy())

    def save_settings(self, payload):
        try:
            s = json.loads(payload) if isinstance(payload, str) else payload
            s.pop("pingHost", None)
            if s.get("region") not in OPERA_REGIONS:
                s["region"] = "EU"
            with self._settings_lock:
                self.settings.update(s)
                self.current_region = self.settings.get("region", "EU")
                self.current_port   = int(self.settings.get("port", 18080))
                settings_copy = self.settings.copy()
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            # Атомарная запись: пишем в .tmp, затем os.replace —
            # если процесс упадёт между truncate и dump, старый
            # settings.json останется целым.
            tmp_path = SETTINGS_FILE + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(settings_copy, f, ensure_ascii=False, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass  # не критично
            os.replace(tmp_path, SETTINGS_FILE)
            log.info(f"Настройки сохранены: {self.settings}")
            return {"ok": True}
        except Exception as e:
            log.error(f"save_settings error: {e}")
            return {"ok": False, "error": str(e)}

    def open_logs(self):
        try:
            if not os.path.exists(LOG_FILE):
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write("")
            os.startfile(LOG_FILE)
            return {"ok": True}
        except Exception as e:
            log.error(f"open_logs error: {e}")
            return {"ok": False, "error": str(e)}

    def get_status(self):
        need_cleanup = False
        with self._process_lock:
            proc = self.opera_process
            if proc is not None:
                try:
                    rc = proc.poll()
                    if rc is not None:
                        if self.opera_status == "connected":
                            log.warning(f"opera-proxy завершился с кодом {rc}")
                            self.opera_status = "disconnected"
                            need_cleanup = True
                        self.opera_process = None
                except Exception as e:
                    log.warning(f"poll error: {e}")
        if need_cleanup and self.active_http_engine == "opera":
            self._disable_system_proxy()
            self.active_http_engine = None

        # авто-обнаружение падения hola
        for engine, attr_proc, attr_status in (
            ("hola", "hola_process", "hola_status"),
        ):
            with self._process_lock:
                p = getattr(self, attr_proc)
            if p is not None and p.poll() is not None:
                if getattr(self, attr_status) == "connected":
                    setattr(self, attr_status, "disconnected")
                    if self.active_http_engine == engine:
                        self._disable_system_proxy()
                        self.active_http_engine = None
                with self._process_lock:
                    setattr(self, attr_proc, None)

        with self._process_lock:
            dp = self.dpi_process
        if dp is not None and dp.poll() is not None and self.dpi_status == "connected":
            self.dpi_status = "disconnected"
            with self._process_lock:
                self.dpi_process = None

        warp_info = "Конфиг будет создан в рабочей директории"
        warp_conf = self._warp_conf_path()
        if os.path.exists(warp_conf):
            mtime = datetime.fromtimestamp(os.path.getmtime(warp_conf)).strftime("%d.%m %H:%M")
            warp_info = f"Конфиг: {warp_conf} ({mtime})"

        server_count = 0
        cache = self.opera_proxies_cache.get(self.current_region)
        if cache and (time.time() - cache["timestamp"] < 600):
            server_count = len(cache["servers"])

        return safe_json({
            "opera": self.opera_status,
            "warp":  self.warp_status,
            "hola": self.hola_status,
            "dpi": self.dpi_status,
            "zapret_strategy": self.current_zapret_strategy,
            "active_http": self.active_http_engine,
            "opera_region": self.current_region,
            "opera_port":   self.current_port,
            "warp_info":    warp_info,
            "warp_conf":    os.path.exists(warp_conf),
            "server_count": server_count,
        })

    # ---------- Системный прокси-слот (общий для HTTP-движков) ----------
    def _activate_http_slot(self, engine, bind):
        """Передать системный прокси-слот указанному движку, отключив остальные HTTP-прокси."""
        if self.active_http_engine and self.active_http_engine != engine:
            prev = self.active_http_engine
            log.info(f"Передача прокси-слота: {prev} -> {engine}")
            if prev == "opera" and self.opera_status == "connected":
                self._kill_opera_process()
                self.opera_status = "disconnected"
                self._js("onOperaStatus", {"status": "disconnected", "message": "Opera отключён (активен другой выход)"})
            elif prev == "hola" and self.hola_status == "connected":
                self._kill_hola_process()
                self.hola_status = "disconnected"
                self._js("onHolaStatus", {"status": "disconnected", "message": "Hola отключён (активен другой выход)"})
        self._enable_system_proxy(bind)
        self.active_http_engine = engine

    def _release_http_slot(self, engine):
        if self.active_http_engine == engine:
            self._disable_system_proxy()
            self.active_http_engine = None

    # ---------- Opera Proxy: получение списка серверов ----------
    def _get_opera_proxies(self, region: str) -> list:
        if region not in OPERA_REGIONS:
            log.warning(f"Регион {region} не поддерживается")
            return []

        if region in self.opera_proxies_cache:
            cache = self.opera_proxies_cache[region]
            if time.time() - cache["timestamp"] < 600:
                return cache["servers"]

        exe = get_resource_path(OPERA_EXE)
        if not os.path.exists(exe):
            log.warning(f"{OPERA_EXE} не найден")
            return []

        try:
            log.info(f"Получение списка серверов для региона {region}")

            proc = subprocess.Popen(
                [exe, "-country", region, "-list-proxies"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            stderr_data = []
            stdout_data = []

            def read_stderr():
                try:
                    for line in proc.stderr:
                        decoded = decode_output(line)
                        stderr_data.append(decoded)
                        if "801" in decoded or "CSV fallback" in decoded:
                            log.warning(f"Обнаружен код 801 для {region}, прерываем")
                            try:
                                proc.terminate()
                            except Exception:
                                pass
                            return
                except Exception:
                    pass

            def read_stdout():
                try:
                    for line in proc.stdout:
                        stdout_data.append(decode_output(line))
                except Exception:
                    pass

            t_err = threading.Thread(target=read_stderr, daemon=True)
            t_out = threading.Thread(target=read_stdout, daemon=True)
            t_err.start()
            t_out.start()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                log.warning("Таймаут -list-proxies, прерываем")
                try:
                    proc.terminate()
                except Exception:
                    pass
            t_out.join(timeout=2)
            t_err.join(timeout=2)

            raw = "".join(stdout_data)
            servers = []
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.lower().startswith("host"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                host = ip = port = None
                if len(parts) >= 3:
                    host, ip, port = parts[0], parts[1], parts[2]
                elif len(parts) == 2:
                    host, port = parts[0], parts[1]
                    ip = host
                elif len(parts) == 1 and ":" in parts[0]:
                    host, port = parts[0].rsplit(":", 1)
                    ip = host
                if host:
                    try:
                        port_i = int(re.sub(r"[^0-9]", "", str(port))) if port else 443
                    except ValueError:
                        port_i = 443
                    servers.append({"host": host, "ip": ip or host, "port": port_i})

            if servers:
                self.opera_proxies_cache[region] = {"servers": servers, "timestamp": time.time()}
                log.info(f"Получено {len(servers)} серверов для {region}")
            else:
                log.warning(f"Серверы для {region} не получены. stderr: {''.join(stderr_data)[:200]}")
            return servers
        except Exception as e:
            log.exception(f"Ошибка получения списка серверов: {e}")
            return []

    def _port_open(self, host, port):
        try:
            with socket.create_connection((host, int(port)), timeout=1.5):
                return True
        except Exception:
            return False

    # ---------- Opera Proxy: подключение ----------
    def start_connect(self, region=None, port=None):
        threading.Thread(target=self._do_connect_opera, args=(region, port), daemon=True).start()
        return {"ok": True}

    def _do_connect_opera(self, region=None, port=None):
        if not self._opera_lock.acquire(timeout=3):
            self._js("onOperaStatus", {"status": self.opera_status, "message": "Дождитесь завершения операции"})
            return
        try:
            with self._settings_lock:
                region = region or self.settings.get("region", "EU")
                port = int(port or self.settings.get("port", 18080))
            if region not in OPERA_REGIONS:
                region = "EU"
            self.current_region = region
            self.current_port = port

            exe = get_resource_path(OPERA_EXE)
            if not os.path.exists(exe):
                raise RuntimeError(f"{OPERA_EXE} не найден. Положите файл рядом с программой.")

            self.opera_status = "connecting"
            self._js("onOperaStatus", {"status": "connecting", "message": f"Подключение Opera ({OPERA_REGIONS[region]})…"})

            servers = self._get_opera_proxies(region)
            server_count = len(servers)

            self._kill_opera_process()
            time.sleep(0.3)

            bind = f"127.0.0.1:{port}"
            if self._port_open("127.0.0.1", port):
                raise RuntimeError(f"Порт {port} уже занят. Смените порт в настройках.")

            log.info(f"Запуск opera-proxy: {region} -> {bind}")
            proc = subprocess.Popen(
                [exe, "-country", region, "-bind-address", bind],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            with self._process_lock:
                self.opera_process = proc

            ready = False
            last_err = ""
            for _ in range(300):
                time.sleep(0.2)
                with self._process_lock:
                    cur = self.opera_process
                if cur is None or cur is not proc:
                    log.info("opera-proxy процесс был заменён/остановлен")
                    return
                rc = cur.poll()
                if rc is not None:
                    try:
                        _, err = cur.communicate(timeout=2)
                        last_err = decode_output(err).strip()
                    except Exception:
                        last_err = ""
                    raise RuntimeError(f"opera-proxy завершился (код {rc}). {last_err[:200]}")
                if self._port_open("127.0.0.1", port):
                    ready = True
                    break
            if not ready:
                raise RuntimeError("Таймаут ожидания порта Opera (60 c)")

            self._activate_http_slot("opera", bind)
            self.opera_status = "connected"
            with self._settings_lock:
                self.settings["region"] = region
                self.settings["port"] = port
            self._js("onOperaStatus", {
                "status": "connected",
                "message": f"Opera Proxy активен ({OPERA_REGIONS[region]})",
                "server_count": server_count,
            })
        except Exception as e:
            log.exception("Opera connect")
            self.opera_status = "error"
            self._kill_opera_process()
            if self.active_http_engine in (None, "opera"):
                self._disable_system_proxy()
                if self.active_http_engine == "opera":
                    self.active_http_engine = None
            self._js("onOperaStatus", {"status": "error", "message": f"Ошибка: {e}"})
        finally:
            self._opera_lock.release()

    def start_disconnect(self):
        threading.Thread(target=self._do_disconnect_opera, daemon=True).start()
        return {"ok": True}

    def _do_disconnect_opera(self):
        if not self._opera_lock.acquire(timeout=5):
            self._js("onOperaStatus", {"status": self.opera_status, "message": "Дождитесь завершения операции"})
            return
        try:
            self._kill_opera_process()
            self._release_http_slot("opera")
            self.opera_status = "disconnected"
            self._js("onOperaStatus", {"status": "disconnected", "message": "Opera Proxy отключён"})
        except Exception as e:
            log.exception("Opera disconnect")
            self._js("onOperaStatus", {"status": "error", "message": f"Ошибка: {e}"})
        finally:
            self._opera_lock.release()

    def _kill_opera_process(self):
        with self._process_lock:
            proc = self.opera_process
            self.opera_process = None
        if proc is not None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception as e:
                log.warning(f"Ошибка завершения opera-proxy: {e}")
        try:
            subprocess.run(["taskkill", "/F", "/IM", OPERA_EXE],
                           capture_output=True, timeout=5,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass

    # ---------- Системный прокси Windows ----------
    def _enable_system_proxy(self, bind):
        if winreg is None:
            log.warning("winreg недоступен")
            return
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROXY_REG_PATH, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, bind)
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "localhost;127.0.0.1;<local>")
            self._notify_ie_settings_changed()
            log.info(f"Системный прокси включён: {bind}")
        except Exception as e:
            log.error(f"Ошибка включения системного прокси: {e}")
            raise

    def _disable_system_proxy(self):
        if winreg is None:
            return
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROXY_REG_PATH, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            self._notify_ie_settings_changed()
            log.info("Системный прокси выключен")
        except Exception as e:
            log.warning(f"Ошибка выключения системного прокси: {e}")

    def _notify_ie_settings_changed(self):
        try:
            INTERNET_OPTION_SETTINGS_CHANGED = 39
            INTERNET_OPTION_REFRESH = 37
            wininet = ctypes.windll.wininet
            wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
            wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
        except Exception as e:
            log.debug(f"InternetSetOption failed: {e}")
    # ---------- WARP (Cloudflare через AmneziaWG) ----------
    def _warp_conf_path(self):
        base = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()), "VPNClient")
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            pass
        return os.path.join(base, WARP_CONF_NAME)

    def _download_file(self, url, dest, label="AmneziaWG", min_bytes=1_000_000, retries=3):
        """Надёжная загрузка: User-Agent, таймаут, потоковое чтение по чанкам,
        прогресс по шагам, докачка во временный .part, проверка размера и
        MSI-сигнатуры, повтор при сетевых сбоях."""
        last_err = None
        for attempt in range(1, retries + 1):
            tmp = dest + ".part"
            try:
                if attempt > 1:
                    self._js("onWarpStatus", {"status": "connecting",
                                              "message": f"Повтор загрузки {label} ({attempt}/{retries})…"})
                req = urllib.request.Request(url, headers={"User-Agent": "VPNClient/2.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    status = getattr(resp, "status", 200) or 200
                    if status >= 400:
                        raise RuntimeError(f"HTTP {status}")
                    total = int(resp.headers.get("Content-Length") or 0)
                    done = 0
                    last_pct = -5
                    last_mb = 0
                    with open(tmp, "wb") as f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                            done += len(chunk)
                            if total > 0:
                                pct = int(done * 100 / total)
                                if pct >= last_pct + 5:
                                    last_pct = pct
                                    self._js("onWarpStatus", {"status": "connecting",
                                              "message": f"Загрузка {label}… {pct}%"})
                            elif done - last_mb >= 1048576:
                                last_mb = done
                                self._js("onWarpStatus", {"status": "connecting",
                                          "message": f"Загрузка {label}… {done / 1048576:.1f} МБ"})
                size = os.path.getsize(tmp)
                if size < min_bytes:
                    raise RuntimeError(f"файл слишком мал ({size} байт), вероятно ошибка сервера")
                if dest.lower().endswith(".msi"):
                    with open(tmp, "rb") as f:
                        sig = f.read(4)
                    if sig != b"\xd0\xcf\x11\xe0":
                        raise RuntimeError("скачанный файл не является корректным MSI")
                os.replace(tmp, dest)
                log.info(f"Загрузка завершена: {dest} ({size} байт)")
                return dest
            except Exception as e:
                last_err = e
                log.warning(f"Попытка {attempt}/{retries} загрузки {url} не удалась: {e}")
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass
                if attempt < retries:
                    time.sleep(2.0)
        raise RuntimeError(f"Не удалось скачать {label}: {last_err}")

    def _ensure_amnezia_wg(self):
        path = find_amnezia_exe()
        if path and os.path.exists(path):
            return path
        self._js("onWarpStatus", {"status": "connecting", "message": "AmneziaWG не найден. Начинаем установку..."})
        msi_url = AMNEZIAWG_MSI_URL
        msi_path = os.path.join(tempfile.gettempdir(), os.path.basename(msi_url))
        self._download_file(msi_url, msi_path)
        self._js("onWarpStatus", {"status": "connecting", "message": "Установка AmneziaWG..."})
        log.info(f"Установка AmneziaWG: msiexec /quiet /i {msi_path}")
        msi_log = os.path.join(tempfile.gettempdir(), "amneziawg_install.log")
        r = subprocess.run(
            ["msiexec", "/quiet", "/norestart", "/i", msi_path, "DO_NOT_LAUNCH=1", "/l*v", msi_log],
            capture_output=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        log.info(f"msiexec: rc={r.returncode}")
        if r.returncode not in (0, 1641, 3010):
            raise RuntimeError(
                f"Ошибка установки AmneziaWG (код {r.returncode}). "
                f"Установите вручную: github.com/amnezia-vpn/amneziawg-windows-client"
            )
        path = find_amnezia_exe()
        if path:
            log.info(f"Установка manager-сервиса AmneziaWG: {path} /installmanagerservice")
            subprocess.run(
                [path, "/installmanagerservice"],
                capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        try:
            os.remove(msi_path)
        except Exception:
            pass
        path = find_amnezia_exe()
        if path and os.path.exists(path):
            self._js("onWarpStatus", {"status": "connecting", "message": "AmneziaWG успешно установлен"})
            global AMNEZIA_EXE
            AMNEZIA_EXE = path
            return path
        raise RuntimeError("AmneziaWG установлен, но amneziawg.exe не найден. Перезапустите приложение.")

    def start_generate_warp(self):
        threading.Thread(target=self._do_generate_warp, daemon=True).start()
        return {"ok": True}

    def _do_generate_warp(self):
        if not self._warp_lock.acquire(blocking=True, timeout=3):
            self._js("onWarpStatus", {"status": self.warp_status, "message": "Дождитесь завершения текущей операции"})
            return
        try:
            exe = get_resource_path(WARP_GEN_EXE)
            if not os.path.exists(exe):
                self._js("onWarpStatus", {"status": "error", "message": f"Файл {WARP_GEN_EXE} не найден."})
                return
            out = self._warp_conf_path()
            log.info(f"Генерация WARP конфига: {exe} -> {out}")
            self._js("onWarpStatus", {"status": "connecting", "message": "Генерация конфига WARP..."})
            result = subprocess.run(
                [exe, "-o", out, "--transport", "none"],
                capture_output=True, timeout=90,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            stdout = decode_output(result.stdout)
            stderr = decode_output(result.stderr)
            log.info(f"warp-awg-gen stdout: {stdout}")
            if stderr:
                log.info(f"warp-awg-gen stderr: {stderr}")
            if result.returncode != 0:
                raise RuntimeError(stderr.strip() or stdout.strip() or f"exit code {result.returncode}")
            if not os.path.exists(out) or os.path.getsize(out) < 50:
                raise RuntimeError("Конфиг не создан или пустой")
            log.info(f"WARP конфиг создан: {out} ({os.path.getsize(out)} байт)")
            self._js("onWarpStatus", {
                "status": self.warp_status,
                "message": "Конфиг WARP успешно сгенерирован",
                "info": f"Конфиг: {out}",
            })
        except Exception as e:
            log.exception("Ошибка генерации WARP")
            self._js("onWarpStatus", {"status": "error", "message": f"Ошибка генерации WARP: {e}"})
        finally:
            self._warp_lock.release()

    def start_connect_warp(self):
        threading.Thread(target=self._do_connect_warp, daemon=True).start()
        return {"ok": True}

    def _do_connect_warp(self):
        if not self._warp_lock.acquire(blocking=True, timeout=3):
            self._js("onWarpStatus", {"status": self.warp_status, "message": "Дождитесь завершения текущей операции"})
            return
        try:
            if not is_admin():
                self._js("onWarpStatus", {"status": "error", "message": "Требуются права администратора."})
                return
            amnezia_path = self._ensure_amnezia_wg()
            if not amnezia_path:
                return
            conf = self._warp_conf_path()
            if not os.path.exists(conf):
                self._js("onWarpStatus", {"status": "error", "message": "Сначала сгенерируйте конфиг WARP в настройках"})
                return
            self.warp_status = "connecting"
            self._js("onWarpStatus", {"status": "connecting", "message": "Устанавливаем WARP-туннель..."})
            existing_service = self._find_amnezia_service()
            if existing_service:
                log.info(f"Сервис {existing_service} уже установлен, просто запускаем")
                new_service = existing_service
                self.current_warp_service = new_service
            else:
                self._force_cleanup_amnezia_services()
                time.sleep(2.0)
                log.info(f"amneziawg.exe /installtunnelservice {conf}")
                r = subprocess.run(
                    [amnezia_path, "/installtunnelservice", conf],
                    capture_output=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                stdout = decode_output(r.stdout)
                stderr = decode_output(r.stderr)
                log.info(f"installtunnelservice: rc={r.returncode} stdout='{stdout}' stderr='{stderr}'")
                if r.returncode != 0:
                    raise RuntimeError(stderr.strip() or stdout.strip() or f"exit {r.returncode}")
                new_service = None
                for attempt in range(15):
                    time.sleep(0.5)
                    found = self._find_amnezia_service()
                    if found:
                        new_service = found
                        log.info(f"Сервис найден на попытке {attempt}: {new_service}")
                        break
                if not new_service:
                    conf_name = os.path.splitext(os.path.basename(conf))[0]
                    new_service = f"AmneziaWGTunnel${conf_name}"
                    log.warning(f"Сервис не найден, используем предсказанное имя: {new_service}")
                self.current_warp_service = new_service
            q_check = sc_run("query", self.current_warp_service, timeout=10)
            already_running = bool(re.search(r"(?:STATE|СОСТОЯНИЕ)\s*:\s*4\b", q_check.stdout_decoded, re.IGNORECASE))
            if already_running:
                log.info(f"Сервис {self.current_warp_service} уже RUNNING")
            else:
                r2 = sc_run("start", self.current_warp_service, timeout=15)
                log.info(f"sc start: rc={r2.returncode} out='{r2.stdout_decoded.strip()}'")
                if r2.returncode != 0 and r2.returncode != 1056:
                    err_msg = (r2.stderr_decoded or r2.stdout_decoded).strip()
                    raise RuntimeError(f"sc start failed (rc={r2.returncode}): {err_msg}")
            running = False
            for i in range(60):
                time.sleep(0.2 if i < 5 else 0.5)
                q = sc_run("query", self.current_warp_service, timeout=10)
                output = q.stdout_decoded
                if re.search(r"(?:STATE|СОСТОЯНИЕ)\s*:\s*4\b", output, re.IGNORECASE):
                    running = True
                    log.info(f"Сервис RUNNING на попытке {i}")
                    break
                if re.search(r"(?:STATE|СОСТОЯНИЕ)\s*:\s*1\b", output, re.IGNORECASE):
                    m = re.search(r"(?:WIN32_EXIT_CODE|КОД_ВЫХОДА_WIN32|Код_выхода_Win32)\s*:\s*(\d+)", output, re.IGNORECASE)
                    code = m.group(1) if m else "?"
                    ev_log = self._read_event_log()
                    raise RuntimeError(f"Сервис остановился (код {code}). Event Log: {ev_log}")
            if not running:
                raise RuntimeError(f"Сервис {self.current_warp_service} не перешёл в RUNNING за 30 секунд")
            self.warp_status = "connected"
            self._js("onWarpStatus", {"status": "connected", "message": "WARP туннель активен"})
            log.info(f"WARP подключён через сервис {self.current_warp_service}")
        except Exception as e:
            log.exception("Ошибка подключения WARP")
            self._force_cleanup_amnezia_services()
            self.warp_status = "error"
            self._js("onWarpStatus", {"status": "error", "message": f"Ошибка WARP: {e}"})
        finally:
            self._warp_lock.release()

    def start_disconnect_warp(self):
        threading.Thread(target=self._do_disconnect_warp, daemon=True).start()
        return {"ok": True}

    def _do_disconnect_warp(self):
        if not self._warp_lock.acquire(blocking=True, timeout=3):
            self._js("onWarpStatus", {"status": self.warp_status, "message": "Дождитесь завершения текущей операции"})
            return
        try:
            self._force_cleanup_amnezia_services()
            self.warp_status = "disconnected"
            self._js("onWarpStatus", {"status": "disconnected", "message": "WARP отключён"})
            log.info("WARP отключён")
        except Exception as e:
            log.exception("Ошибка отключения WARP")
            self._js("onWarpStatus", {"status": "error", "message": f"Ошибка: {e}"})
        finally:
            self._warp_lock.release()

    def _read_event_log(self):
        try:
            ps = (
                "Get-WinEvent -FilterHashtable @{LogName='Application';ProviderName='AmneziaWG'} "
                "-MaxEvents 5 -ErrorAction SilentlyContinue | "
                "Select-Object -ExpandProperty Message"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            msg = decode_output(r.stdout).strip()
            return msg[:500] if msg else "(пусто)"
        except Exception as e:
            return f"(не удалось прочитать лог: {e})"

    def _find_amnezia_service(self):
        try:
            r = sc_run("queryex", "type=", "service", "state=", "all", timeout=10)
            out = r.stdout_decoded
            for m in re.finditer(r"(?:SERVICE_NAME|ИМЯ_СЛУЖБЫ)\s*:\s*(\S+)", out, re.IGNORECASE):
                name = m.group(1).strip()
                if name.startswith("AmneziaWGTunnel$"):
                    return name
        except Exception as e:
            log.debug(f"_find_amnezia_service failed: {e}")
        return None

    def _force_cleanup_amnezia_services(self):
        services = []
        try:
            r = sc_run("queryex", "type=", "service", "state=", "all", timeout=10)
            out = r.stdout_decoded
            for m in re.finditer(r"(?:SERVICE_NAME|ИМЯ_СЛУЖБЫ)\s*:\s*(\S+)", out, re.IGNORECASE):
                name = m.group(1).strip()
                if name.startswith("AmneziaWGTunnel$"):
                    services.append(name)
        except Exception as e:
            log.debug(f"enumerate services failed: {e}")
        for exe_name in ("amneziawg-go.exe", "amneziawg.exe"):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", exe_name],
                    capture_output=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass
        for svc in services:
            try:
                sc_run("stop", svc, timeout=15)
                time.sleep(0.5)
                sc_run("delete", svc, timeout=15)
                log.info(f"Сервис удалён: {svc}")
            except Exception as e:
                log.debug(f"cleanup {svc} failed: {e}")
        for svc in services:
            try:
                q = sc_run("query", svc, timeout=5)
                if re.search(r"(?:1060|не установлен|does not exist)", q.stdout_decoded, re.IGNORECASE):
                    log.info(f"Подтверждено удаление: {svc}")
            except Exception:
                pass
        self.current_warp_service = None

    # ---------- Общий хелпер: ожидание открытия локального порта ----------
    def _wait_local_port(self, host, port, proc, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc is not None and proc.poll() is not None:
                return False
            try:
                with socket.create_connection((host, int(port)), timeout=1):
                    return True
            except OSError:
                time.sleep(0.4)
        return False

    # ---------- Hola Proxy ----------
    def start_connect_hola(self):
        threading.Thread(target=self._do_connect_hola, daemon=True).start()
        return {"ok": True}

    def _do_connect_hola(self):
        if not self._hola_lock.acquire(blocking=True, timeout=3):
            self._js("onHolaStatus", {"status": self.hola_status, "message": "Дождитесь завершения текущей операции"})
            return
        try:
            exe = get_resource_path(HOLA_EXE)
            if not os.path.exists(exe):
                self._js("onHolaStatus", {"status": "error", "message": f"Файл {HOLA_EXE} не найден."})
                return
            with self._settings_lock:
                port = int(self.settings.get("hola_port", 24080))
                country = (self.settings.get("hola_country", "us") or "us").strip().lower()
            bind = f"127.0.0.1:{port}"
            self.hola_status = "connecting"
            self._js("onHolaStatus", {"status": "connecting", "message": "Запуск Hola Proxy..."})
            self._kill_hola_process()
            cmd = [exe, "-country", country, "-bind-address", bind]
            log.info(f"Запуск Hola: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            with self._process_lock:
                self.hola_process = proc
            if not self._wait_local_port("127.0.0.1", port, proc, timeout=60):
                err = ""
                if proc.poll() is not None:
                    try:
                        err = decode_output(proc.stderr.read())
                    except Exception:
                        err = ""
                self._kill_hola_process()
                raise RuntimeError(err.strip()[:300] or "прокси не открыл порт за 60с")
            self._activate_http_slot("hola", bind)
            self.hola_status = "connected"
            self._js("onHolaStatus", {"status": "connected", "message": f"Hola Proxy подключён ({country.upper()})"})
            log.info(f"Hola подключён на {bind} ({country})")
        except Exception as e:
            log.exception("Ошибка подключения Hola")
            self.hola_status = "error"
            self._js("onHolaStatus", {"status": "error", "message": f"Ошибка Hola: {e}"})
        finally:
            self._hola_lock.release()

    def start_disconnect_hola(self):
        threading.Thread(target=self._do_disconnect_hola, daemon=True).start()
        return {"ok": True}

    def _do_disconnect_hola(self):
        if not self._hola_lock.acquire(blocking=True, timeout=3):
            self._js("onHolaStatus", {"status": self.hola_status, "message": "Дождитесь завершения текущей операции"})
            return
        try:
            self._kill_hola_process()
            self._release_http_slot("hola")
            self.hola_status = "disconnected"
            self._js("onHolaStatus", {"status": "disconnected", "message": "Hola отключён"})
            log.info("Hola отключён")
        except Exception as e:
            log.exception("Ошибка отключения Hola")
            self._js("onHolaStatus", {"status": "error", "message": f"Ошибка: {e}"})
        finally:
            self._hola_lock.release()

    def _kill_hola_process(self):
        with self._process_lock:
            proc = self.hola_process
            self.hola_process = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", HOLA_EXE],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass

    def _get_hola_proxies(self, country: str) -> list:
        exe = get_resource_path(HOLA_EXE)
        if not os.path.exists(exe):
            return []
        try:
            r = subprocess.run(
                [exe, "-country", country, "-list-proxies"],
                capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            out = decode_output(r.stdout) + "\n" + decode_output(r.stderr)
        except Exception as e:
            log.debug(f"hola -list-proxies failed: {e}")
            return []
        ip_re = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
        servers, seen = [], set()
        for line in out.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("host"):
                continue
            m = ip_re.search(line)
            if not m:
                continue
            ip = m.group(1)
            if ip in seen:
                continue
            seen.add(ip)
            port = 443
            pm = re.search(re.escape(ip) + r"[:, \t]+(\d{2,5})", line)
            if pm:
                try:
                    port = int(pm.group(1))
                except ValueError:
                    port = 443
            host = line.split(",")[0].strip()
            if (not host) or (" " in host) or ("/" in host):
                host = ip
            servers.append({"host": host, "ip": ip, "port": port})
        return servers

    # ---------- Обход DPI (Zapret) ----------
    def _zapret_dir(self, version=1):
        """Корневая папка Zapret: для v1 — zapret/, для v2 — zapret/zapret2/."""
        base = self._zapret_root()
        if version == 2:
            return os.path.join(base, ZAPRET2_DIR)
        return base

    def _zapret_root(self):
        """Корневая папка zapret (без учёта версии)."""
        candidates = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, ZAPRET_DIR))
        candidates.append(os.path.join(os.path.abspath("."), ZAPRET_DIR))
        if getattr(sys, "frozen", False):
            candidates.append(os.path.join(os.path.dirname(sys.executable), ZAPRET_DIR))
        for c in candidates:
            if os.path.isdir(c):
                return c
        return os.path.join(os.path.abspath("."), ZAPRET_DIR)

    def _zapret_bin_dir(self, version=1):
        base = self._zapret_dir(version)
        b = os.path.join(base, "bin")
        return b if os.path.isdir(b) else base

    def _zapret_lists_dir(self, version=1):
        base = self._zapret_dir(version)
        l = os.path.join(base, "lists")
        return l if os.path.isdir(l) else base

    def _detect_strategy_version(self, bat_path):
        """Определяет версию Zapret по маркеру :: ZAPRET_VERSION=N в bat-файле.
        Если маркер не найден — пытается угадать по расположению (zapret2/ -> v2)."""
        try:
            with open(bat_path, "rb") as f:
                head = f.read(2048)
            try:
                text = head.decode("utf-8", errors="replace")
            except Exception:
                text = ""
            m = re.search(r"ZAPRET_VERSION\s*=\s*(\d+)", text)
            if m:
                v = int(m.group(1))
                if v in (1, 2):
                    return v
        except Exception:
            pass
        # Фоллбэк: если файл лежит внутри zapret2/ — это v2
        try:
            root = self._zapret_root()
            rel = os.path.relpath(bat_path, root)
            if rel.lower().startswith(ZAPRET2_DIR + os.sep):
                return 2
        except Exception:
            pass
        return 1

    def _find_winws_exe(self, version=1):
        bin_dir = self._zapret_bin_dir(version)
        winws_name = ZAPRET2_WINWS if version == 2 else ZAPRET_WINWS
        c = os.path.join(bin_dir, winws_name)
        if os.path.exists(c):
            return c
        base = self._zapret_dir(version)
        if os.path.isdir(base):
            for root, _dirs, files in os.walk(base):
                if winws_name in files:
                    return os.path.join(root, winws_name)
        return ""

    def _list_strategy_files(self):
        """Возвращает список путей ко всем .bat-стратегиям (v1 + v2)."""
        result = []
        for version in (1, 2):
            base = self._zapret_dir(version)
            if not os.path.isdir(base):
                continue
            try:
                names = os.listdir(base)
            except Exception:
                continue
            for name in names:
                low = name.lower()
                if not low.endswith(".bat"):
                    continue
                if low.startswith("service"):
                    continue
                result.append((version, os.path.join(base, name)))
        # Сортировка: сначала по версии (1 раньше 2), потом по имени
        result.sort(key=lambda x: (x[0], os.path.basename(x[1]).lower()))
        return result

    def list_zapret_strategies(self):
        out = []
        for version, p in self._list_strategy_files():
            name = os.path.splitext(os.path.basename(p))[0]
            out.append({"name": name, "version": version,
                        "display": f"{name} (Zapret {version})"})
        return safe_json(out)

    def _tokenize_args(self, text):
        tokens = []
        cur = ""
        quote = None
        for ch in text:
            if quote:
                if ch == quote:
                    quote = None
                else:
                    cur += ch
            elif ch in ('"', "'"):
                quote = ch
            elif ch.isspace():
                if cur:
                    tokens.append(cur)
                    cur = ""
            else:
                cur += ch
        if cur:
            tokens.append(cur)
        return tokens

    def _parse_strategy(self, bat_path, version=None):
        if version is None:
            version = self._detect_strategy_version(bat_path)
        bin_dir = self._zapret_bin_dir(version)
        base = self._zapret_dir(version)
        lists_dir = self._zapret_lists_dir(version)
        os.makedirs(lists_dir, exist_ok=True)
        for _name, _content in (
            ("ipset-exclude-user.txt", "203.0.113.113/32\n"),
            ("list-general-user.txt", "domain.example.abc\n"),
            ("list-exclude-user.txt", "domain.example.abc\n"),
        ):
            _p = os.path.join(lists_dir, _name)
            if not os.path.exists(_p):
                try:
                    with open(_p, "w", encoding="utf-8") as _f:
                        _f.write(_content)
                except Exception:
                    pass
        try:
            with open(bat_path, "rb") as f:
                raw = f.read()
        except Exception as e:
            log.warning(f"Не удалось прочитать стратегию {bat_path}: {e}")
            return []
        content = decode_output(raw)
        lines = content.splitlines()
        dp0 = base + os.sep

        # Собираем переменные из строк "set" (set "VAR=val" или set VAR=val)
        variables = {
            "BIN": bin_dir + os.sep,
            "LISTS": lists_dir + os.sep,
            # zapret: service.bat при выключенном игровом фильтре подставляет
            # порт-заглушку 12. Без этого %GameFilter*% вырезаются в ""
            # -> висячие запятые и пустые --filter-tcp=/--filter-udp=
            # -> winws: "bad value for --wf-tcp".
            "GameFilter": "12",
            "GameFilterTCP": "12",
            "GameFilterUDP": "12",
        }
        set_re = re.compile(r'^\s*set\s+"?([A-Za-z0-9_]+)=(.*?)"?\s*$', re.IGNORECASE)
        for line in lines:
            m = set_re.match(line)
            if m:
                variables[m.group(1)] = m.group(2)

        def expand(s):
            s = s.replace("%~dp0", dp0)
            for _ in range(6):
                changed = False
                for k, v in variables.items():
                    token = "%" + k + "%"
                    if token in s:
                        s = s.replace(token, v)
                        changed = True
                if "%~dp0" in s:
                    s = s.replace("%~dp0", dp0)
                    changed = True
                if not changed:
                    break
            return s

        # Раскрываем значения самих переменных (могут ссылаться на %~dp0 / друг друга)
        for k in list(variables.keys()):
            variables[k] = expand(variables[k])

        # Находим команду запуска winws / winws2
        # v1-стратегии используют "^" для переноса строк cmd
        # v2-стратегии используют "\" (для start) и "^" (для остальных строк)
        def _is_continuation(line):
            s = line.rstrip()
            return s.endswith("^") or s.endswith("\\")

        winws_line = ""
        collecting = False
        winws_token = ""
        for line in lines:
            low = line.lower()
            if not collecting:
                # Поддерживаем как winws.exe (v1), так и winws2.exe (v2)
                if "winws2.exe" in low:
                    winws_token = "winws2.exe"
                    winws_line = line
                    collecting = True
                elif "winws.exe" in low:
                    winws_token = "winws.exe"
                    winws_line = line
                    collecting = True
                if collecting and not _is_continuation(line):
                    break
            else:
                winws_line += " " + line
                if not _is_continuation(line):
                    break
        if not winws_token:
            log.warning(f"В {bat_path} не найден winws.exe/winws2.exe")
            return []
        # Сначала снимаем batch-escape: `^<спецсимвол>` -> `<спецсимвол>`.
        # В .cmd/.bat `^` это escape-символ. В исходных AntiZapret-конфигах
        # есть `^!` (подавить delayed expansion), `^^` (литерал `^`) и т.п.
        # Если этого не сделать, `.replace("^", " ")` ниже разорвёт
        # `--dpi-desync-fake-tls=^!` на два токена `--dpi-desync-fake-tls=`
        # и `!`, и winws попытается прочитать `!` как файл -> "could not read".
        winws_line = re.sub(r'\^([!"^|&<>()%])', r'\1', winws_line)
        # Затем оставшиеся `^` (это переносы строк `^<EOL>`) -> пробел,
        # как и `\` (перенос строк в v2-стратегиях).
        winws_line = winws_line.replace("^", " ").replace("\\", " ")
        idx = winws_line.lower().find(winws_token)
        after = winws_line[idx + len(winws_token):]
        after = after.strip()
        if after.startswith('"'):
            after = after[1:]  # закрывающая кавычка от "%BIN%winws.exe"
        after = expand(after)
        # Удаляем оставшиеся нераскрытые переменные, чтобы не ломать аргументы
        after = re.sub(r"%[A-Za-z0-9_~]+%", "", after)
        # Удаляем метки `--name=...` (это НЕ опция winws, а подпись блока
        # из исходных .txt youtubediscord: "--name=Discord UDP", "--name=Игровые
        # UDP порты" и т.п.). winws не знает такой опции и падает в help.
        # Значение может быть в кавычках или без, может содержать пробелы/скобки
        # и кириллицу, поэтому режем жадно до следующего ` --` или конца строки.
        after = re.sub(r'--name=(?:"[^"]*"|[^\s]+(?:\s+[^\s"]+)*?)(?=\s+--|\s*$)', '', after)
        # Сжимаем множественные пробелы, оставшиеся после удаления метки.
        after = re.sub(r'\s{2,}', ' ', after)
        return self._tokenize_args(after)

    def _winws_required_files_ok(self, version=1):
        bin_dir = self._zapret_bin_dir(version)
        missing = []
        try:
            present = {f.lower() for f in os.listdir(bin_dir)}
        except Exception:
            present = set()
        for fn in ("WinDivert.dll", "WinDivert64.sys"):
            if fn.lower() not in present:
                missing.append(fn)
        return missing

    def _ensure_zapret_user_lists(self, version=1):
        try:
            lists_dir = self._zapret_lists_dir(version)
            os.makedirs(lists_dir, exist_ok=True)
            defaults = {
                "ipset-exclude-user.txt": "203.0.113.113/32\n",
                "list-general-user.txt": "domain.example.abc\n",
                "list-exclude-user.txt": "domain.example.abc\n",
            }
            for name, content in defaults.items():
                path = os.path.join(lists_dir, name)
                if not os.path.exists(path):
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(content)
        except Exception as e:
            log.warning("Не удалось создать пользовательские списки zapret: %s", e)

    def _cleanup_windivert(self):
        # Удаляем возможно зависшую службу WinDivert от предыдущего запуска
        for svc in ("windivert", "WinDivert1.4"):
            for action in ("stop", "delete"):
                try:
                    subprocess.run(
                        ["sc", action, svc],
                        capture_output=True, timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                except Exception:
                    pass

    def _register_windivert(self, version=1):
        """Перерегистрирует службу WinDivert на наш путь к .sys.

        Без этого winws падает с "cannot find the file specified", если
        ранее сервис был зарегистрирован на другой путь (например
        D:\\zapret\\bin\\WinDivert64.sys от другой копии zapret).
        Требует прав администратора (sc create требует admin).

        WinDivert64.sys поставляется с истёкшим (2023-05-26) сертификатом
        Sectigo. На Windows 11 + Secure Boot ZaperSetup-овая WinDivert.dll
        (45568 байт) отказывается работать. Workaround: используем
        WinDivert.dll (47616 байт) с Flowseal/zapret-discord-youtube —
        она имеет иной путь проверки подписи и работает.
        """
        sys_path = os.path.join(self._zapret_bin_dir(version), "WinDivert64.sys")
        if not os.path.exists(sys_path):
            return False
        # Если сервис уже указывает на наш путь — не трогаем
        try:
            out = subprocess.run(
                ["sc", "qc", "windivert"],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout.decode("utf-8", errors="replace")
            if sys_path.lower() in out.lower():
                return True  # уже наш
        except Exception:
            pass
        # Удаляем старый (вместе с DeleteFlag) и создаём заново
        for action in ("stop", "delete"):
            try:
                subprocess.run(
                    ["sc", action, "windivert"],
                    capture_output=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass
        # create windivert binPath= "\??\D:\...\WinDivert64.sys" type= kernel start= demand
        try:
            r = subprocess.run(
                ["sc", "create", "windivert",
                 "binPath=", f"\\??\\{sys_path}",
                 "type=", "kernel",
                 "start=", "demand",
                 "displayname=", "WinDivert"],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _launch_winws(self, args, version=1):
        bin_dir = self._zapret_bin_dir(version)
        exe = self._find_winws_exe(version)
        self._winws_log_path = os.path.join(tempfile.gettempdir(), "winws_out.log")
        try:
            out_fh = open(self._winws_log_path, "wb")
        except Exception:
            out_fh = subprocess.DEVNULL
        self._winws_log_fh = out_fh
        exe_name = os.path.basename(exe) if exe else "winws.exe"
        log.info(f"Запуск {exe_name} (v{version}): {exe}")
        log.info(f"  cwd={bin_dir}")
        log.info(f"  args={' '.join(args)}")
        proc = subprocess.Popen(
            [exe] + args, cwd=bin_dir,
            stdout=out_fh, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return proc

    def _winws_exit_reason(self):
        fh = getattr(self, "_winws_log_fh", None)
        if fh is not None and fh is not subprocess.DEVNULL:
            try:
                fh.close()
            except Exception:
                pass
        try:
            path = getattr(self, "_winws_log_path", "")
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    txt = decode_output(f.read()).strip()
                if txt:
                    return txt[-500:]
        except Exception:
            pass
        return ""

    def _test_site(self, url, timeout=4):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        # Тестируем НАПРЯМУЮ, в обход системного прокси (иначе при активном
        # Opera/Hola проверяется прокси, а не обход DPI — авто-подбор врёт).
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for method in ("HEAD", "GET"):
            try:
                req = urllib.request.Request(url, headers=headers, method=method)
                with opener.open(req, timeout=timeout) as resp:
                    if getattr(resp, "status", 200) < 500:
                        return True
            except Exception:
                continue
        return False

    def _zapret_score(self, urls=None, timeout=4, max_workers=10):
        """Тестирует стратегию по списку URL параллельно. Возвращает (score, latency_seconds).

        urls=None → все ZAPRET_TEST_URLS (55 сайтов).
        timeout=4 → секунд на каждый URL (HEAD → fallback GET).
        max_workers=10 → размер пула потоков.

        Параллелизация через ThreadPoolExecutor сокращает wall-clock время
        на порядок: 55 URL × 0.5s = 27s последовательно → 3-5s параллельно
        (при 10 workers). Это критично для tiered auto-pick: без параллелизации
        261 стратегия × 27s = ~2 часа, с параллелизацией ~10-15 минут.
        """
        if urls is None:
            urls = ZAPRET_TEST_URLS
        t0 = time.monotonic()
        score = self._zapret_score_parallel(urls, timeout, max_workers)
        latency = time.monotonic() - t0
        return score, latency

    def _zapret_score_parallel(self, urls, timeout, max_workers):
        """Параллельно проверяет список URL, возвращает количество успешных."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        if len(urls) <= 1:
            return sum(1 for _, u in urls if self._test_site(u, timeout))
        score = 0
        workers = min(max_workers, len(urls))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(self._test_site, u, timeout): n for n, u in urls}
            for fut in as_completed(futs):
                try:
                    if fut.result():
                        score += 1
                except Exception:
                    pass
        return score

    def _zapret_score_per_site(self):
        """Тестирует стратегию и возвращает dict: {name: True/False, ...}."""
        out = {}
        for name, url in ZAPRET_TEST_URLS:
            out[name] = self._test_site(url)
        return out

    def _start_strategy_by_name(self, name):
        target = None
        target_version = 1
        for version, p in self._list_strategy_files():
            if os.path.splitext(os.path.basename(p))[0] == name:
                target = p
                target_version = version
                break
        if target is None:
            return False
        if not self._find_winws_exe(target_version):
            log.warning(f"winws{target_version}.exe для версии {target_version} не найден")
            return False
        args = self._parse_strategy(target, target_version)
        if not args:
            return False
        self._kill_dpi_process()
        self._ensure_zapret_user_lists(target_version)
        proc = self._launch_winws(args, version=target_version)
        with self._process_lock:
            self.dpi_process = proc
        self.current_zapret_strategy = name
        self.current_zapret_version = target_version
        return True

    def _auto_pick_strategy(self, time_budget=900):
        """Подбирает лучшую стратегию среди ВСЕХ доступных (zapret v1 + zapret2 v2).

        Tiered testing для скорости (default budget 900с = 15 мин):
          Tier 1 (smoke):  5 must-work URL, 2с timeout, 5 parallel workers.
                          Если score < MIN_SMOKE_FOR_DETAILED — skip Tier 2.
          Tier 2 (detail): все 55 URL, 3с timeout, 10 parallel workers.
                          Запускается только если Tier 1 >= 3/5.
                          Early exit при 55/55.

        Алгоритм:
        1. Фильтрует стратегии по режиму zapret_auto_mode (both/v1/v2).
        2. Группирует по bucket (antizapret / general / default / other).
        3. Внутри каждого bucket'а чередует v1 и v2 (round-robin) — чтобы
           хорошая стратегия из v2 могла быть найдена ДО того, как переберём
           100+ v1-стратегий.
        4. Для каждой стратегии: Tier 1 smoke → решение → опционально Tier 2.
           Лучшая по (score DESC, latency ASC) побеждает.
        5. Раннее завершение при perfect detailed score; ограничение по time_budget.
        6. ETA и прогресс в лог/GUI.
        """
        # 1. Режим
        with self._settings_lock:
            mode = (self.settings.get("zapret_auto_mode", "both") or "both").strip().lower()
        if mode not in ZAPRET_AUTO_MODES:
            mode = "both"

        all_files = self._list_strategy_files()
        if mode == "v1":
            files = [x for x in all_files if x[0] == 1]
        elif mode == "v2":
            files = [x for x in all_files if x[0] == 2]
        else:
            files = list(all_files)
        if not files:
            log.warning(f"Авто-подбор: нет стратегий для режима '{mode}'")
            return None

        # 2-3. Round-robin группировка
        def _bucket(item):
            _version, p = item
            name = os.path.basename(p).lower()
            if "antizapret" in name:
                return (0, "antizapret")
            if "general" in name and "alt" not in name:
                return (0, "general")
            if "default" in name and "alt" not in name:
                return (0, "default")
            return (1, "other")

        def _interleave_round_robin(items):
            v1s = sorted([x for x in items if x[0] == 1],
                         key=lambda x: os.path.basename(x[1]).lower())
            v2s = sorted([x for x in items if x[0] == 2],
                         key=lambda x: os.path.basename(x[1]).lower())
            out = []
            i = 0
            while i < len(v1s) or i < len(v2s):
                if i < len(v1s):
                    out.append(v1s[i])
                if i < len(v2s):
                    out.append(v2s[i])
                i += 1
            return out

        buckets = {}
        for item in files:
            key = _bucket(item)
            buckets.setdefault(key, []).append(item)
        sorted_files = []
        for key in sorted(buckets.keys()):
            sorted_files.extend(_interleave_round_robin(buckets[key]))

        total = len(ZAPRET_TEST_URLS)
        total_files = len(sorted_files)
        log.info(
            f"Авто-подбор: режим={mode}, стратегий={total_files} "
            f"(v1={sum(1 for v,_ in sorted_files if v==1)}, "
            f"v2={sum(1 for v,_ in sorted_files if v==2)}), "
            f"тестов={total}, бюджет={time_budget}с"
        )

        # 4-6. Tiered тестирование
        best = None  # (name, score, latency, version)
        deadline = time.time() + time_budget
        tested = 0
        smoke_only = 0  # стратегии, проскочившие только Tier 1
        detailed = 0    # стратегии, прошедшие Tier 2
        skipped_deadline = False
        t_start = time.time()
        for version, p in sorted_files:
            if time.time() > deadline:
                log.info("Авто-подбор: исчерпан лимит времени")
                skipped_deadline = True
                break
            if not self._find_winws_exe(version):
                continue
            name = os.path.splitext(os.path.basename(p))[0]
            args = self._parse_strategy(p, version)
            if not args:
                continue
            self._kill_dpi_process()
            self._ensure_zapret_user_lists(version)
            proc = self._launch_winws(args, version=version)
            with self._process_lock:
                self.dpi_process = proc
            time.sleep(1.5)
            if proc.poll() is not None:
                continue
            tested += 1

            # Tier 1: smoke (5 URL, 2с, 5 workers)
            smoke_score, smoke_lat = self._zapret_score(
                urls=ZAPRET_SMOKE_URLS, timeout=SMOKE_TIMEOUT, max_workers=SMOKE_WORKERS,
            )
            smoke_max = len(ZAPRET_SMOKE_URLS)

            # Решение: skip Tier 2 если smoke явно плохой (< 3/5)
            if smoke_score < MIN_SMOKE_FOR_DETAILED:
                score, latency = smoke_score, smoke_lat
                score_max = smoke_max
                tier_tag = " (smoke-only)"
                smoke_only += 1
            else:
                # Tier 2: подробный (55 URL, 3с, 10 workers)
                score, latency = self._zapret_score(
                    urls=None, timeout=DETAILED_TIMEOUT, max_workers=DETAILED_WORKERS,
                )
                score_max = len(ZAPRET_TEST_URLS)
                tier_tag = ""
                detailed += 1

            elapsed = time.time() - t_start
            avg_per = elapsed / max(tested, 1)
            remaining = max(total_files - tested, 0)
            eta = int(avg_per * remaining)
            is_best = best is None or (score, -latency) > (best[1], -best[2])
            star = " ★" if is_best else ""
            log.info(
                f"  [{tested}/{total_files}] '{name}' v{version}: "
                f"{score}/{score_max} (smoke {smoke_score}/{smoke_max}) "
                f"за {latency:.1f}с{tier_tag} | ETA {eta}с{star}"
            )
            self._js("onDpiStatus", {
                "status": "connecting",
                "message": (
                    f"Проверка «{name}» (v{version}): {score}/{score_max} "
                    f"({tested}/{total_files}, ETA {eta}с)"
                ),
            })
            if is_best:
                best = (name, score, latency, version)
            # 5. Раннее завершение: идеальный detailed score
            if score >= len(ZAPRET_TEST_URLS):
                log.info(
                    f"Авто-подбор: идеальная стратегия '{name}' v{version} "
                    f"({score}/{score_max})"
                )
                self.current_zapret_strategy = name
                self.current_zapret_version = version
                return name
        if best is not None:
            log.info(
                f"Авто-подбор: лучшая '{best[0]}' v{best[3]} — "
                f"{best[1]}/{total} за {best[2]:.1f}с "
                f"(протестировано {tested}/{total_files}: "
                f"tier2={detailed}, smoke-only={smoke_only}, "
                f"истекло {time.time()-t_start:.0f}с)"
            )
            self._start_strategy_by_name(best[0])
            return best[0]
        if skipped_deadline:
            log.info(
                f"Авто-подбор: ни одна стратегия не подошла "
                f"(протестировано {tested}: tier2={detailed}, smoke-only={smoke_only})"
            )
        return None

    def list_hola_countries(self):
        countries = [
            ("ar", "Argentina"), ("at", "Austria"), ("au", "Australia"),
            ("be", "Belgium"), ("bg", "Bulgaria"), ("br", "Brazil"),
            ("ca", "Canada"), ("ch", "Switzerland"), ("cl", "Chile"),
            ("co", "Colombia"), ("cz", "Czechia"), ("de", "Germany"),
            ("dk", "Denmark"), ("es", "Spain"), ("fi", "Finland"),
            ("fr", "France"), ("gb", "United Kingdom"), ("gr", "Greece"),
            ("hk", "Hong Kong"), ("hr", "Croatia"), ("hu", "Hungary"),
            ("id", "Indonesia"), ("ie", "Ireland"), ("il", "Israel"),
            ("in", "India"), ("is", "Iceland"), ("it", "Italy"),
            ("jp", "Japan"), ("kr", "South Korea"), ("mx", "Mexico"),
            ("nl", "Netherlands"), ("no", "Norway"), ("nz", "New Zealand"),
            ("pl", "Poland"), ("ro", "Romania"), ("ru", "Russia"),
            ("se", "Sweden"), ("sk", "Slovakia"), ("sg", "Singapore"),
            ("tr", "Turkey"), ("uk", "United Kingdom"), ("us", "United States"),
        ]
        return safe_json([{"code": c, "name": n} for c, n in countries])

    def start_connect_dpi(self, strategy=None):
        threading.Thread(target=self._do_connect_dpi, args=(strategy,), daemon=True).start()
        return {"ok": True}

    def _do_connect_dpi(self, strategy=None):
        if not self._dpi_lock.acquire(blocking=True, timeout=3):
            self._js("onDpiStatus", {"status": self.dpi_status, "message": "Дождитесь завершения текущей операции"})
            return
        try:
            if not is_admin():
                self._js("onDpiStatus", {"status": "error", "message": "Для обхода DPI требуются права администратора."})
                return
            if not self._list_strategy_files():
                self._js("onDpiStatus", {"status": "error", "message": "Стратегии Zapret не найдены."})
                return
            self.dpi_status = "connecting"
            self._js("onDpiStatus", {"status": "connecting", "message": "Запуск обхода DPI (Zapret)..."})

            if strategy is None:
                with self._settings_lock:
                    strategy = (self.settings.get("zapret_strategy", "") or "").strip()
            strategy = (strategy or "").strip()
            if strategy in ("", "__none__"):
                raise RuntimeError("Сначала выберите стратегию или «Авто-подбор» в настройках")
            auto = (strategy == "__auto__")

            # Определяем версию (v1/v2) и проверяем наличие бинарника
            target_version = 1
            if not auto:
                strategy_found = False
                for v, p in self._list_strategy_files():
                    if os.path.splitext(os.path.basename(p))[0] == strategy:
                        target_version = v
                        strategy_found = True
                        break
                if not strategy_found:
                    # Сохранённая стратегия больше не существует (файл удалён /
                    # переименован / setup.bat не выполнен после обновления).
                    # Fallback на авто-подбор вместо тихой подмены версии.
                    log.warning(
                        f"Сохранённая стратегия '{strategy}' не найдена — "
                        f"переключаюсь на авто-подбор"
                    )
                    auto = True
                    with self._settings_lock:
                        self.settings["zapret_strategy"] = "__auto__"
            else:
                # для авто-подбора берём любую доступную версию (по приоритету 1)
                files = self._list_strategy_files()
                if files:
                    target_version = files[0][0]
            if not self._find_winws_exe(target_version):
                exe_name = "winws2.exe" if target_version == 2 else "winws.exe"
                raise RuntimeError(f"{exe_name} (Zapret v{target_version}) не найден. Соберите приложение заново.")

            self._cleanup_windivert()
            # Авто-регистрация WinDivert-сервиса на наш путь (на случай если
            # ранее он указывал на D:\zapret\bin\ от другой копии zapret).
            # Используем Flowseal DLL (47616 байт) как workaround для
            # истёкшего 2023-05-26 сертификата WinDivert64.sys на Win11+SecureBoot.
            self._register_windivert(target_version)
            self._ensure_zapret_user_lists(target_version)
            miss = self._winws_required_files_ok(target_version)
            if miss:
                raise RuntimeError("Не хватает файлов WinDivert: " + ", ".join(miss))

            if not auto:
                self._js("onDpiStatus", {"status": "connecting", "message": f"Стратегия «{strategy}»..."})
                if not self._start_strategy_by_name(strategy):
                    raise RuntimeError(f"Стратегия «{strategy}» не найдена")
                time.sleep(2.0)
                with self._process_lock:
                    proc = self.dpi_process
                if proc is None or proc.poll() is not None:
                    reason = self._winws_exit_reason()
                    self._kill_dpi_process()
                    raise RuntimeError("winws сразу завершился. " + (reason or "Открой %TEMP%\\winws_out.log"))
                chosen = strategy
            else:
                self._js("onDpiStatus", {"status": "connecting", "message": "Авто-подбор стратегии Zapret..."})
                chosen = self._auto_pick_strategy()
                if not chosen:
                    raise RuntimeError("Не удалось подобрать рабочую стратегию Zapret")

            self.current_zapret_strategy = chosen
            self.dpi_status = "connected"
            with self._settings_lock:
                # Сохраняем КОНКРЕТНОЕ имя стратегии (в т.ч. после auto-pick) —
                # при следующем запуске запустим её напрямую, без повторного
                # auto-pick. Если файл стратегии будет удалён/переименован,
                # _do_connect_dpi сделает fallback на __auto__ при старте.
                self.settings["zapret_strategy"] = chosen
            self._js("onDpiStatus", {"status": "connected", "message": f"Обход DPI активен ({chosen})", "strategy": chosen})
            log.info(f"Zapret запущен (стратегия {chosen}, v{self.current_zapret_version})")
        except Exception as e:
            log.exception("Ошибка запуска DPI")
            self.dpi_status = "error"
            self._kill_dpi_process()
            self.current_zapret_strategy = ""
            self.current_zapret_version = 1
            self._js("onDpiStatus", {"status": "error", "message": f"Ошибка DPI: {e}"})
        finally:
            self._dpi_lock.release()

    def start_disconnect_dpi(self):
        threading.Thread(target=self._do_disconnect_dpi, daemon=True).start()
        return {"ok": True}

    def _do_disconnect_dpi(self):
        if not self._dpi_lock.acquire(blocking=True, timeout=3):
            self._js("onDpiStatus", {"status": self.dpi_status, "message": "Дождитесь завершения текущей операции"})
            return
        try:
            self._kill_dpi_process()
            self.dpi_status = "disconnected"
            self.current_zapret_strategy = ""
            self.current_zapret_version = 1
            self._js("onDpiStatus", {"status": "disconnected", "message": "Обход DPI выключен", "strategy": ""})
            log.info("Zapret остановлен")
        except Exception as e:
            log.exception("Ошибка отключения DPI")
            self._js("onDpiStatus", {"status": "error", "message": f"Ошибка: {e}"})
        finally:
            self._dpi_lock.release()

    def _kill_dpi_process(self):
        with self._process_lock:
            proc = self.dpi_process
            self.dpi_process = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        # Убиваем ОБА варианта winws (v1 = winws.exe, v2 = winws2.exe) — иначе
        # переключение между стратегиями разных версий оставит «висящий» процесс.
        for exe_name in (ZAPRET_WINWS, ZAPRET2_WINWS):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", exe_name],
                    capture_output=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass

    # ---------- TCP-пинг серверов Opera ----------
    def start_ping(self, source="opera", key=None):
        threading.Thread(target=self._do_ping, args=(source, key), daemon=True).start()
        return {"ok": True}

    def _tcp_ping(self, ip, port=443, timeout=4):
        try:
            start = time.time()
            with socket.create_connection((ip, int(port)), timeout=timeout):
                return int((time.time() - start) * 1000)
        except Exception:
            return None

    def _do_ping(self, source="opera", key=None):
        try:
            source = (source or "opera").lower()
            if source == "hola":
                country = (key or self.settings.get("hola_country", "us") or "us").lower()
                label = "Hola " + country.upper()
                servers = self._get_hola_proxies(country)
            else:
                region = key or self.current_region
                if region not in OPERA_REGIONS:
                    self._js("onPingResult", {"error": "Неизвестный регион"})
                    return
                label = "Opera " + region
                servers = self._get_opera_proxies(region)
            if not servers:
                self._js("onPingResult", {"error": f"Не удалось получить список серверов ({label})"})
                return
            results, best = [], None
            for srv in servers[:6]:
                ip = srv.get("ip") or srv.get("host")
                host = srv.get("host") or ip
                port = srv.get("port", 443)
                self._js("onPingProgress", {"server": host, "status": "checking"})
                ms = self._tcp_ping(ip, port, timeout=4)
                if ms is None:
                    self._js("onPingProgress", {"server": host, "status": "timeout"})
                else:
                    self._js("onPingProgress", {"server": host, "status": "ok", "ms": ms})
                    results.append(ms)
                    if best is None or ms < best[1]:
                        best = (host, ms)
            if not results:
                self._js("onPingResult", {"error": "Серверы не отвечают"})
                return
            self._js("onPingResult", {"ping": min(results), "server": best[0] if best else label})
        except Exception as e:
            log.exception("Ошибка пинга")
            self._js("onPingResult", {"error": f"Ошибка: {e}"})

    # ---------- Экстренный сброс / завершение ----------
    def force_kill_all(self):
        threading.Thread(target=self._do_force_kill, daemon=True).start()
        return {"ok": True}

    def _do_force_kill(self):
        log.info("Экстренный сброс всех подключений")
        try:
            self._kill_opera_process()
        except Exception as e:
            log.debug(f"kill opera failed: {e}")
        try:
            self._kill_hola_process()
        except Exception as e:
            log.debug(f"kill hola failed: {e}")
        try:
            self._kill_dpi_process()
            self._cleanup_windivert()
        except Exception as e:
            log.debug(f"kill dpi failed: {e}")
        try:
            self._disable_system_proxy()
        except Exception as e:
            log.debug(f"disable proxy failed: {e}")
        try:
            self._force_cleanup_amnezia_services()
        except Exception as e:
            log.debug(f"cleanup amnezia failed: {e}")
        self.active_http_engine = None
        self.current_zapret_strategy = ""
        self.current_zapret_version = 1
        self.opera_status = "disconnected"
        self.hola_status = "disconnected"
        self.warp_status = "disconnected"
        self.dpi_status = "disconnected"
        self._js("onOperaStatus", {"status": "disconnected"})
        self._js("onHolaStatus", {"status": "disconnected"})
        self._js("onWarpStatus", {"status": "disconnected"})
        self._js("onDpiStatus", {"status": "disconnected", "strategy": ""})
        log.info("Экстренный сброс завершён")

    def shutdown(self):
        log.info("Завершение работы приложения, очистка...")
        try:
            self._kill_opera_process()
            self._kill_hola_process()
        except Exception as e:
            log.debug(f"shutdown proxy kill failed: {e}")
        try:
            self._kill_dpi_process()
            self._cleanup_windivert()
            self.current_zapret_strategy = ""
            self.current_zapret_version = 1
        except Exception as e:
            log.debug(f"shutdown dpi cleanup failed: {e}")
        try:
            self._disable_system_proxy()
            self.active_http_engine = None
        except Exception as e:
            log.debug(f"shutdown proxy disable failed: {e}")
        try:
            self._force_cleanup_amnezia_services()
        except Exception as e:
            log.debug(f"shutdown warp cleanup failed: {e}")
        # дать дочерним процессам (winws/WinDivert) освободить _MEI-каталог
        time.sleep(0.6)


# ---------------------------------------------------------------------------
# Служебный хелпер для sc.exe (управление службами AmneziaWG)
# ---------------------------------------------------------------------------
@dataclass
class ScResult:
    returncode: int
    stdout_decoded: str = ""
    stderr_decoded: str = ""


def sc_run(*args, timeout=30):
    cmd = ["sc.exe"] + list(args)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return ScResult(
            returncode=proc.returncode,
            stdout_decoded=decode_output(proc.stdout),
            stderr_decoded=decode_output(proc.stderr),
        )
    except subprocess.TimeoutExpired:
        log.warning(f"sc.exe таймаут: {' '.join(cmd)}")
        return ScResult(returncode=-1, stderr_decoded="timeout")
    except FileNotFoundError:
        log.error("sc.exe не найден")
        return ScResult(returncode=-2, stderr_decoded="sc.exe not found")
    except Exception as e:
        log.error(f"sc.exe ошибка: {e}")
        return ScResult(returncode=-3, stderr_decoded=str(e))


# ---------------------------------------------------------------------------
# Иконка в системном трее
# ---------------------------------------------------------------------------
class TrayManager:
    def __init__(self, window, api):
        self.window = window
        self.api = api
        self.icon = None
        self._thread = None

    def _load_image(self):
        try:
            from PIL import Image
        except Exception as e:
            log.warning(f"PIL недоступен, иконка трея не загружена: {e}")
            return None
        names = [
            os.path.join("IMG", "icon.ico"), os.path.join("IMG", "icon.png"),
            "icon.ico", "icon.png",
        ]
        seen, paths = set(), []
        for n in names:
            for cand in (
                get_resource_path(n),
                os.path.join(getattr(sys, "_MEIPASS", ""), n) if hasattr(sys, "_MEIPASS") else "",
                os.path.join(os.path.dirname(sys.executable), n) if getattr(sys, "frozen", False) else "",
                os.path.join(os.path.abspath("."), n),
            ):
                if cand and cand not in seen:
                    seen.add(cand); paths.append(cand)
        for p in paths:
            if os.path.exists(p):
                try:
                    img = Image.open(p); img.load()
                    return img.convert("RGBA")
                except Exception as e:
                    log.debug(f"Не удалось открыть иконку {p}: {e}")
        # запасная иконка, если файл не нашёлся
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((6, 6, 58, 58), fill=(52, 210, 123, 255))
            d.rectangle((28, 20, 36, 44), fill=(255, 255, 255, 255))
            return img
        except Exception:
            try:
                from PIL import Image
                return Image.new("RGB", (64, 64), (52, 210, 123))
            except Exception:
                return None

    def _on_show(self, icon=None, item=None):
        try:
            self.window.show()
        except Exception as e:
            log.debug(f"tray show failed: {e}")

    def _on_exit(self, icon=None, item=None):
        log.info("Выход через трей")
        try:
            self.api.shutdown()
        except Exception as e:
            log.debug(f"tray shutdown failed: {e}")
        try:
            if self.icon is not None:
                self.icon.stop()
        except Exception:
            pass
        try:
            self.window.destroy()
        except Exception:
            pass
        time.sleep(0.8)
        os._exit(0)

    def start(self):
        try:
            import pystray
        except Exception as e:
            log.warning(f"pystray недоступен, трей отключён: {e}")
            return
        image = self._load_image()
        if image is None:
            log.warning("Нет изображения для трея")
            return
        menu = pystray.Menu(
            pystray.MenuItem("Показать VPN Client", self._on_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", self._on_exit),
        )
        self.icon = pystray.Icon("vpn_client", image, APP_NAME, menu)
        self._thread = threading.Thread(target=self.icon.run, daemon=True)
        self._thread.start()
        log.info("Иконка в трее запущена")


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
# Глобальная ссылка на Api для cleanup при выходе (atexit, signal, kill).
# Устанавливается в main() сразу после создания api. Нужна, т.к. on_closing
# и _on_exit в трее вызывают api.shutdown() напрямую, а для случаев
# необработанного exception / SIGTERM — нет прямого пути к api.
_API_REF = {"api": None, "cleanup_done": False}


def _safe_shutdown():
    """Идемпотентный cleanup. Вызывается из atexit, signal handlers и т.д."""
    api = _API_REF.get("api")
    if api is None or _API_REF.get("cleanup_done"):
        return
    _API_REF["cleanup_done"] = True
    try:
        api.shutdown()
    except Exception as e:
        try:
            log.debug(f"_safe_shutdown failed: {e}")
        except Exception:
            pass


def _install_signal_handlers():
    """SIGTERM/SIGBREAK (Windows) → cleanup. SIGINT обработается в webview."""
    if signal is None:
        return
    try:
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, lambda *_: _safe_shutdown())
    except Exception:
        pass
    # Windows-only: SIGBREAK прилетает от taskkill /F (без /F не дойдёт),
    # но если процесс запущен из консоли — сработает.
    if hasattr(signal, "SIGBREAK"):
        try:
            signal.signal(signal.SIGBREAK, lambda *_: _safe_shutdown())
        except Exception:
            pass


def main():
    log.info(f"Запуск {APP_NAME} v{APP_VERSION}")

    # Сброс возможно зависшего системного прокси от предыдущего запуска
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROXY_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            try:
                wininet = ctypes.windll.wininet
                wininet.InternetSetOptionW(0, 39, 0, 0)
                wininet.InternetSetOptionW(0, 37, 0, 0)
            except Exception:
                pass
            log.info("Старый системный прокси сброшен при старте")
        except Exception as e:
            log.debug(f"Не удалось сбросить прокси при старте: {e}")

    window = webview.create_window(
        APP_NAME,
        html=HTML,
        width=540,
        height=940,
        min_size=(480, 820),
        resizable=True,
        text_select=False,
    )
    api = Api(window)
    _API_REF["api"] = api
    if atexit is not None:
        try:
            atexit.register(_safe_shutdown)
        except Exception:
            pass
    _install_signal_handlers()
    window.expose(
        api.get_version,
        api.get_settings,
        api.save_settings,
        api.open_logs,
        api.get_status,
        api.start_connect,
        api.start_disconnect,
        api.start_generate_warp,
        api.start_connect_warp,
        api.start_disconnect_warp,
        api.start_connect_hola,
        api.start_disconnect_hola,
        api.start_connect_dpi,
        api.start_disconnect_dpi,
        api.list_hola_countries,
        api.list_zapret_strategies,
        api.start_ping,
        api.force_kill_all,
    )

    tray = TrayManager(window, api)
    tray.start()

    def _closing():
        window.hide()
        return False

    window.events.closing += _closing

    debug = "--debug" in sys.argv
    try:
        webview.start(debug=debug, gui="edgechromium")
    except Exception as e:
        log.warning(f"edgechromium недоступен ({e}), пробуем стандартный движок")
        webview.start(debug=debug)
    finally:
        try:
            api.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Критическая ошибка")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(APP_NAME, f"Критическая ошибка:\n{e}\n\nЛог: {LOG_FILE}")
            root.destroy()
        except Exception:
            pass
        sys.exit(1)