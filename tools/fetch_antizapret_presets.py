# -*- coding: utf-8 -*-
"""
Fetches and converts pumPCin/AntiZapret *.cmd configs into VPN-Client .bat format.
Strips the `1_` and `2_` prefixes and converts %~dp0 paths into %BIN%/%LISTS% vars.

Output (all prefixed with "z1 - " so they sort together with the other v1
presets in the GUI):
    zapret/z1 - antizapret (auto v1).bat
    zapret/z1 - antizapret (auto v2).bat
    zapret/z1 - antizapret (auto v3).bat
    zapret/z1 - antizapret (extended v1).bat
    zapret/z1 - antizapret (extended v2).bat
    zapret/z1 - antizapret (extended v3).bat
    zapret/z1 - antizapret (extended v4).bat
    zapret/z1 - antizapret (general v1).bat
    zapret/z1 - antizapret (general v2).bat
    zapret/z1 - antizapret (general v3).bat
    zapret/z1 - antizapret (general v4).bat
"""
import os
import re
import sys
import json
import zipfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_V1 = ROOT / "zapret"
API = "https://api.github.com/repos/pumPCin/AntiZapret/releases/latest"


def get_latest_release_url():
    try:
        req = urllib.request.Request(API,
                                     headers={"User-Agent": "vpn-client",
                                              "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
        rel = json.loads(data)
        zip_asset = next((a for a in rel.get("assets", []) if a["name"].endswith(".zip")), None)
        if zip_asset:
            return rel["tag_name"], zip_asset["browser_download_url"]
    except Exception as e:
        print(f"[!] GitHub API failed: {e}")
    return None, None


def fetch_and_extract(url, tag):
    tmpdir = Path(tempfile.gettempdir()) / "vpn_client_antizapret_cache"
    extract_dir = tmpdir / f"antizapret-{tag}"
    if extract_dir.exists():
        print(f"  [cache] using existing {extract_dir}")
        return extract_dir
    tmpdir.mkdir(parents=True, exist_ok=True)
    zip_path = tmpdir / f"antizapret-{tag}.zip"
    print(f"  [download] {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "vpn-client"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        zip_path.write_bytes(resp.read())
    print(f"  [extract] -> {extract_dir}")
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)
    return extract_dir


def find_root_with_cmds(extract_dir: Path) -> Path | None:
    """Find the directory containing `1_antizapret_*.cmd` files."""
    # Direct
    direct = [p for p in extract_dir.glob("1_antizapret_*.cmd")]
    if direct:
        return extract_dir
    # One level deeper
    for sub in extract_dir.iterdir():
        if sub.is_dir() and list(sub.glob("1_antizapret_*.cmd")):
            return sub
    return None


def parse_antizapret_name(name: str) -> str:
    """`1_antizapret_auto_v1.cmd` -> `antizapret (auto v1)`.

    Keeps spaces in the basename; VPN-Client's strategy filter is substring-based
    and case-insensitive, so it still finds these via `antizapret` lookup.
    """
    base = name
    if base.lower().endswith(".cmd"):
        base = base[:-4]
    if base.lower().endswith(".bat"):
        base = base[:-4]
    # Drop leading "1_" or "2_"
    base = re.sub(r"^[0-9]+_", "", base)
    # `antizapret_auto_v1` -> `antizapret (auto v1)` for nicer display
    m = re.match(r"^antizapret[ _]([a-z]+)[ _]v(\d+)$", base, re.IGNORECASE)
    if m:
        return f"antizapret ({m.group(1).lower()} v{m.group(2)})"
    # Fallback: just replace underscores with spaces
    return base.replace("_", " ")


def convert_antizapret_cmd(content: str) -> str:
    """Convert %~dp0 -> %BIN%/%LISTS%, change start line, add ZAPRET_VERSION marker."""
    out = [
        "@echo off",
        "chcp 65001 > nul",
        ":: 65001 - UTF-8",
        ":: ZAPRET_VERSION=1",
        ":: Source: pumPCin/AntiZapret",
        "",
        "cd /d \"%~dp0\"",
        "",
    ]
    started = False
    for line in content.splitlines():
        s = line.rstrip()
        stripped = s.strip()
        if not started:
            if stripped.lower().startswith("start") and "winws.exe" in stripped.lower():
                started = True
            else:
                continue
        if not stripped:
            continue
        # Replace %~dp0winws.exe -> %BIN%winws.exe
        s = s.replace("%~dp0winws.exe", "%BIN%winws.exe")
        # Replace %~dp0X.bin -> %BIN%X.bin
        s = re.sub(r'%~dp0([\w\-./\\]+\.bin)', r'%BIN%\1', s)
        # Replace %~dp0X.txt -> %LISTS%X.txt
        s = re.sub(r'%~dp0([\w\-./\\]+\.txt)', r'%LISTS%\1', s)
        # In case there's a remaining %~dp0 reference (other files), fall back to %BIN%
        s = s.replace("%~dp0", "%BIN%")
        # Mark continuation lines (^ at end) for portability
        s = re.sub(r"\s*\^\s*$", " ^", s)
        out.append(s)
    if not started:
        return ""
    out.append("")
    return "\r\n".join(out)


def main():
    tag, url = get_latest_release_url()
    if not url:
        print("[!] Could not resolve latest AntiZapret release")
        return 1
    print(f"[i] AntiZapret release: {tag}")
    extracted = fetch_and_extract(url, tag)
    src_dir = find_root_with_cmds(extracted)
    if not src_dir:
        print(f"[!] No antizapret .cmd files in {extracted}")
        return 1
    print(f"  [src] {src_dir}")

    converted = 0
    for cmd in sorted(src_dir.glob("1_antizapret_*.cmd")):
        try:
            text = cmd.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"  [ERR] reading {cmd.name}: {e}")
            continue
        bat = convert_antizapret_cmd(text)
        if not bat:
            print(f"  [skip] {cmd.name} (no winws invocation)")
            continue
        out_name = parse_antizapret_name(cmd.name) + ".bat"
        out_path = OUT_V1 / f"z1 - {out_name}"
        out_path.write_text(bat, encoding="utf-8", newline="")
        print(f"  [ok]   {cmd.name}  ->  {out_path.relative_to(ROOT)}")
        converted += 1

    print(f"\n[OK] Converted {converted} antizapret .cmd files -> {OUT_V1.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
