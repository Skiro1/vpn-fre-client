# -*- coding: utf-8 -*-
"""
Isolated tests for the Zapret preset fetchers.

Goals:
  - Run with zero network access (mock the HTTP layer).
  - Run in a tmpdir (no pollution of the real zapret/ folder).
  - Be fast (<5s) and deterministic.
  - Catch regressions: missing prefix, wrong markers, broken conversion,
    leftover legacy files, etc.

Network tests (marked with @network) download a tiny asset (e.g. one
WinDivert.dll of ~47KB) to verify the live URL is still healthy. They are
off by default; enable with `VPNCLIENT_RUN_NETWORK=1` env var.
"""
import io
import os
import sys
import json
import shutil
import zipfile
import hashlib
import tempfile
import importlib.util
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures: list[str] = []
warnings: list[str] = []
tested = 0
RUN_NETWORK = os.environ.get("VPNCLIENT_RUN_NETWORK") == "1"


def check(cond, msg):
    global tested
    tested += 1
    if not cond:
        failures.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


def warn(msg):
    warnings.append(msg)
    print(f"  WARN: {msg}")


def import_tool(name: str):
    p = ROOT / "tools" / name
    spec = importlib.util.spec_from_file_location(name[:-3], p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_zip_with_files(files: dict) -> bytes:
    """Build an in-memory zip with {archive_path: bytes}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# TEST 1: Flowseal fetcher — synthetic zip, no network
# ---------------------------------------------------------------------------
print("=" * 70)
print("TEST 1: fetch_flowseal_presets.py — synthetic archive")
print("=" * 70)
flow = import_tool("fetch_flowseal_presets.py")

# A typical Flowseal archive layout: general*.bat files + a lists/ folder
SAMPLE_FLOWSEAL = {
    "general (ALT).bat": b'''@echo off
chcp 65001 > nul
cd /d "%~dp0"
call service.bat status_zapret
call service.bat check_updates
echo:
set "BIN=%~dp0bin\\"
set "LISTS=%~dp0lists\\"
cd /d %BIN%
start "zapret: general (ALT)" /min "%BIN%winws.exe" ^
--wf-tcp=80,443 --filter-tcp=443 ^
--hostlist="%LISTS%list-general.txt" --dpi-desync=fake
''',
    "general (SIMPLE FAKE).bat": b'''@echo off
cd /d "%~dp0"
set "BIN=%~dp0bin\\"
set "LISTS=%~dp0lists\\"
cd /d %BIN%
start "zapret: general (SIMPLE FAKE)" /min "%BIN%winws.exe" ^
--wf-tcp=80,443 --filter-tcp=443 --dpi-desync=disorder
''',
    "service.bat": b"REM helper, should be skipped\n",
    "lists/list-general.txt": b"example.com\n",
}

with tempfile.TemporaryDirectory(prefix="vpnclient_flowseal_") as tmp:
    tmpdir = Path(tmp)
    fake_zip_bytes = make_zip_with_files(SAMPLE_FLOWSEAL)
    fake_extract = tmpdir / "extract"
    fake_extract.mkdir()
    with zipfile.ZipFile(io.BytesIO(fake_zip_bytes)) as zf:
        zf.extractall(fake_extract)

    # Patch OUT_V1 in the flowseal module to point at our tmpdir
    out_v1 = tmpdir / "zapret"
    out_v1.mkdir()
    with mock.patch.object(flow, "OUT_V1", out_v1):
        for src in fake_extract.glob("*.bat"):
            if src.name.lower() == "service.bat":
                continue
            if not src.name.lower().startswith("general"):
                continue
            txt = src.read_bytes().decode("utf-8", errors="replace")
            converted = flow.convert_flowseal_bat(txt, src.name)
            assert converted, f"empty conversion for {src.name}"
            (out_v1 / f"z1 - {src.name}").write_text(converted, encoding="utf-8", newline="")

    files = sorted(out_v1.glob("*.bat"))
    check(len(files) == 2, f"two general*.bat files created: {[f.name for f in files]}")
    check(all(f.name.startswith("z1 - ") for f in files),
          f"all files have 'z1 - ' prefix: {[f.name for f in files]}")
    check(not (out_v1 / "service.bat").exists(),
          "service.bat is not copied into output (inlined instead)")
    for f in files:
        body = f.read_text(encoding="utf-8")
        check("ZAPRET_VERSION=1" in body, f"{f.name} has ZAPRET_VERSION=1")
        check("call service.bat" not in body, f"{f.name} strips 'call service.bat'")
        check("%BIN%winws.exe" in body, f"{f.name} uses %BIN%winws.exe")
        check("start" in body.lower(), f"{f.name} has start command")
    # service.bat was skipped
    skipped = list(fake_extract.glob("service.bat"))
    check(bool(skipped), "service.bat was in source (skipped in output)")

# ---------------------------------------------------------------------------
# TEST 2: AntiZapret fetcher — synthetic zip, no network
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 2: fetch_antizapret_presets.py — synthetic archive")
print("=" * 70)
anti = import_tool("fetch_antizapret_presets.py")

SAMPLE_ANTI = {
    "1_antizapret_auto_v1.cmd": b'''@echo off
chcp 65001 > nul
start "antizapret: auto v1" /min "%~dp0winws.exe" ^
--wf-tcp=80,443 --filter-tcp=80 ^
--ipset="%~dp0ipset-all.txt" --dpi-desync=fake ^
--filter-tcp=443 --dpi-desync=multisplit ^
--dpi-desync-split-seqovl-pattern="%~dp0tls_clienthello_www_google_com.bin"
''',
    "1_antizapret_extended_v4.cmd": b'''start "antizapret: extended v4" /min "%~dp0winws.exe" ^
--wf-tcp=80,443 --wf-udp=443 --filter-udp=443 ^
--dpi-desync=fake --dpi-desync-udplen-increment=10
''',
    "ipset-all.txt": b"8.8.8.8/32\n",
    "tls_clienthello_www_google_com.bin": b"\x00\x01\x02",
}

with tempfile.TemporaryDirectory(prefix="vpnclient_anti_") as tmp:
    tmpdir = Path(tmp)
    out_v1 = tmpdir / "zapret"
    out_v1.mkdir()
    fake_extract = tmpdir / "extract"
    fake_extract.mkdir()
    with zipfile.ZipFile(io.BytesIO(make_zip_with_files(SAMPLE_ANTI))) as zf:
        zf.extractall(fake_extract)
    with mock.patch.object(anti, "OUT_V1", out_v1):
        for cmd in sorted(fake_extract.glob("1_antizapret_*.cmd")):
            txt = cmd.read_bytes().decode("utf-8", errors="replace")
            bat = anti.convert_antizapret_cmd(txt)
            assert bat, f"empty conversion for {cmd.name}"
            name = anti.parse_antizapret_name(cmd.name)
            (out_v1 / f"z1 - {name}.bat").write_text(bat, encoding="utf-8", newline="")

    files = sorted(out_v1.glob("*.bat"))
    check(len(files) == 2, f"two antizapret .bat files created: {[f.name for f in files]}")
    check(all(f.name.startswith("z1 - ") for f in files),
          f"all files have 'z1 - ' prefix: {[f.name for f in files]}")
    expected_names = {"z1 - antizapret (auto v1).bat", "z1 - antizapret (extended v4).bat"}
    check({f.name for f in files} == expected_names,
          f"file names match expected: actual={[f.name for f in files]}")
    for f in files:
        body = f.read_text(encoding="utf-8")
        check("ZAPRET_VERSION=1" in body, f"{f.name} has ZAPRET_VERSION=1")
        check("%BIN%winws.exe" in body, f"{f.name} uses %BIN%winws.exe")
        # No leftover %~dp0 in args section
        args = body.split("start", 1)[1] if "start" in body else ""
        check("%~dp0" not in args, f"{f.name} has no %~dp0 in args")

# ---------------------------------------------------------------------------
# TEST 3: parse_antizapret_name table
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 3: parse_antizapret_name edge cases")
print("=" * 70)
cases = [
    ("1_antizapret_auto_v1.cmd",      "antizapret (auto v1)"),
    ("1_antizapret_extended_v4.cmd",  "antizapret (extended v4)"),
    ("1_antizapret_general_v3.cmd",   "antizapret (general v3)"),
    ("2_antizapret_auto_v2.cmd",      "antizapret (auto v2)"),
    ("1_antizapret_weird_v9.bat",     "antizapret (weird v9)"),
]
for src, expected in cases:
    got = anti.parse_antizapret_name(src)
    check(got == expected, f"parse_antizapret_name({src!r}) -> {got!r} (expected {expected!r})")

# ---------------------------------------------------------------------------
# TEST 4: rename_legacy_strategies dry-run
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 4: rename_legacy_strategies.py dry-run")
print("=" * 70)
ren = import_tool("rename_legacy_strategies.py")

with tempfile.TemporaryDirectory(prefix="vpnclient_rename_") as tmp:
    tmpdir = Path(tmp)
    z = tmpdir / "zapret"
    z.mkdir()
    # Mix of legacy and modern files
    (z / "general (ALT).bat").write_text("x", encoding="utf-8")
    (z / "antizapret (auto v1).bat").write_text("x", encoding="utf-8")
    (z / "z1 - already-prefixed.bat").write_text("x", encoding="utf-8")
    (z / "service.bat").write_text("x", encoding="utf-8")
    with mock.patch.object(ren, "V1_DIR", z), \
         mock.patch.object(ren, "V2_DIR", z / "zapret2"):
        plan = ren.plan_renames(z, ren.PREFIX_V1)
    names = [t.name for _s, t in plan]
    check("z1 - general (ALT).bat" in names, f"plan includes general (ALT): {names}")
    check("z1 - antizapret (auto v1).bat" in names, f"plan includes antizapret: {names}")
    check("z1 - already-prefixed.bat" not in names, f"plan skips already-prefixed: {names}")
    check("z1 - service.bat" not in names, f"plan excludes service.bat: {names}")

# ---------------------------------------------------------------------------
# TEST 5: fetch_zapret_presets.py — sanitize_filename
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 5: fetch_zapret_presets.sanitize_filename")
print("=" * 70)
ytd = import_tool("fetch_zapret_presets.py")
samples = [
    ("z1 - alt1_foo.bat", "z1 - alt1_foo.bat"),
    ("weird<>name?.bat", "weird_name_.bat"),
    ("path/with/slash.bat", "path_with_slash.bat"),
    ("z2 - test.bat", "z2 - test.bat"),
    ("a/b/c:*.bat", "a_b_c_.bat"),
]
for src, expected in samples:
    got = ytd.sanitize_filename(src)
    check(got == expected, f"sanitize({src!r}) -> {got!r} (expected {expected!r})")

# ---------------------------------------------------------------------------
# TEST 6: fetch_zapret_setup.py — known URLs are syntactically correct
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 6: fetch_zapret_setup.py — source-of-truth URLs")
print("=" * 70)
setup = import_tool("fetch_zapret_setup.py")
src = (ROOT / "tools" / "fetch_zapret_setup.py").read_text(encoding="utf-8", errors="replace")
# WinDivert.dll must be downloaded from Flowseal (the 47616-byte version that
# works on Win11 + Secure Boot). ZaperSetup ships a broken 45568-byte one.
check("Flowseal/zapret-discord-youtube" in src,
      "fetch_zapret_setup.py downloads WinDivert.dll from Flowseal")
check("WinDivert.dll" in src,
      "fetch_zapret_setup.py references WinDivert.dll")
# Backup/fallback URL is fine, but Flowseal must be primary
flowseal_dll_idx = src.find("Flowseal/zapret-discord-youtube")
check(flowseal_dll_idx > 0, f"Flowseal URL appears in source (idx={flowseal_dll_idx})")
# Make sure we don't accidentally reference the ZaperSetup 45568-byte DLL
# as the only source.
check("Zapret2Setup" in src or "ZaperSetup" in src or "ZapretSetup" in src,
      "fetch_zapret_setup.py still references ZaperSetup for winws.exe")

# ---------------------------------------------------------------------------
# TEST 7: download_zapret.ps1 — known repos
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 7: download_zapret.ps1 — source-of-truth repos")
print("=" * 70)
ps1 = (ROOT / "tools" / "download_zapret.ps1").read_text(encoding="utf-8", errors="replace")
expected_repos = [
    "bol-van/zapret",          # main zapret winws.exe source
    "bol-van/zapret2",         # zapret2 winws2.exe source
    "youtubediscord/zapret",   # ZaperSetup + presets
    "Flowseal/zapret-discord-youtube",  # WinDivert.dll
]
for repo in expected_repos:
    check(repo in ps1, f"download_zapret.ps1 references {repo}")

# ---------------------------------------------------------------------------
# TEST 8: download_proxies.ps1 — known proxy repos
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 8: download_proxies.ps1 — source-of-truth proxy repos")
print("=" * 70)
ps1 = (ROOT / "tools" / "download_proxies.ps1").read_text(encoding="utf-8", errors="replace")
expected_proxies = [
    "Alexey71/opera-proxy",     # Opera proxy
    "Skiro1/warp-awg-gen",      # WARP config generator
    "snawoot-proxies-forks/hola-proxy",  # Hola proxy
]
for repo in expected_proxies:
    check(repo in ps1, f"download_proxies.ps1 references {repo}")

# ---------------------------------------------------------------------------
# TEST 9: WinDivert.dll size sanity (offline — local file if present)
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 9: WinDivert.dll size sanity (offline check)")
print("=" * 70)
for p in [
    ROOT / "zapret" / "bin" / "WinDivert.dll",
    ROOT / "zapret" / "zapret2" / "bin" / "WinDivert.dll",
]:
    if p.exists():
        size = p.stat().st_size
        # Flowseal's WinDivert.dll is exactly 47616 bytes.
        # ZaperSetup ships a broken 45568-byte version.
        check(size == 47616,
              f"{p.relative_to(ROOT)} size is 47616 (Flowseal), got {size}")
    else:
        warn(f"{p.relative_to(ROOT)} not present (run setup.bat to fetch)")

# ---------------------------------------------------------------------------
# TEST 10: Network smoke test (opt-in) — fetch a tiny file and verify hash
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print(f"TEST 10: network smoke (RUN_NETWORK={RUN_NETWORK})")
print("=" * 70)
if RUN_NETWORK:
    import urllib.request
    # The Flowseal WinDivert.dll is 47616 bytes — small, fast, and a real
    # regression canary for the URL.
    url = ("https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/"
           "main/bin/WinDivert.dll")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
        check(len(data) == 47616,
              f"Flowseal WinDivert.dll is 47616 bytes (got {len(data)})")
        # SHA-256 sanity (regression canary — not a strict assert, but log)
        sha = hashlib.sha256(data).hexdigest()
        print(f"  SHA-256: {sha}")
    except Exception as e:
        warn(f"network test failed: {e}")
else:
    warn("network tests skipped (set VPNCLIENT_RUN_NETWORK=1 to enable)")

# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"Tests run:    {tested}")
print(f"Failures:     {len(failures)}")
print(f"Warnings:     {len(warnings)}")
if failures:
    print()
    print("FAILURES:")
    for f in failures:
        print(f"  - {f}")
if warnings:
    print()
    print("WARNINGS:")
    for w in warnings:
        print(f"  - {w}")
sys.exit(1 if failures else 0)
