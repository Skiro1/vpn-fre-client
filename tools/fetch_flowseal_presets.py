# -*- coding: utf-8 -*-
"""
Fetches and converts Flowseal/zapret-discord-youtube general*.bat configs
into the VPN-Client .bat format (no service.bat dependency, %BIN%/%LISTS% vars).

Output (all prefixed with "z1 - " so they sort together with the other v1
presets in the GUI):
    zapret/z1 - general (ALT).bat
    zapret/z1 - general (FAKE TLS AUTO).bat
    zapret/z1 - general (SIMPLE FAKE).bat
    ... and all other general*.bat files
"""
import os
import re
import sys
import shutil
import zipfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_V1 = ROOT / "zapret"
FLOWSEAL_LATEST = "https://api.github.com/repos/Flowseal/zapret-discord-youtube/releases/latest"
TARGET_VERSION_HINT = "1.9.9a"


def get_latest_release_url():
    """Return (tag, asset_url) for the latest Flowseal release zip."""
    try:
        req = urllib.request.Request(FLOWSEAL_LATEST,
                                     headers={"User-Agent": "vpn-client",
                                              "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
        import json
        rel = json.loads(data)
        zip_asset = next((a for a in rel.get("assets", []) if a["name"].endswith(".zip")), None)
        if zip_asset:
            return rel["tag_name"], zip_asset["browser_download_url"]
    except Exception as e:
        print(f"[!] GitHub API failed: {e}")
    return TARGET_VERSION_HINT, (
        f"https://github.com/Flowseal/zapret-discord-youtube/releases/download/"
        f"{TARGET_VERSION_HINT}/zapret-discord-youtube-{TARGET_VERSION_HINT}.zip"
    )


def fetch_and_extract(url, tag):
    """Download zip and extract to a temp dir; return the temp dir path."""
    tmpdir = Path(tempfile.gettempdir()) / "vpn_client_flowseal_cache"
    extract_dir = tmpdir / f"flowseal-{tag}"
    if extract_dir.exists():
        print(f"  [cache] using existing {extract_dir}")
        return extract_dir
    tmpdir.mkdir(parents=True, exist_ok=True)
    zip_path = tmpdir / f"flowseal-{tag}.zip"
    print(f"  [download] {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "vpn-client"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        zip_path.write_bytes(resp.read())
    print(f"  [extract] -> {extract_dir}")
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)
    return extract_dir


def find_lists_dir(root: Path) -> Path | None:
    """The Flowseal archive extracts flat - lists/ is directly inside root."""
    cand = root / "lists"
    if cand.is_dir():
        return cand
    for d in root.rglob("lists"):
        if d.is_dir():
            return d
    return None


def find_bat_files(root: Path) -> list[Path]:
    return sorted([p for p in root.glob("*.bat") if p.is_file()])


def convert_flowseal_bat(content: str, name: str, lists_dir_name: str = "lists") -> str:
    """
    Convert a Flowseal .bat (which depends on service.bat and call statements)
    to a self-contained VPN-Client .bat using %BIN% / %LISTS% markers.

    Strips:
        - call service.bat <...>  (we inline the game filter + user lists)
        - %~dp0 substitution (replaced with %BIN% / %LISTS%)
    Keeps:
        - start /min "%BIN%winws.exe" ... (replaces %BIN% literally)
        - list-general.txt / list-google.txt etc.
    """
    out_lines = [
        "@echo off",
        "chcp 65001 > nul",
        ":: 65001 - UTF-8",
        ":: ZAPRET_VERSION=1",
        f":: Source: Flowseal/zapret-discord-youtube ({name})",
        "",
        "cd /d \"%~dp0\"",
        "",
    ]

    # Build a synthetic service.bat in memory
    out_lines.extend([
        # GameFilterTCP / GameFilterUDP - Flowseal default: empty when disabled.
        # In VPN-Client we hardcode 12 (a single sentinel port) so that winws
        # never sees --filter-tcp=, / --wf-tcp= with an empty value.
        'set "GameFilterTCP=12"',
        'set "GameFilterUDP=12"',
        "",
    ])

    # Find the start of the winws invocation.
    # Flowseal bats do `cd /d %BIN%` and then `start "..." /min "%BIN%winws.exe" --wf-tcp=...`
    # We just want everything from "start" (inclusive) to the end of the file,
    # but with %BIN% and %LISTS% already expanded and a fixed GameFilter=12.
    started = False
    for line in content.splitlines():
        s = line.rstrip()
        stripped = s.strip()
        if not started:
            # Flowseal uses `start "zapret: %~n0" /min "%BIN%winws.exe"`
            if stripped.lower().startswith("start") and "winws.exe" in stripped.lower():
                started = True
            else:
                continue
        if not stripped:
            continue
        # Skip "call service.bat" lines - we already inlined GameFilter
        if stripped.lower().startswith("call service.bat"):
            continue
        if stripped.lower().startswith("set \"bin=") or stripped.lower().startswith("set bin="):
            continue
        if stripped.lower().startswith("set \"lists=") or stripped.lower().startswith("set lists="):
            continue
        if stripped.lower().startswith("echo:"):
            continue
        # Strip the %~dp0 reference
        s = s.replace("%~dp0bin\\", "%BIN%").replace("%~dp0", "%BIN%")
        # Convert "lists/" path tokens to %LISTS%
        s = s.replace("\"%BIN%lists\\", "\"%LISTS%").replace("%BIN%lists\\", "%LISTS%")
        # Mark continuation lines (^ at end) for portability
        s = re.sub(r"\s*\^\s*$", " ^", s)
        out_lines.append(s)

    if not started:
        return ""
    out_lines.append("")
    return "\r\n".join(out_lines)


def main():
    tag, url = get_latest_release_url()
    print(f"[i] Flowseal release: {tag}")
    flow_root = fetch_and_extract(url, tag)
    lists_src = find_lists_dir(flow_root)
    if lists_src:
        print(f"  [lists] {lists_src}")
    bat_files = find_bat_files(flow_root)
    if not bat_files:
        print("[!] No .bat files found in Flowseal archive")
        return 1

    converted = 0
    for bat in bat_files:
        # We only want general*.bat (the pre-tuned Flowseal configs).
        # service.bat is the loader; we don't ship it because we inline GameFilter.
        low = bat.name.lower()
        if not (low.startswith("general") or low == "service.bat"):
            continue
        # The "service.bat" is for status_chk; skip it.
        if low == "service.bat":
            continue
        try:
            text = bat.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"  [ERR] reading {bat.name}: {e}")
            continue
        converted_bat = convert_flowseal_bat(text, bat.name)
        if not converted_bat:
            print(f"  [skip] {bat.name} (no winws invocation found)")
            continue
        out_path = OUT_V1 / f"z1 - {bat.name}"
        out_path.write_text(converted_bat, encoding="utf-8", newline="")
        print(f"  [ok]   {bat.name}  ->  {out_path.relative_to(ROOT)}")
        converted += 1

    print(f"\n[OK] Converted {converted} Flowseal .bat files -> {OUT_V1.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
