# -*- coding: utf-8 -*-
"""
tools/fetch_zapret_setup.py

Качает Zapret2Setup_*.exe (latest stable) с youtubediscord/zapret,
тихо распаковывает через Inno Setup /NSILENT, и копирует в наши
zapret/bin и zapret/zapret2/bin:
  - winws.exe  (v1)
  - winws2.exe (v2)
  - все .bin (fakes)
  - WinDivert.dll, cygwin1.dll

Также докачивает:
  - quic_initial_dbankcloud_ru.bin из Flowseal/zapret-discord-youtube 1.9.9a
  - list-extended.txt из pumPCin/AntiZapret

И копирует все .txt из инсталляторских lists/ в наши v1/v2 lists/.
"""
import os
import sys
import json
import shutil
import zipfile
import subprocess
import urllib.request
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
V1_BIN   = os.path.join(ROOT, "zapret", "bin")
V1_LISTS = os.path.join(ROOT, "zapret", "lists")
V2_BIN   = os.path.join(ROOT, "zapret", "zapret2", "bin")
V2_LISTS = os.path.join(ROOT, "zapret", "zapret2", "lists")
CACHE    = os.path.join(tempfile.gettempdir(), "vpn_client_zapret_cache")

GITHUB_API = "https://api.github.com/repos/{}/releases/latest"

REPOS = {
    "ytd":  "youtubediscord/zapret",
    "fs":   "Flowseal/zapret-discord-youtube",
    "ant":  "pumPCin/AntiZapret",
}


def log(msg):
    print("[fetch_zapret_setup] " + msg, flush=True)


def latest_release(repo):
    url = GITHUB_API.format(repo)
    req = urllib.request.Request(url, headers={"User-Agent": "vpn-client-setup"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data["tag_name"], data.get("assets", [])


def download(url, dst):
    log("  download " + url)
    req = urllib.request.Request(url, headers={"User-Agent": "vpn-client-setup"})
    with urllib.request.urlopen(req, timeout=300) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f)
    return os.path.getsize(dst)


def silent_install(exe_path, dest_dir, timeout=180):
    log("  silent install to " + dest_dir)
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir, ignore_errors=True)
    os.makedirs(dest_dir, exist_ok=True)
    args = [exe_path, "/SP-", "/SILENT", "/SUPPRESSMSGBOXES", "/DIR=" + dest_dir]
    # Inno Setup installer — GUI приложение. На Windows при вызове из
    # Python subprocess.run БЕЗ creationflags он может не получить корректный
    # shell context (видит "не-Silent" parent) и выйти с rc=2.
    # CREATE_NO_WINDOW + явный shell=False + capture_output даёт стабильный
    # silent install. Также логируем stdout/stderr для диагностики.
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            args,
            timeout=timeout,
            shell=False,
            capture_output=True,
            text=True,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"silent install timeout after {timeout}s") from e
    if proc.returncode != 0:
        out = (proc.stdout or "").strip()[-500:]
        err = (proc.stderr or "").strip()[-500:]
        log(f"  ! Inno Setup rc={proc.returncode}")
        if out:
            log(f"  ! stdout: {out}")
        if err:
            log(f"  ! stderr: {err}")
        raise RuntimeError("silent install failed: rc=" + str(proc.returncode))
    return dest_dir


def copytree_overlay(src_dir, dst_dir, globs, skip_if_dst_bigger_zero=True):
    """Копирует файлы по globs из src_dir в dst_dir, не затирая
    непустые существующие (защита user data в *-user.txt)."""
    copied = 0
    skipped = 0
    if not os.path.isdir(src_dir):
        return copied, skipped
    for fname in os.listdir(src_dir):
        if not any(fname.endswith(g) for g in globs):
            continue
        src = os.path.join(src_dir, fname)
        dst = os.path.join(dst_dir, fname)
        if os.path.exists(dst):
            if skip_if_dst_bigger_zero and os.path.getsize(dst) > 0:
                skipped += 1
                continue
            if os.path.getsize(dst) == os.path.getsize(src):
                skipped += 1
                continue
        shutil.copy2(src, dst)
        copied += 1
    return copied, skipped


def copy_file_to_bins(src, fname):
    """Копирует fname из src в v1 и v2 bin dirs (если есть)."""
    src_path = os.path.join(src, fname)
    if not os.path.exists(src_path):
        return False
    for dst_dir in (V1_BIN, V2_BIN):
        dst = os.path.join(dst_dir, fname)
        if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src_path):
            continue
        shutil.copy2(src_path, dst)
    return True


def fetch_ytd_setup():
    """Качает и распаковывает youtubediscord/zapret latest."""
    log("[1/4] youtubediscord/zapret latest release")
    tag, assets = latest_release(REPOS["ytd"])
    asset = next((a for a in assets if a["name"].lower().endswith(".exe")), None)
    if not asset:
        raise RuntimeError("No .exe asset in youtubediscord/zapret " + tag)
    log("  tag=" + tag + " asset=" + asset["name"])
    os.makedirs(CACHE, exist_ok=True)
    exe_path = os.path.join(CACHE, asset["name"])
    if not os.path.exists(exe_path) or os.path.getsize(exe_path) != asset["size"]:
        download(asset["browser_download_url"], exe_path)
    extract_dir = os.path.join(CACHE, "zapret_ytd_silent")
    silent_install(exe_path, extract_dir)

    # 1a) Copy .bin files
    src_bin = os.path.join(extract_dir, "bin")
    if not os.path.isdir(src_bin):
        # Альтернативный layout
        for cand in ("bin", "exe"):
            src_bin = os.path.join(extract_dir, cand)
            if any(f.endswith(".bin") for f in os.listdir(src_bin)):
                break
    copied, skipped = copytree_overlay(src_bin, V1_BIN, [".bin"])
    log(f"  .bin -> v1: copied={copied}, skipped={skipped}")
    copied, skipped = copytree_overlay(src_bin, V2_BIN, [".bin"])
    log(f"  .bin -> v2: copied={copied}, skipped={skipped}")

    # 1b) Copy .txt from lists/ to both lists dirs
    src_lists = os.path.join(extract_dir, "lists")
    if os.path.isdir(src_lists):
        for dst_dir in (V1_LISTS, V2_LISTS):
            os.makedirs(dst_dir, exist_ok=True)
        copied, skipped = copytree_overlay(src_lists, V1_LISTS, [".txt"])
        log(f"  .txt -> v1 lists: copied={copied}, skipped={skipped}")
        copied, skipped = copytree_overlay(src_lists, V2_LISTS, [".txt"])
        log(f"  .txt -> v2 lists: copied={copied}, skipped={skipped}")

    # 1c) Replace winws.exe (v1) and winws2.exe (v2)
    src_exe = os.path.join(extract_dir, "exe")
    if not os.path.isdir(src_exe):
        src_exe = extract_dir
    for src_name, dst_dir, exe_name in (
        ("winws.exe",  V1_BIN, "winws.exe"),
        ("winws2.exe", V2_BIN, "winws2.exe"),
    ):
        src = os.path.join(src_exe, src_name)
        if os.path.exists(src):
            dst = os.path.join(dst_dir, exe_name)
            if os.path.getsize(dst) != os.path.getsize(src):
                shutil.copy2(src, dst)
                log(f"  updated {exe_name} ({os.path.getsize(src)} bytes)")

    # 1d) WinDivert.dll КАЧАЕМ с Flowseal/zapret-discord-youtube (main branch),
    #     НЕ из ZaperSetup.
    #
    #     WinDivert64.sys в обоих источниках одинаковый (SHA-256 8DA08533...
    #     сертификат Sectigo истёк 2023-05-26), НО WinDivert.dll РАЗНЫЙ:
    #       - ZaperSetup  : 45568 байт — НЕ грузит .sys с истёкшим сертификатом
    #                       на Windows 11 + Secure Boot. Winws падает с
    #                       "windivert: error opening filter: The system cannot
    #                       find the file specified."
    #       - Flowseal    : 47616 байт — РАБОТАЕТ с тем же .sys (старая версия
    #                       DLL имеет иной путь проверки подписи).
    #     Поэтому берём DLL с Flowseal — пользователь подтвердил, что она
    #     грузит драйвер на Windows 11 + Secure Boot без отключения test signing.
    flowseal_dll_url = (
        "https://raw.githubusercontent.com/Flowseal/"
        "zapret-discord-youtube/main/bin/WinDivert.dll"
    )
    try:
        log("  downloading WinDivert.dll from Flowseal/zapret-discord-youtube...")
        req = urllib.request.Request(flowseal_dll_url,
                                     headers={"User-Agent": "vpn-client"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            dll_bytes = resp.read()
        for dst_dir in (V1_BIN, V2_BIN):
            dst = os.path.join(dst_dir, "WinDivert.dll")
            with open(dst, "wb") as fh:
                fh.write(dll_bytes)
            log(f"  installed WinDivert.dll in {dst_dir} ({len(dll_bytes)} bytes, Flowseal)")
    except Exception as e:
        # Fallback: используем DLL из ZaperSetup
        log(f"  [!] Flowseal download failed: {e}")
        log(f"      falling back to ZaperSetup WinDivert.dll (may not load on Secure Boot)")
        src_wd = os.path.join(src_exe, "WinDivert.dll")
        if os.path.exists(src_wd):
            for dst_dir in (V1_BIN, V2_BIN):
                dst = os.path.join(dst_dir, "WinDivert.dll")
                if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src_wd):
                    shutil.copy2(src_wd, dst)
                    log(f"  installed WinDivert.dll in {dst_dir} ({os.path.getsize(src_wd)} bytes, ZaperSetup)")

    # 1e) Copy windivert.filter/ directory contents to v1+v2 bin dirs
    #     ytd v72.2 winws грузит фильтры из CWD/windivert.filter/*.txt
    src_filter_dir = os.path.join(extract_dir, "windivert.filter")
    if os.path.isdir(src_filter_dir):
        for dst_dir in (V1_BIN, V2_BIN):
            dst_filter = os.path.join(dst_dir, "windivert.filter")
            if os.path.exists(dst_filter) and not os.path.isdir(dst_filter):
                os.remove(dst_filter)
            os.makedirs(dst_filter, exist_ok=True)
            for f in os.listdir(src_filter_dir):
                src = os.path.join(src_filter_dir, f)
                dst = os.path.join(dst_filter, f)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
        log("  copied windivert.filter/ -> v1+v2 bin")

    # 1f) Copy lua/ scripts to v1+v2 bin dirs (overlays @lua/ refs in .bat)
    src_lua = os.path.join(extract_dir, "lua")
    if os.path.isdir(src_lua):
        for dst_dir in (V1_BIN, V2_BIN):
            dst_lua = os.path.join(dst_dir, "lua")
            os.makedirs(dst_lua, exist_ok=True)
            for f in os.listdir(src_lua):
                src = os.path.join(src_lua, f)
                dst = os.path.join(dst_lua, f)
                if os.path.isfile(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
        log("  populated lua/ -> v1+v2 bin")


def fetch_flowseal_dbankcloud():
    """Качает quic_initial_dbankcloud_ru.bin из Flowseal 1.9.9a."""
    log("[2/4] Flowseal zapret-discord-youtube 1.9.9a (dbankcloud bin)")
    tag, assets = latest_release(REPOS["fs"])
    asset = next((a for a in assets if a["name"].endswith(".zip")), None)
    if not asset:
        raise RuntimeError("No .zip asset in Flowseal " + tag)
    log("  tag=" + tag + " asset=" + asset["name"])
    zip_path = os.path.join(CACHE, asset["name"])
    if not os.path.exists(zip_path) or os.path.getsize(zip_path) != asset["size"]:
        download(asset["browser_download_url"], zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("bin/quic_initial_dbankcloud_ru.bin") as src:
            data = src.read()
    for dst_dir in (V1_BIN, V2_BIN):
        dst = os.path.join(dst_dir, "quic_initial_dbankcloud_ru.bin")
        if os.path.exists(dst) and os.path.getsize(dst) == len(data):
            continue
        with open(dst, "wb") as f:
            f.write(data)
    log(f"  wrote quic_initial_dbankcloud_ru.bin ({len(data)} bytes) to v1+v2")


def fetch_antizapret_extended():
    """Качает list-extended.txt из pumPCin/AntiZapret."""
    log("[3/4] pumPCin/AntiZapret list-extended.txt")
    url = "https://raw.githubusercontent.com/pumPCin/AntiZapret/main/list-extended.txt"
    req = urllib.request.Request(url, headers={"User-Agent": "vpn-client-setup"})
    with urllib.request.urlopen(req, timeout=120) as r:
        text = r.read().decode("utf-8", errors="replace")
    for dst_dir in (V1_LISTS, V2_LISTS):
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, "list-extended.txt")
        with open(dst, "w", encoding="utf-8") as f:
            f.write(text)
    log(f"  wrote list-extended.txt ({len(text)} chars) to v1+v2 lists")


def ensure_user_lists():
    """Создаёт *-user.txt плейсхолдеры если их нет."""
    log("[4/4] ensure user-list placeholders")
    os.makedirs(V1_LISTS, exist_ok=True)
    os.makedirs(V2_LISTS, exist_ok=True)
    defaults = {
        "ipset-exclude-user.txt": "203.0.113.113/32\n",
        "list-general-user.txt":  "domain.example.abc\n",
        "list-exclude-user.txt":  "domain.example.abc\n",
    }
    for dst_dir in (V1_LISTS, V2_LISTS):
        for name, content in defaults.items():
            p = os.path.join(dst_dir, name)
            if not os.path.exists(p):
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)


def main():
    t0 = time.time()
    fetch_ytd_setup()
    fetch_flowseal_dbankcloud()
    fetch_antizapret_extended()
    ensure_user_lists()
    log("DONE in {:.1f}s".format(time.time() - t0))


if __name__ == "__main__":
    main()
