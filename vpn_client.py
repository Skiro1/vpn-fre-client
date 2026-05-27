# -*- coding: utf-8 -*-
"""
VPN Client v1.6.0 — Opera Proxy + Cloudflare WARP (AmneziaWG)

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
import urllib.request
from datetime import datetime
from dataclasses import dataclass

try:
    import winreg
except ImportError:
    winreg = None

import webview

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
LOG_FILE = os.path.join(tempfile.gettempdir(), "vpn_client_debug.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        (logging.StreamHandler(sys.stdout) if sys.stdout is not None else logging.NullHandler()) if "--debug" in sys.argv else logging.NullHandler(),
    ],
)
log = logging.getLogger("vpn-client")
log.info(f"Лог-файл: {LOG_FILE}")

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------
APP_NAME = "VPN Client"
APP_VERSION = "1.6.0"

OPERA_EXE = "opera-proxy.exe"
WARP_GEN_EXE = "warp-awg-gen.exe"
WARP_CONF_NAME = "warp.conf"

AMNEZIAWG_VERSION = "2.0.0"
AMNEZIAWG_MSI_URL = (
    "https://github.com/amnezia-vpn/amneziawg-windows-client/releases/download/"
    f"{AMNEZIAWG_VERSION}/amneziawg-{{arch}}-{AMNEZIAWG_VERSION}.msi"
)

OPERA_PROXY_VERSION = "v1.17.0"
OPERA_PROXY_URL = (
    "https://github.com/Alexey71/opera-proxy/releases/download/"
    f"{OPERA_PROXY_VERSION}/opera-proxy.windows-{{arch}}.exe"
)

WARP_AWG_GEN_VERSION = "v1.0.0"
WARP_AWG_GEN_URL = (
    "https://github.com/Skiro1/warp-awg-gen/releases/download/"
    f"{WARP_AWG_GEN_VERSION}/warp-awg-gen-windows-{{arch}}.exe"
)

BINARY_ARCH_MAP = {"amd64": "amd64", "arm64": "arm64", "x86": "386"}

def _amnezia_arch():
    m = platform.machine().lower()
    if m in ("amd64", "x86_64"):
        return "amd64"
    elif m == "arm64":
        return "arm64"
    else:
        return "x86"

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
# Авто-загрузка бинарников
# ---------------------------------------------------------------------------
def _download_file(url, dest, label="", timeout=120):
    log.info(f"Загрузка {label or url} -> {dest}")
    try:
        urllib.request.urlretrieve(url, dest)
        log.info(f"Загрузка завершена: {os.path.getsize(dest)} байт")
    except Exception as e:
        log.error(f"Ошибка загрузки {url}: {e}")
        raise

def _ensure_binaries():
    for name, url_template in [
        (OPERA_EXE, OPERA_PROXY_URL),
        (WARP_GEN_EXE, WARP_AWG_GEN_URL),
    ]:
        path = get_resource_path(name)
        if os.path.exists(path):
            log.info(f"{name} уже есть")
            continue
        arch = BINARY_ARCH_MAP.get(_amnezia_arch(), "amd64")
        url = url_template.format(arch=arch)
        dest = os.path.join(os.path.abspath("."), name)
        try:
            _download_file(url, dest, label=name)
        except Exception as e:
            log.warning(f"Не удалось скачать {name}: {e}")

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


_ensure_binaries()

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8" />
<title>VPN Client</title>
<style>
:root{
    --bg-0:#0a0b1e;--bg-1:#11132b;--bg-2:#1a1d3a;
    --accent:#7c5cff;--accent-2:#00d4ff;--success:#00ff88;
    --danger:#ff3860;--warn:#ffb020;
    --text:#e8eaff;--text-dim:#8b90b8;
    --glass:rgba(255,255,255,0.04);--glass-brd:rgba(255,255,255,0.08);
    --radius:16px;--shadow:0 10px 40px rgba(0,0,0,0.45);
}
*{box-sizing:border-box;margin:0;padding:0;}
html,body{height:100%;}
body{
    font-family:'Segoe UI',-apple-system,system-ui,sans-serif;
    color:var(--text);
    background:radial-gradient(1200px 800px at 20% 10%, #1a1048 0%, transparent 60%),
               radial-gradient(1000px 700px at 80% 90%, #00324a 0%, transparent 55%),
               var(--bg-0);
    overflow-x:hidden;min-height:100vh;user-select:none;
    -webkit-app-region: drag;
}
button,select,input,a,.no-drag{-webkit-app-region: no-drag;}
.orb{position:fixed;border-radius:50%;filter:blur(80px);opacity:0.35;pointer-events:none;z-index:0;animation:float 18s ease-in-out infinite;}
.orb.o1{width:380px;height:380px;background:var(--accent);top:-120px;left:-120px;}
.orb.o2{width:320px;height:320px;background:var(--accent-2);bottom:-100px;right:-100px;animation-delay:-6s;}
.orb.o3{width:260px;height:260px;background:#ff3eae;top:40%;left:55%;opacity:0.18;animation-delay:-12s;}
@keyframes float{0%,100%{transform:translate(0,0) scale(1);}50%{transform:translate(40px,-30px) scale(1.08);}}
.container{position:relative;z-index:1;max-width:560px;margin:0 auto;padding:28px 24px 18px;min-height:100vh;display:flex;flex-direction:column;gap:18px;}
.header{display:flex;align-items:center;justify-content:space-between;gap:12px;}
.logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:18px;}
.logo-badge{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--accent),var(--accent-2));display:grid;place-items:center;box-shadow:0 6px 20px rgba(124,92,255,0.45);}
.logo-badge svg{width:18px;height:18px;fill:white;}
.icon-btn{background:var(--glass);border:1px solid var(--glass-brd);color:var(--text);width:38px;height:38px;border-radius:10px;display:grid;place-items:center;cursor:pointer;transition:0.2s;backdrop-filter:blur(10px);}
.icon-btn:hover{background:rgba(255,255,255,0.08);transform:translateY(-1px);}
.icon-btn svg{width:18px;height:18px;fill:currentColor;}
.status{text-align:center;}
.status-badge{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;background:var(--glass);border:1px solid var(--glass-brd);font-size:12px;text-transform:uppercase;letter-spacing:1.5px;color:var(--text-dim);}
.status-badge .dot{width:8px;height:8px;border-radius:50%;background:var(--text-dim);box-shadow:0 0 0 0 currentColor;}
.status-badge.connected{color:var(--success);border-color:rgba(0,255,136,0.3);}
.status-badge.connected .dot{background:var(--success);animation:pulse 2s infinite;}
.status-badge.connecting{color:var(--warn);border-color:rgba(255,176,32,0.3);}
.status-badge.connecting .dot{background:var(--warn);animation:pulse 1s infinite;}
.status-badge.disconnected{color:var(--danger);border-color:rgba(255,56,96,0.3);}
.status-badge.disconnected .dot{background:var(--danger);}
@keyframes pulse{0%{box-shadow:0 0 0 0 currentColor;}70%{box-shadow:0 0 0 10px transparent;}100%{box-shadow:0 0 0 0 transparent;}}
.status-title{margin-top:10px;font-size:22px;font-weight:700;background:linear-gradient(90deg,#fff,#c9cfff);-webkit-background-clip:text;background-clip:text;color:transparent;}
.power-wrap{display:grid;place-items:center;padding:10px 0;}
.power{width:180px;height:180px;border-radius:50%;border:none;cursor:pointer;background:radial-gradient(circle at 30% 30%, #2a2060 0%, #140d38 70%);position:relative;box-shadow:inset 0 0 30px rgba(124,92,255,0.3),0 20px 60px rgba(0,0,0,0.5),0 0 0 8px rgba(124,92,255,0.08);transition:all 0.4s cubic-bezier(.2,.9,.3,1.2);display:grid;place-items:center;color:var(--text-dim);}
.power:hover{transform:scale(1.03);}
.power:active{transform:scale(0.97);}
.power svg{width:64px;height:64px;fill:currentColor;filter:drop-shadow(0 0 12px currentColor);}
.power.on{color:var(--success);background:radial-gradient(circle at 30% 30%, #0a3a24 0%, #071a12 70%);box-shadow:inset 0 0 40px rgba(0,255,136,0.35),0 20px 70px rgba(0,255,136,0.25),0 0 0 8px rgba(0,255,136,0.12);}
.power.connecting{color:var(--warn);animation:spin 1.8s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.btn{padding:12px 14px;border-radius:12px;background:var(--glass);border:1px solid var(--glass-brd);color:var(--text);font-size:13px;font-weight:600;cursor:pointer;transition:0.2s;display:flex;align-items:center;justify-content:center;gap:8px;backdrop-filter:blur(10px);}
.btn:hover{background:rgba(255,255,255,0.08);transform:translateY(-1px);}
.btn:disabled{opacity:0.4;cursor:not-allowed;transform:none !important;}
.btn svg{width:16px;height:16px;fill:currentColor;}
.btn.danger{color:var(--danger);border-color:rgba(255,56,96,0.25);}
.btn.danger:hover:not(:disabled){background:rgba(255,56,96,0.08);}
.btn.primary{background:linear-gradient(135deg,var(--accent),var(--accent-2));border:none;color:white;box-shadow:0 8px 24px rgba(124,92,255,0.35);}
.btn.primary:hover:not(:disabled){box-shadow:0 10px 30px rgba(124,92,255,0.5);}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;}
.stat{background:var(--glass);border:1px solid var(--glass-brd);border-radius:12px;padding:12px 10px;text-align:center;backdrop-filter:blur(10px);}
.stat-label{font-size:10px;text-transform:uppercase;letter-spacing:1.2px;color:var(--text-dim);}
.stat-value{font-size:15px;font-weight:700;margin-top:4px;}
.card{background:var(--glass);border:1px solid var(--glass-brd);border-radius:var(--radius);padding:16px;backdrop-filter:blur(14px);box-shadow:var(--shadow);}
.card-title{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:700;margin-bottom:12px;letter-spacing:0.3px;}
.card-title .pill{margin-left:auto;font-size:10px;padding:3px 8px;border-radius:999px;background:rgba(0,212,255,0.12);color:var(--accent-2);text-transform:uppercase;letter-spacing:1px;}
.warp-row{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.warp-info{font-size:12px;color:var(--text-dim);margin-top:10px;display:flex;align-items:center;gap:6px;word-break:break-all;}
.footer{text-align:center;color:var(--text-dim);font-size:11px;margin-top:auto;padding-top:10px;}
.toasts{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:1000;display:flex;flex-direction:column;gap:8px;pointer-events:none;max-width:90vw;}
.toast{background:rgba(20,22,50,0.95);border:1px solid var(--glass-brd);border-left:3px solid var(--accent);padding:10px 16px;border-radius:10px;font-size:13px;min-width:240px;max-width:400px;backdrop-filter:blur(20px);box-shadow:0 10px 30px rgba(0,0,0,0.5);animation:slideIn 0.3s ease;}
.toast.success{border-left-color:var(--success);}
.toast.error{border-left-color:var(--danger);}
.toast.warn{border-left-color:var(--warn);}
@keyframes slideIn{from{opacity:0;transform:translateY(20px);}to{opacity:1;transform:translateY(0);}}
.modal-back{position:fixed;inset:0;background:rgba(0,0,0,0.6);display:none;align-items:center;justify-content:center;z-index:900;backdrop-filter:blur(6px);}
.modal-back.show{display:flex;}
.modal{width:90%;max-width:420px;background:linear-gradient(160deg,#1a1d3a,#11132b);border:1px solid var(--glass-brd);border-radius:var(--radius);padding:22px;box-shadow:var(--shadow);animation:popIn 0.25s cubic-bezier(.2,.9,.3,1.2);}
@keyframes popIn{from{opacity:0;transform:scale(0.92);}to{opacity:1;transform:scale(1);}}
.modal h3{margin-bottom:14px;font-size:17px;}
.field{margin-bottom:12px;}
.field label{display:block;font-size:12px;color:var(--text-dim);margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;}
.field select, .field input{width:100%;padding:10px 12px;border-radius:10px;background:rgba(0,0,0,0.3);border:1px solid var(--glass-brd);color:var(--text);font-size:14px;outline:none;}
.field select:focus, .field input:focus{border-color:var(--accent);}
.modal-actions{display:flex;gap:10px;margin-top:16px;}
.modal-actions .btn{flex:1;}
.spinner{width:14px;height:14px;border-radius:50%;border:2px solid rgba(255,255,255,0.2);border-top-color:white;animation:spin 0.8s linear infinite;display:inline-block;}
.ping-result{margin-top:12px;padding:12px;border-radius:10px;background:rgba(0,0,0,0.3);text-align:center;}
.ping-value{font-size:32px;font-weight:700;color:var(--success);margin:10px 0;}
</style>
</head>
<body>
<div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div>

<div class="container">
    <div class="header">
        <div class="logo">
            <div class="logo-badge"><svg viewBox="0 0 24 24"><path d="M12 1L3 5v6c0 5.5 3.8 10.7 9 12 5.2-1.3 9-6.5 9-12V5l-9-4zm-1 6h2v6h-2V7zm0 8h2v2h-2v-2z"/></svg></div>
            <div>
                <div>VPN Client</div>
                <div style="font-size:10px;color:var(--text-dim);font-weight:400;">Opera + WARP</div>
            </div>
        </div>
        <button class="icon-btn" id="btnSettings" title="Настройки">
            <svg viewBox="0 0 24 24"><path d="M19.4 13c0-.3.1-.6.1-.9s0-.6-.1-.9l2.1-1.7c.2-.2.2-.4.1-.6l-2-3.5c-.1-.2-.3-.3-.5-.2l-2.5 1c-.5-.4-1.1-.7-1.7-1l-.4-2.6c0-.2-.2-.4-.4-.4h-4c-.2 0-.4.2-.4.4l-.4 2.6c-.6.3-1.2.6-1.7 1l-2.5-1c-.2-.1-.5 0-.6.2l-2 3.5c-.1.2-.1.5.1.6l2.1 1.7c0 .3-.1.6-.1.9s0 .6.1.9L3.2 14.6c-.2.2-.2.4-.1.6l2 3.5c.1.2.3.3.5.2l2.5-1c.5.4 1.1.7 1.7 1l.4 2.6c0 .2.2.4.4.4h4c.2 0 .4-.2.4-.4l.4-2.6c.6-.3 1.2-.6 1.7-1l2.5 1c.2.1.5 0 .6-.2l2-3.5c.1-.2.1-.5-.1-.6l-2.1-1.7zM12 15.5c-1.9 0-3.5-1.6-3.5-3.5s1.6-3.5 3.5-3.5 3.5 1.6 3.5 3.5-1.6 3.5-3.5 3.5z"/></svg>
        </button>
    </div>

    <div class="status">
        <span class="status-badge disconnected" id="statusBadge">
            <span class="dot"></span>
            <span id="statusText">Отключено</span>
        </span>
        <div class="status-title" id="statusTitle">Защита неактивна</div>
    </div>

    <div class="power-wrap">
        <button class="power" id="btnPower" title="Opera Proxy">
            <svg viewBox="0 0 24 24"><path d="M13 3h-2v10h2V3zm4.83 2.17l-1.42 1.42C17.99 7.86 19 9.81 19 12c0 3.87-3.13 7-7 7s-7-3.13-7-7c0-2.19 1.01-4.14 2.58-5.42L6.17 5.17C4.23 6.82 3 9.26 3 12c0 4.97 4.03 9 9 9s9-4.03 9-9c0-2.74-1.23-5.18-3.17-6.83z"/></svg>
        </button>
    </div>

    <div class="row">
        <button class="btn" id="btnPing">
            <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>
            Пинг
        </button>
        <button class="btn danger" id="btnKill">
            <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5 11H7v-2h10v2z"/></svg>
            Сброс
        </button>
    </div>

    <div class="stats">
        <div class="stat"><div class="stat-label">Регион</div><div class="stat-value" id="statRegion">\u2014</div></div>
        <div class="stat"><div class="stat-label">Серверов</div><div class="stat-value" id="statServers">\u2014</div></div>
        <div class="stat"><div class="stat-label">Протокол</div><div class="stat-value" id="statProto">\u2014</div></div>
    </div>

    <div class="card">
        <div class="card-title">
            <svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--accent-2);"><path d="M13 2.05v3.03c3.39.49 6 3.39 6 6.92 0 .9-.18 1.75-.48 2.54l2.6 1.53c.56-1.24.88-2.62.88-4.07 0-5.18-3.95-9.45-9-9.95zM12 19c-3.87 0-7-3.13-7-7 0-3.53 2.61-6.43 6-6.92V2.05c-5.06.5-9 4.76-9 9.95 0 5.52 4.47 10 9.99 10 3.31 0 6.24-1.61 8.06-4.09l-2.6-1.53C16.17 17.98 14.21 19 12 19z"/></svg>
            Cloudflare WARP
            <span class="pill" id="warpPill">Offline</span>
        </div>
        <div class="warp-row">
            <button class="btn" id="btnWarpGen">
                <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
                Сгенерировать
            </button>
            <button class="btn primary" id="btnWarpConn">
                <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                <span id="warpConnLabel">Подключить</span>
            </button>
        </div>
        <div class="warp-info" id="warpInfo">Конфиг будет создан в рабочей директории приложения</div>
    </div>

    <div class="footer">VPN Client v<span id="appVersion">1.5.0</span> · Opera Proxy + AmneziaWG</div>
</div>

<div class="modal-back" id="settingsModal">
    <div class="modal">
        <h3>Настройки</h3>
        <div class="field">
            <label>Регион Opera Proxy</label>
            <select id="selRegion">
                <option value="EU">Европа (EU)</option>
                <option value="AS">Азия (AS)</option>
                <option value="AM">Америка (AM)</option>
            </select>
        </div>
        <div class="field">
            <label>Локальный порт</label>
            <input type="number" id="inpPort" value="18080" min="1024" max="65535" />
        </div>
        <div class="modal-actions">
            <button class="btn" id="btnSettingsCancel">Отмена</button>
            <button class="btn primary" id="btnSettingsSave">Сохранить</button>
        </div>
    </div>
</div>

<div class="modal-back" id="pingModal">
    <div class="modal">
        <h3>Пинг Opera Proxy (<span id="pingRegion">EU</span>)</h3>
        <div class="ping-result" id="pingResult">
            <div style="color:var(--text-dim);">Нажмите "Запустить" для проверки задержки</div>
        </div>
        <div class="modal-actions">
            <button class="btn" id="btnPingClose">Закрыть</button>
            <button class="btn primary" id="btnPingRun">Запустить</button>
        </div>
    </div>
</div>

<div class="toasts" id="toasts"></div>

<script>
const $ = s => document.querySelector(s);
const state = {
    opera: 'disconnected',
    warp:  'disconnected',
    settings: { region:'EU', port:18080 },
    operaBusy: false,
    warpBusy: false,
    pingBusy: false,
    serverCount: 0,
};

function escapeHtml(s){
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}
function debounceButton(btn, ms=1500){
    if (!btn) return;
    btn.disabled = true;
    setTimeout(()=>{
        if (btn.id === 'btnPower' && !state.operaBusy) btn.disabled = false;
        else if ((btn.id === 'btnWarpGen' || btn.id === 'btnWarpConn') && !state.warpBusy) btn.disabled = false;
        else if (btn.id === 'btnPingRun' && !state.pingBusy) btn.disabled = false;
        else btn.disabled = false;
    }, ms);
}

function toast(msg, type='info', ttl=3500){
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.textContent = msg;
    $('#toasts').appendChild(el);
    setTimeout(()=>{
        el.style.transition='opacity .3s, transform .3s';
        el.style.opacity='0';
        el.style.transform='translateY(20px)';
        setTimeout(()=>el.remove(), 300);
    }, ttl);
}

function renderStatus(){
    const badge = $('#statusBadge');
    const txt = $('#statusText');
    const title = $('#statusTitle');
    const btn = $('#btnPower');

    badge.classList.remove('connected','connecting','disconnected');
    btn.classList.remove('on','connecting');

    if (state.opera === 'connected'){
        badge.classList.add('connected');
        txt.textContent = 'Opera: Подключено';
        title.textContent = state.warp === 'connected' ? 'WARP + Opera активны' : 'Opera Proxy активен';
        btn.classList.add('on');
    } else if (state.opera === 'connecting'){
        badge.classList.add('connecting');
        txt.textContent = 'Opera: Подключение...';
        title.textContent = 'Устанавливаем соединение';
        btn.classList.add('connecting');
    } else {
        badge.classList.add('disconnected');
        txt.textContent = state.warp === 'connected' ? 'WARP: Подключено' : 'Отключено';
        title.textContent = state.warp === 'connected' ? 'WARP активен' : 'Защита неактивна';
    }

    const pill = $('#warpPill');
    pill.textContent = state.warp === 'connected' ? 'Online' : state.warp === 'connecting' ? '...' : 'Offline';
    pill.style.background = state.warp === 'connected' ? 'rgba(0,255,136,0.15)'
                         : state.warp === 'connecting' ? 'rgba(255,176,32,0.15)'
                         : 'rgba(0,212,255,0.12)';
    pill.style.color = state.warp === 'connected' ? 'var(--success)'
                      : state.warp === 'connecting' ? 'var(--warn)'
                      : 'var(--accent-2)';

    $('#warpConnLabel').textContent = state.warp === 'connected' ? 'Отключить' : 'Подключить';

    $('#btnWarpGen').disabled = state.warpBusy;
    $('#btnWarpConn').disabled = state.warpBusy;
    $('#btnPower').disabled = state.operaBusy;

    if (state.opera === 'connected'){
        $('#statRegion').textContent = state.settings.region;
        $('#statServers').textContent = state.serverCount || '\u2014';
        $('#statProto').textContent = 'HTTP';
    } else {
        $('#statRegion').textContent = '\u2014';
        $('#statServers').textContent = '\u2014';
        $('#statProto').textContent = '\u2014';
    }
}

async function callApi(name, ...args){
    if (!window.pywebview?.api){
        toast('API ещё не готов', 'warn');
        return null;
    }
    try{
        return await window.pywebview.api[name](...args);
    } catch(e){
        console.error(name, e);
        toast('Ошибка: ' + e.message, 'error');
        return null;
    }
}

window.onOperaStatus = function(data){
    state.opera = data.status;
    if (data.status !== 'connecting') {
        state.operaBusy = false;
        $('#btnPower').disabled = false;
    }
    if (data.server_count !== undefined) state.serverCount = data.server_count;
    if (data.message) toast(data.message, data.status === 'connected' ? 'success' : data.status === 'error' ? 'error' : 'info');
    renderStatus();
};
window.onWarpStatus = function(data){
    state.warp = data.status;
    if (data.status !== 'connecting') {
        state.warpBusy = false;
        $('#btnWarpGen').disabled = false;
        $('#btnWarpConn').disabled = false;
    }
    if (data.message) toast(data.message, data.status === 'connected' ? 'success' : data.status === 'error' ? 'error' : 'info');
    if (data.info) $('#warpInfo').textContent = data.info;
    renderStatus();
};
window.onPingProgress = function(data){
    const el = $('#pingResult');
    el.innerHTML = `<div style="color:var(--text-dim);">${escapeHtml(data.server)} — ${data.status === 'timeout' ? 'не отвечает' : 'проверяем...'}</div>`;
};
window.onPingResult = function(data){
    const el = $('#pingResult');
    if (data.error){
        el.textContent = '';
        const div = document.createElement('div');
        div.style.color = 'var(--danger)';
        div.textContent = data.error;
        el.appendChild(div);
    } else {
        el.innerHTML = `
            <div style="color:var(--text-dim);">Средняя задержка до сервера</div>
            <div class="ping-value">${data.ping} мс</div>
            <div style="color:var(--text-dim);font-size:11px;">${escapeHtml(data.server)}</div>
        `;
    }
    state.pingBusy = false;
    $('#btnPingRun').disabled = false;
    $('#btnPingRun').innerHTML = 'Запустить';
};
window.onStatusPoll = function(data){
    if (state.opera !== 'connecting' && data.opera !== state.opera){ state.opera = data.opera; }
    if (state.warp  !== 'connecting' && data.warp  !== state.warp ){ state.warp  = data.warp;  }
    if (data.opera_region) state.settings.region = data.opera_region;
    if (data.opera_port)   state.settings.port   = data.opera_port;
    if (data.warp_info)    $('#warpInfo').textContent = data.warp_info;
    if (data.server_count !== undefined) state.serverCount = data.server_count;
    renderStatus();
};
window.onSettingsLoaded = function(s){
    state.settings = Object.assign(state.settings, s);
    $('#selRegion').value = state.settings.region;
    $('#inpPort').value   = state.settings.port;
    renderStatus();
};

$('#btnPower').addEventListener('click', async () => {
    if (state.operaBusy) return;
    debounceButton($('#btnPower'), 1500);
    if (state.opera === 'connected'){
        state.opera = 'connecting';
        state.operaBusy = true;
        renderStatus();
        await callApi('start_disconnect');
    } else if (state.opera === 'disconnected' || state.opera === 'error'){
        state.opera = 'connecting';
        state.operaBusy = true;
        renderStatus();
        await callApi('start_connect', state.settings.region, state.settings.port);
    }
});

$('#btnWarpGen').addEventListener('click', async () => {
    if (state.warpBusy) return;
    debounceButton($('#btnWarpGen'), 3000);
    state.warpBusy = true;
    renderStatus();
    toast('Генерация WARP-конфига...', 'info');
    await callApi('start_generate_warp');
});
$('#btnWarpConn').addEventListener('click', async () => {
    if (state.warpBusy) return;
    debounceButton($('#btnWarpConn'), 2000);
    state.warpBusy = true;
    if (state.warp === 'connected'){
        state.warp = 'connecting';
        renderStatus();
        await callApi('start_disconnect_warp');
    } else {
        state.warp = 'connecting';
        renderStatus();
        await callApi('start_connect_warp');
    }
});

$('#btnPing').addEventListener('click', () => {
    $('#pingModal').classList.add('show');
    $('#pingRegion').textContent = state.settings.region;
    $('#pingResult').innerHTML = '<div style="color:var(--text-dim);">Нажмите "Запустить" для проверки задержки</div>';
});
$('#btnPingClose').addEventListener('click', () => $('#pingModal').classList.remove('show'));
$('#btnPingRun').addEventListener('click', async () => {
    if (state.pingBusy) return;
    state.pingBusy = true;
    debounceButton($('#btnPingRun'), 5000);
    $('#btnPingRun').innerHTML = '<span class="spinner"></span> Пингуем...';
    $('#pingResult').innerHTML = '<div style="color:var(--text-dim);">Проверяем задержку...</div>';
    await callApi('start_ping', state.settings.region);
});

$('#btnKill').addEventListener('click', async () => {
    if (!confirm('Экстренно сбросить все подключения и прокси?')) return;
    debounceButton($('#btnKill'), 3000);
    await callApi('force_kill_all');
    state.opera = 'disconnected';
    state.warp  = 'disconnected';
    state.warpBusy = false;
    state.operaBusy = false;
    $('#btnWarpGen').disabled = false;
    $('#btnWarpConn').disabled = false;
    $('#btnPower').disabled = false;
    renderStatus();
    toast('Все процессы остановлены', 'success');
});

$('#btnSettings').addEventListener('click', () => $('#settingsModal').classList.add('show'));
$('#btnSettingsCancel').addEventListener('click', () => $('#settingsModal').classList.remove('show'));
$('#btnSettingsSave').addEventListener('click', async () => {
    const s = {
        region: $('#selRegion').value,
        port: parseInt($('#inpPort').value,10) || 18080,
    };
    state.settings = s;
    await callApi('save_settings', JSON.stringify(s));
    $('#settingsModal').classList.remove('show');
    toast('Настройки сохранены', 'success');
    renderStatus();
});

async function init(){
    let tries = 0;
    while (!window.pywebview?.api && tries < 30){
        await new Promise(r => setTimeout(r, 200));
        tries++;
    }
    if (!window.pywebview?.api){
        toast('API не доступен', 'error', 99999);
        return;
    }
    $('#appVersion').textContent = await callApi('get_version') || '1.5.0';
    const s = await callApi('get_settings');
    if (s){
        try{ state.settings = Object.assign(state.settings, typeof s === 'string' ? JSON.parse(s) : s); }catch(e){}
    }
    window.onSettingsLoaded(state.settings);
    setInterval(async () => {
        const d = await callApi('get_status');
        if (d) window.onStatusPoll(typeof d === 'string' ? JSON.parse(d) : d);
    }, 2000);
    renderStatus();
}
let _initDone = false;
async function initSafe(){
    if (_initDone) return;
    _initDone = true;
    await init();
}
window.addEventListener('pywebviewready', initSafe);
if (document.readyState === 'complete' || document.readyState === 'interactive') setTimeout(initSafe, 100);
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
        self.current_region = "EU"
        self.current_port = 18080
        self.current_warp_service = None
        self.opera_proxies_cache = {}
        self.settings = {"region": "EU", "port": 18080}
        self._settings_lock = threading.Lock()

        self._warp_lock = threading.Lock()
        self._opera_lock = threading.Lock()
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
                        log.warning("settings.json повреждён, используем значения по умолчанию")
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
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings_copy, f, ensure_ascii=False, indent=2)
            log.info(f"Настройки сохранены: {self.settings}")
            return {"ok": True}
        except Exception as e:
            log.error(f"save_settings error: {e}")
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
        if need_cleanup:
            self._disable_system_proxy()

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
            "opera_region": self.current_region,
            "opera_port":   self.current_port,
            "warp_info":    warp_info,
            "server_count": server_count,
        })

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
                        stdout_data.append(line)
                except Exception:
                    pass

            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stdout_thread = threading.Thread(target=read_stdout, daemon=True)
            stderr_thread.start()
            stdout_thread.start()

            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                log.warning(f"opera-proxy -list-proxies таймаут (30 сек)")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()

            stderr_thread.join(timeout=2)
            stdout_thread.join(timeout=2)

            try: proc.stdout.close()
            except Exception: pass
            try: proc.stderr.close()
            except Exception: pass

            stderr_text = "".join(stderr_data)
            stdout = decode_output(b"".join(stdout_data))

            if stderr_text:
                log.info(f"opera-proxy -list-proxies stderr:\n{stderr_text}")
            log.info(f"opera-proxy -list-proxies stdout ({len(stdout)} bytes):\n{stdout}")

            if "801" in stderr_text or "CSV fallback" in stderr_text:
                log.warning(f"Регион {region}: API вернул 801 (нет серверов)")
                return []

            if proc.returncode != 0:
                log.error(f"opera-proxy вернул код {proc.returncode}")
                return []

            servers = []
            csv_pattern = re.compile(
                r'^([A-Z]{2}),([^,]*),([a-zA-Z0-9.\-]+),(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}),(\d{1,5})$'
            )
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                m = csv_pattern.match(line)
                if m:
                    country_code, country_name, host, ip, port = m.groups()
                    octets = ip.split('.')
                    if all(0 <= int(o) <= 255 for o in octets):
                        servers.append({
                            "country": country_code,
                            "host": host,
                            "ip": ip,
                            "port": port,
                        })

            log.info(f"Получено {len(servers)} серверов для {region}")
            if servers:
                self.opera_proxies_cache[region] = {
                    "servers": servers,
                    "timestamp": time.time(),
                }
            return servers
        except Exception as e:
            log.exception(f"Ошибка получения списка серверов: {e}")
            return []

    # ---------- Opera Proxy: подключение ----------
    def start_connect(self, region=None, port=None):
        threading.Thread(target=self._do_connect_opera, args=(region, port), daemon=True).start()
        return {"ok": True}

    def _do_connect_opera(self, region, port):
        acquired = self._opera_lock.acquire(blocking=True, timeout=3)
        if not acquired:
            log.warning("Opera: уже идёт операция")
            self._js("onOperaStatus", {
                "status": self.opera_status,
                "message": "Дождитесь завершения текущей операции",
            })
            return
        try:
            region = region or self.current_region
            port   = int(port or self.current_port)

            if region not in OPERA_REGIONS:
                raise RuntimeError(f"Регион {region} не поддерживается")

            servers = self._get_opera_proxies(region)
            if not servers:
                raise RuntimeError(
                    f"Для региона {region} нет доступных серверов. "
                    f"Попробуйте другой регион (EU, AS, AM)."
                )

            exe = get_resource_path(OPERA_EXE)
            if not os.path.exists(exe):
                raise RuntimeError(f"Файл {OPERA_EXE} не найден")

            self._kill_opera_process()
            time.sleep(0.5)

            if self._port_open("127.0.0.1", port):
                raise RuntimeError(f"Порт {port} уже занят другим приложением")

            bind = f"127.0.0.1:{port}"
            log.info(f"Запуск opera-proxy: {exe} -country {region} -bind-address {bind}")
            log.info(f"Серверов в регионе {region}: {len(servers)}")

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

            proc = subprocess.Popen(
                [exe, "-country", region, "-bind-address", bind],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
            )
            with self._process_lock:
                self.opera_process = proc

            self.opera_status = "connecting"
            ready = False
            last_stderr = ""
            for i in range(300):
                time.sleep(0.2)
                with self._process_lock:
                    current_proc = self.opera_process
                if current_proc is None or current_proc is not proc:
                    log.warning("opera_process был изменён другим потоком")
                    return
                try:
                    rc = current_proc.poll()
                except Exception:
                    rc = None
                if rc is not None:
                    try:
                        _, err = current_proc.communicate(timeout=2)
                        last_stderr = decode_output(err).strip()
                    except Exception:
                        last_stderr = ""
                    log.error(f"opera-proxy умер с кодом {rc}: {last_stderr[:500]}")
                    raise RuntimeError(
                        f"opera-proxy завершился (код {rc}). "
                        f"{'Причина: ' + last_stderr[:200] if last_stderr else 'Проверьте регион.'}"
                    )
                if self._port_open("127.0.0.1", port):
                    ready = True
                    log.info(f"Порт {port} слушается на итерации {i}")
                    break

            if not ready:
                try:
                    with self._process_lock:
                        current_proc = self.opera_process
                    if current_proc is not None:
                        current_proc.terminate()
                        _, err = current_proc.communicate(timeout=3)
                        last_stderr = decode_output(err).strip()
                except Exception:
                    pass
                raise RuntimeError(
                    f"Таймаут ожидания порта (60 сек). "
                    f"{'Причина: ' + last_stderr[:200] if last_stderr else 'Возможно, регион недоступен.'}"
                )

            self._enable_system_proxy(bind)
            self.opera_status = "connected"
            self.current_region = region
            self.current_port = port
            self._js("onOperaStatus", {
                "status": "connected",
                "message": f"Opera Proxy активен ({region}, {len(servers)} серверов)",
                "server_count": len(servers),
            })
            log.info(f"Opera Proxy успешно запущен ({len(servers)} серверов)")
        except Exception as e:
            log.exception("Ошибка запуска Opera Proxy")
            self.opera_status = "error"
            self._kill_opera_process()
            self._disable_system_proxy()
            self._js("onOperaStatus", {"status": "error", "message": f"Ошибка: {e}"})
        finally:
            self._opera_lock.release()

    def _port_open(self, host, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True
        except Exception:
            return False
        finally:
            try: s.close()
            except Exception: pass

    def start_disconnect(self):
        threading.Thread(target=self._do_disconnect_opera, daemon=True).start()
        return {"ok": True}

    def _do_disconnect_opera(self):
        acquired = self._opera_lock.acquire(blocking=True, timeout=3)
        if not acquired:
            self._js("onOperaStatus", {
                "status": self.opera_status,
                "message": "Дождитесь завершения текущей операции",
            })
            return
        try:
            self._kill_opera_process()
            self._disable_system_proxy()
            self.opera_status = "disconnected"
            self._js("onOperaStatus", {"status": "disconnected", "message": "Opera Proxy отключён"})
            log.info("Opera Proxy остановлен")
        except Exception as e:
            log.exception("Ошибка отключения Opera Proxy")
            self._js("onOperaStatus", {"status": "error", "message": f"Ошибка: {e}"})
        finally:
            self._opera_lock.release()

    def _kill_opera_process(self):
        proc = None
        with self._process_lock:
            proc = self.opera_process
            self.opera_process = None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", OPERA_EXE],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            pass

    def _enable_system_proxy(self, bind):
        if winreg is None:
            log.warning("winreg недоступен")
            return
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROXY_REG_PATH, 0,
                                 winreg.KEY_WRITE | winreg.KEY_READ) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, bind)
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "localhost;127.*;<local>")
            self._notify_ie_settings_changed()
            log.info(f"Системный прокси включён: {bind}")
        except Exception as e:
            log.exception(f"Не удалось включить системный прокси: {e}")

    def _disable_system_proxy(self):
        if winreg is None:
            return
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROXY_REG_PATH, 0,
                                 winreg.KEY_WRITE | winreg.KEY_READ) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            self._notify_ie_settings_changed()
            log.info("Системный прокси отключён")
        except Exception as e:
            log.exception(f"Не удалось отключить системный прокси: {e}")

    def _notify_ie_settings_changed(self):
        try:
            INTERNET_OPTION_SETTINGS_CHANGED = 39
            INTERNET_OPTION_REFRESH = 37
            ctypes.windll.Wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
            ctypes.windll.Wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
        except Exception as e:
            log.debug(f"InternetSetOptionW failed: {e}")

    # ---------- WARP ----------
    def _warp_conf_path(self):
        base = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()), "VPNClient")
        try: os.makedirs(base, exist_ok=True)
        except Exception: pass
        return os.path.join(base, WARP_CONF_NAME)

    def start_generate_warp(self):
        threading.Thread(target=self._do_generate_warp, daemon=True).start()
        return {"ok": True}

    def _download_file(self, url, dest):
        log.info(f"Загрузка {url} -> {dest}")
        batch = b""
        def rep(block, count, total):
            nonlocal batch
            downloaded = block * count
            if total > 0:
                pct = int(downloaded * 100 / total)
                if pct % 10 == 0 or pct == 0:
                    self._js("onWarpStatus", {
                        "status": "connecting",
                        "message": f"Загрузка AmneziaWG... {pct}%",
                    })
        try:
            urllib.request.urlretrieve(url, dest, rep)
            log.info(f"Загрузка завершена: {os.path.getsize(dest)} байт")
        except Exception as e:
            log.error(f"Ошибка загрузки {url}: {e}")
            raise

    def _ensure_amnezia_wg(self):
        path = find_amnezia_exe()
        if path and os.path.exists(path):
            return path

        self._js("onWarpStatus", {
            "status": "connecting",
            "message": "AmneziaWG не найден. Начинаем установку...",
        })

        arch = _amnezia_arch()
        msi_url = AMNEZIAWG_MSI_URL.format(arch=arch)
        msi_path = os.path.join(tempfile.gettempdir(), os.path.basename(msi_url))

        self._download_file(msi_url, msi_path)

        self._js("onWarpStatus", {
            "status": "connecting",
            "message": "Установка AmneziaWG...",
        })
        log.info(f"Установка AmneziaWG: msiexec /quiet /i {msi_path}")
        r = subprocess.run(
            ["msiexec", "/quiet", "/i", msi_path, "DO_NOT_LAUNCH=1"],
            capture_output=True, timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        stdout = decode_output(r.stdout)
        stderr = decode_output(r.stderr)
        log.info(f"msiexec: rc={r.returncode} stdout='{stdout}' stderr='{stderr}'")
        if r.returncode not in (0, 1641, 3010):
            raise RuntimeError(
                f"Ошибка установки AmneziaWG (код {r.returncode}). "
                f"Установите вручную: github.com/amnezia-vpn/amneziawg-windows-client"
            )

        path = find_amnezia_exe()
        if path:
            log.info(f"Установка AmneziaWG в {path}: /installmanagerservice")
            subprocess.run(
                [path, "/installmanagerservice"],
                capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

        try: os.remove(msi_path)
        except Exception: pass

        path = find_amnezia_exe()
        if path and os.path.exists(path):
            self._js("onWarpStatus", {
                "status": "connecting",
                "message": "AmneziaWG успешно установлен",
            })
            global AMNEZIA_EXE
            AMNEZIA_EXE = path
            return path

        raise RuntimeError(
            "AmneziaWG установлен, но amneziawg.exe не найден. "
            "Попробуйте перезапустить приложение."
        )

    def _do_generate_warp(self):
        acquired = self._warp_lock.acquire(blocking=True, timeout=3)
        if not acquired:
            log.warning("WARP: уже идёт операция")
            self._js("onWarpStatus", {
                "status": self.warp_status,
                "message": "Дождитесь завершения текущей операции",
            })
            return
        try:
            exe = get_resource_path(WARP_GEN_EXE)
            if not os.path.exists(exe):
                self._js("onWarpStatus", {
                    "status": "error",
                    "message": f"Файл {WARP_GEN_EXE} не найден.",
                })
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
            self._js("onWarpStatus", {
                "status": "error",
                "message": f"Ошибка генерации WARP: {e}",
            })
        finally:
            self._warp_lock.release()

    def start_connect_warp(self):
        threading.Thread(target=self._do_connect_warp, daemon=True).start()
        return {"ok": True}

    def _do_connect_warp(self):
        acquired = self._warp_lock.acquire(blocking=True, timeout=3)
        if not acquired:
            log.warning("WARP: уже идёт операция")
            self._js("onWarpStatus", {
                "status": self.warp_status,
                "message": "Дождитесь завершения текущей операции",
            })
            return
        try:
            if not is_admin():
                self._js("onWarpStatus", {
                    "status": "error",
                    "message": "Требуются права администратора.",
                })
                return

            amnezia_path = self._ensure_amnezia_wg()
            if not amnezia_path:
                return

            conf = self._warp_conf_path()
            if not os.path.exists(conf):
                self._js("onWarpStatus", {
                    "status": "error",
                    "message": "Сначала сгенерируйте WARP-конфиг",
                })
                return

            self.warp_status = "connecting"
            self._js("onWarpStatus", {"status": "connecting", "message": "Устанавливаем WARP-туннель..."})

            # Проверить, не установлен ли уже сервис туннеля
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

            q_check = sc_run("query", new_service, timeout=10)
            already_running = bool(re.search(r"(?:STATE|СОСТОЯНИЕ)\s*:\s*4\b", q_check.stdout_decoded, re.IGNORECASE))
            if already_running:
                log.info(f"Сервис {new_service} уже RUNNING, sc start не нужен")
            else:
                r2 = sc_run("start", new_service, timeout=15)
                log.info(f"sc start: rc={r2.returncode} out='{r2.stdout_decoded.strip()}'")
                if r2.returncode != 0 and r2.returncode != 1056:
                    err_msg = (r2.stderr_decoded or r2.stdout_decoded).strip()
                    raise RuntimeError(f"sc start failed (rc={r2.returncode}): {err_msg}")
                if r2.returncode == 1056:
                    log.info("sc start: 1056 — служба уже запущена (установщик авто-запустил)")

            running = False
            for i in range(60):
                sleep_time = 0.2 if i < 5 else 0.5
                time.sleep(sleep_time)
                q = sc_run("query", new_service, timeout=10)
                output = q.stdout_decoded
                log.debug(f"sc query output (i={i}): {output[:300]}")
                if re.search(r"(?:STATE|СОСТОЯНИЕ)\s*:\s*4\b", output, re.IGNORECASE):
                    running = True
                    log.info(f"Сервис RUNNING на попытке {i}")
                    break
                if re.search(r"(?:STATE|СОСТОЯНИЕ)\s*:\s*1\b", output, re.IGNORECASE):
                    m = re.search(r"(?:WIN32_EXIT_CODE|КОД_ВЫХОДА_WIN32|Код_выхода_Win32)\s*:\s*(\d+)", output, re.IGNORECASE)
                    code = m.group(1) if m else "?"
                    ev_log = self._read_event_log()
                    raise RuntimeError(
                        f"Сервис остановился (код {code}). "
                        f"Event Log: {ev_log}"
                    )

            if not running:
                raise RuntimeError(f"Сервис {new_service} не перешёл в RUNNING за 30 секунд (реальное ожидание: 28.5 с)")

            self.warp_status = "connected"
            self._js("onWarpStatus", {
                "status": "connected",
                "message": "WARP туннель активен",
            })
            log.info(f"WARP подключён через сервис {new_service}")
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
        acquired = self._warp_lock.acquire(blocking=True, timeout=3)
        if not acquired:
            self._js("onWarpStatus", {
                "status": self.warp_status,
                "message": "Дождитесь завершения текущей операции",
            })
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

    def _read_event_log(self, log_name="Application", max_age_hours=1):
        try:
            ps_cmd = (
                f'Get-WinEvent -FilterHashtable @{{LogName="{log_name}";'
                f'ProviderName="AmneziaWG";StartTime=(Get-Date).AddHours(-{max_age_hours})}} '
                f'-MaxEvents 5 | Format-List TimeCreated,LevelDisplayName,Message'
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            out = (r.stdout or "").strip()
            return out[:500] if out else "No AmneziaWG events found"
        except Exception as e:
            return f"Event log read error: {e}"

    def _find_amnezia_service(self):
        try:
            r = sc_run("queryex", "type=", "service", "state=", "all", timeout=20)
            output = r.stdout_decoded
            for line in output.splitlines():
                line_s = line.strip()
                if line_s.upper().startswith("SERVICE_NAME:") or "\u0418\u041c\u042f_\u0421\u041b\u0423\u0416\u0411\u042b" in line_s.upper():
                    name = line_s.split(":", 1)[1].strip()
                    if "AmneziaWGTunnel$" in name:
                        return name
        except Exception as e:
            log.warning(f"_find_amnezia_service error: {e}")
        return None

    def _force_cleanup_amnezia_services(self):
        try:
            r = sc_run("queryex", "type=", "service", "state=", "all", timeout=20)
            output = r.stdout_decoded
            services = []
            for line in output.splitlines():
                line_s = line.strip()
                if line_s.upper().startswith("SERVICE_NAME:") or "\u0418\u041c\u042f_\u0421\u041b\u0423\u0416\u0411\u042b" in line_s.upper():
                    name = line_s.split(":", 1)[1].strip()
                    if "AmneziaWGTunnel$" in name or "amneziawg" in name.lower():
                        services.append(name)

            conf_name = os.path.splitext(os.path.basename(self._warp_conf_path()))[0]
            services.append(f"AmneziaWGTunnel${conf_name}")
            if hasattr(self, "current_warp_service") and self.current_warp_service:
                services.append(self.current_warp_service)
            services = list(dict.fromkeys(services))

            for proc in ("amneziawg-go.exe", "amneziawg.exe"):
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/IM", proc],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass

            for svc in services:
                log.info(f"Останавливаем и удаляем: {svc}")
                sc_run("stop", svc, timeout=10)
                time.sleep(0.5)
                r = sc_run("delete", svc, timeout=10)
                log.info(f"sc delete {svc}: rc={r.returncode}")
                if r.returncode == 0:
                    for wait_i in range(10):
                        time.sleep(0.3)
                        check = sc_run("query", svc, timeout=5)
                        if "not found" in check.stdout_decoded.lower() or "does not exist" in check.stdout_decoded.lower() or check.returncode == 1060:
                            log.info(f"Сервис {svc} реально удалён (попытка {wait_i})")
                            break
        except Exception as e:
            log.warning(f"_force_cleanup_amnezia_services: {e}")

    # ---------- Ping ----------
    def start_ping(self, region=None):
        threading.Thread(target=self._do_ping, args=(region,), daemon=True).start()
        return {"ok": True}

    def _do_ping(self, region):
        region = region or self.current_region
        try:
            if region not in OPERA_REGIONS:
                self._js("onPingResult", {"error": f"Регион {region} не поддерживается"})
                return

            servers = self._get_opera_proxies(region)
            if not servers:
                self._js("onPingResult", {
                    "error": f"Для региона {region} нет доступных серверов. "
                             f"Попробуйте EU или AM."
                })
                return

            results = []
            for server in servers[:3]:
                ip = server["ip"]
                host = server["host"]
                log.info(f"Пингуем {ip} ({host})")
                elapsed = self._tcp_ping(ip, 443, timeout=4)
                if elapsed is not None:
                    log.info(f"TCP ping {ip}: {elapsed} мс")
                    results.append((elapsed, host, ip))
                else:
                    log.debug(f"TCP ping {ip} не ответил")
                    self._js("onPingProgress", {"server": f"{host} ({ip})", "status": "timeout"})

            if not results:
                self._js("onPingResult", {
                    "error": "Серверы не отвечают. Попробуйте EU или другой регион."
                })
                return

            results.sort(key=lambda x: x[0])
            best_ping, best_host, best_ip = results[0]
            log.info(f"Минимальная задержка: {best_ping} мс ({best_host})")
            self._js("onPingResult", {
                "ping": best_ping,
                "server": f"{best_host} ({best_ip})",
                "tested": len(results),
            })
        except Exception as e:
            log.exception("Ошибка пинга")
            self._js("onPingResult", {"error": f"Ошибка: {e}"})

    def _tcp_ping(self, host: str, port: int = 443, timeout: int = 4):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        start = time.time()
        try:
            s.connect((host, port))
            elapsed = int((time.time() - start) * 1000)
            return elapsed
        except Exception:
            return None
        finally:
            try: s.close()
            except Exception: pass

    # ---------- Force kill ----------
    def force_kill_all(self):
        threading.Thread(target=self._do_force_kill, daemon=True).start()
        return {"ok": True}

    def _do_force_kill(self):
        log.warning("FORCE KILL")
        try: self._kill_opera_process()
        except Exception as e: log.warning(f"force_kill opera: {e}")
        try: self._disable_system_proxy()
        except Exception as e: log.warning(f"force_kill proxy: {e}")
        try: self._force_cleanup_amnezia_services()
        except Exception as e: log.warning(f"force_kill warp: {e}")
        self.opera_status = "disconnected"
        self.warp_status  = "disconnected"

    def shutdown(self):
        log.info("Graceful shutdown...")
        try:
            if self.opera_status == "connected":
                self._kill_opera_process()
                self._disable_system_proxy()
        except Exception as e:
            log.warning(f"shutdown opera: {e}")
        try:
            if self.warp_status == "connected":
                self._force_cleanup_amnezia_services()
        except Exception as e:
            log.warning(f"shutdown warp: {e}")


# ---------------------------------------------------------------------------
# Утилита для sc.exe (управление службами Windows)
# ---------------------------------------------------------------------------
@dataclass
class ScResult:
    returncode: int
    stdout_decoded: str = ""
    stderr_decoded: str = ""

def sc_run(*args, timeout=30):
    try:
        r = subprocess.run(
            ["sc.exe"] + [a for a in args if a],
            capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return ScResult(
            returncode=r.returncode,
            stdout_decoded=decode_output(r.stdout or b""),
            stderr_decoded=decode_output(r.stderr or b""),
        )
    except subprocess.TimeoutExpired:
        return ScResult(returncode=-1, stdout_decoded="", stderr_decoded="timeout")
    except FileNotFoundError:
        return ScResult(returncode=-2, stdout_decoded="", stderr_decoded="sc.exe not found")
    except Exception as e:
        return ScResult(returncode=-3, stdout_decoded="", stderr_decoded=str(e))


# ---------------------------------------------------------------------------
# System Tray
# ---------------------------------------------------------------------------
import pystray
from PIL import Image as PILImage


class TrayManager:
    def __init__(self, window, api):
        self.window = window
        self.api = api
        self.icon = None
        self._icon_path = get_resource_path("IMG/icon.ico")
        self._running = threading.Event()
        self._thread = None

    def _create_image(self):
        try:
            if os.path.exists(self._icon_path):
                return PILImage.open(self._icon_path)
        except Exception as e:
            log.warning(f"Не удалось загрузить иконку для трея: {e}")
        img = PILImage.new("RGBA", (64, 64), (124, 92, 255, 255))
        return img

    def _on_show(self, icon, item):
        try:
            self.window.show()
            self.window.on_top()
        except Exception as e:
            log.warning(f"show: {e}")

    def _on_exit(self, icon, item):
        try:
            self.api.shutdown()
        except Exception as e:
            log.warning(f"shutdown: {e}")
        try:
            self.window.destroy()
        except Exception:
            pass
        if self.icon:
            self.icon.stop()

    def _setup(self, icon):
        self.icon = icon

    def start(self):
        def run():
            try:
                image = self._create_image()
                menu = pystray.Menu(
                    pystray.MenuItem("Показать VPN Client", self._on_show, default=True),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Выход", self._on_exit),
                )
                self.icon = pystray.Icon("vpn-client", image, "VPN Client", menu)
                self.icon.run()
            except Exception as e:
                log.error(f"Ошибка трея: {e}")

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def on_closing(api, window):
    try:
        log.info("Окно закрыто, приложение свёрнуто в трей")
        window.hide()
    except Exception as e:
        log.warning(f"on_closing hide: {e}")
    return False  # отменяем закрытие, скрываем окно


def main():
    log.info(f"Запуск {APP_NAME} v{APP_VERSION}")
    log.info(f"Python: {sys.version.split()[0]}, frozen={getattr(sys, 'frozen', False)}")
    log.info(f"Admin: {is_admin()}")
    log.info(f"AmneziaWG: {AMNEZIA_EXE or 'не найден'}")

    # Сбросить потенциально зависший прокси от предыдущего запуска
    try:
        if winreg is not None:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROXY_REG_PATH, 0,
                                 winreg.KEY_WRITE | winreg.KEY_READ) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            ctypes.windll.Wininet.InternetSetOptionW(0, 39, 0, 0)
            ctypes.windll.Wininet.InternetSetOptionW(0, 37, 0, 0)
    except Exception as e:
        log.warning(f"Не удалось сбросить системный прокси при старте: {e}")

    window = webview.create_window(
        APP_NAME,
        html=HTML,
        width=480,
        height=800,
        resizable=True,
        min_size=(420, 700),
        text_select=False,
    )

    api = Api(window)
    window.expose(api.get_version, api.get_settings, api.save_settings,
                  api.get_status, api.start_connect, api.start_disconnect,
                  api.start_generate_warp, api.start_connect_warp,
                  api.start_disconnect_warp, api.start_ping, api.force_kill_all)

    tray = TrayManager(window, api)
    tray.start()

    window.events.closing += lambda: on_closing(api, window)

    try:
        webview.start(debug="--debug" in sys.argv, gui="edgechromium")
    except Exception as e:
        log.warning(f"edgechromium недоступен: {e}")
        webview.start(debug="--debug" in sys.argv)
    finally:
        tray.stop()


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
            messagebox.showerror(APP_NAME, f"Критическая ошибка:\n{e}\n\nСм. лог: {LOG_FILE}")
        except Exception:
            pass
        sys.exit(1)
