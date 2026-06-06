# -*- coding: utf-8 -*-
"""
Comprehensive test of all tools/* scripts.
Each script is imported (or executed in a subprocess) and its output
is verified against expected behavior.
"""
import os
import sys
import re
import json
import shutil
import tempfile
import subprocess
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Pre-flight: if zapret/ is missing, data-dependent tests below
# become WARNs with a clear "run tools\setup.bat" hint.
sys.path.insert(0, str(ROOT / "tests"))
from _preflight import check_setup

SETUP_OK, SETUP_MISSING = check_setup(verbose=True)
SKIP_DATA_TESTS = not SETUP_OK

failures = []
warnings = []
tested = 0

def check(cond, msg):
    global tested
    tested += 1
    if not cond:
        failures.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")

def data_check(cond, msg):
    """Same as check() but a missing zapret/ tree becomes a WARN."""
    global tested
    tested += 1
    if not cond:
        if SKIP_DATA_TESTS:
            warnings.append(msg)
            print(f"  SKIP: {msg}")
        else:
            failures.append(msg)
            print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")

def warn(msg):
    warnings.append(msg)
    print(f"  WARN: {msg}")


def import_tool(name: str):
    """Import a Python module from tools/ by file name."""
    # Сначала ищем в tools/, иначе в tests/ (для self-test)
    for sub in ("tools", "tests"):
        p = ROOT / sub / name
        if p.exists():
            path = p
            break
    else:
        raise FileNotFoundError(f"module {name} not found in tools/ or tests/")
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


print("=" * 70)
print("TOOL 1: tools/fetch_zapret_presets.py (youtubediscord/zapret)")
print("=" * 70)
mod = import_tool("fetch_zapret_presets.py")
check(hasattr(mod, "REPO") and mod.REPO == "youtubediscord/zapret",
      f"REPO = {mod.REPO}")
check(hasattr(mod, "fetch_tree"), "has fetch_tree()")
check(hasattr(mod, "convert_preset"), "has convert_preset()")
check(hasattr(mod, "sanitize_filename"), "has sanitize_filename()")
# Test sanitize
n = mod.sanitize_filename("alt_1/foo<>bar?.bat")
check(".bat" in n and "<" not in n, f"sanitize_filename('alt_1/foo<>bar?.bat') -> {n!r}")

# Verify output files exist
out_v1 = ROOT / "zapret"
out_v2 = ROOT / "zapret" / "zapret2"
v1_bats = list(out_v1.glob("z1 - *.bat"))
v2_bats = list(out_v2.glob("z2 - *.bat"))
data_check(len(v1_bats) >= 100, f"v1 youtubediscord presets present: {len(v1_bats)}")
data_check(len(v2_bats) >= 90, f"v2 youtubediscord presets present: {len(v2_bats)}")

# Sample: verify a converted .bat has ZAPRET_VERSION marker
if v1_bats:
    sample = v1_bats[0].read_text(encoding="utf-8", errors="replace")
    check("ZAPRET_VERSION=1" in sample, f"sample v1 has ZAPRET_VERSION=1 marker")
    check("%BIN%winws.exe" in sample, f"sample v1 uses %BIN%winws.exe")
    check("start" in sample.lower(), f"sample v1 has start command")

if v2_bats:
    sample = v2_bats[0].read_text(encoding="utf-8", errors="replace")
    check("ZAPRET_VERSION=2" in sample, f"sample v2 has ZAPRET_VERSION=2 marker")
    check("%BIN%winws2.exe" in sample, f"sample v2 uses %BIN%winws2.exe")

print()
print("=" * 70)
print("TOOL 2: tools/fetch_flowseal_presets.py (Flowseal/zapret-discord-youtube)")
print("=" * 70)
mod = import_tool("fetch_flowseal_presets.py")
check(hasattr(mod, "get_latest_release_url"), "has get_latest_release_url()")
check(hasattr(mod, "convert_flowseal_bat"), "has convert_flowseal_bat()")
check(hasattr(mod, "FLOWSEAL_LATEST"), "FLOWSEAL_LATEST API URL defined")

# Test convert_flowseal_bat with synthetic input
sample_bat = '''@echo off
chcp 65001 > nul

cd /d "%~dp0"
call service.bat status_zapret
call service.bat check_updates
call service.bat load_game_filter
call service.bat load_user_lists
echo:

set "BIN=%~dp0bin\\"
set "LISTS=%~dp0lists\\"
cd /d %BIN%

start "zapret: test" /min "%BIN%winws.exe" --wf-tcp=80,443 --wf-udp=443 ^
--filter-tcp=443 --hostlist="%LISTS%list-general.txt" --dpi-desync=fake
'''
out = mod.convert_flowseal_bat(sample_bat, "general.bat")
check("ZAPRET_VERSION=1" in out, f"converted has ZAPRET_VERSION=1")
check("GameFilterTCP" in out, f"converted has GameFilterTCP (inlined from service.bat)")
check("call service.bat" not in out, f"converted removes 'call service.bat'")
check("start" in out, f"converted has start command")
check("%BIN%winws.exe" in out, f"converted uses %BIN%winws.exe")

# Verify Flowseal .bat files exist in zapret/ with z1 - prefix
flowseal_bats = list((ROOT / "zapret").glob("z1 - general*.bat"))
data_check(len(flowseal_bats) >= 15,
      f"Flowseal general*.bat files (z1 - prefix): {len(flowseal_bats)}")
# Verify no legacy un-prefixed Flowseal files remain
legacy_flowseal = list((ROOT / "zapret").glob("general*.bat"))
data_check(not legacy_flowseal,
      f"no legacy un-prefixed Flowseal .bat files: {legacy_flowseal}")

print()
print("=" * 70)
print("TOOL 3: tools/fetch_antizapret_presets.py (pumPCin/AntiZapret)")
print("=" * 70)
mod = import_tool("fetch_antizapret_presets.py")
check(hasattr(mod, "get_latest_release_url"), "has get_latest_release_url()")
check(hasattr(mod, "convert_antizapret_cmd"), "has convert_antizapret_cmd()")
check(hasattr(mod, "parse_antizapret_name"), "has parse_antizapret_name()")

# Test parse_antizapret_name
for n, expected in [
    ("1_antizapret_auto_v1.cmd", "antizapret (auto v1)"),
    ("1_antizapret_extended_v4.cmd", "antizapret (extended v4)"),
    ("1_antizapret_general_v3.cmd", "antizapret (general v3)"),
]:
    out = mod.parse_antizapret_name(n)
    check(out == expected, f"parse_antizapret_name({n!r}) -> {out!r} (expected {expected!r})")

# Test convert_antizapret_cmd
sample_cmd = '''start "antizapret: auto v1" /min "%~dp0winws.exe" ^
--wf-tcp=80,443 --wf-udp=443 ^
--filter-tcp=80 --ipset="%~dp0ipset-all.txt" --dpi-desync=fake ^
--filter-tcp=443 --dpi-desync=multisplit --dpi-desync-split-seqovl-pattern="%~dp0tls_clienthello_www_google_com.bin" ^
'''
out = mod.convert_antizapret_cmd(sample_cmd)
check("ZAPRET_VERSION=1" in out, f"converted has ZAPRET_VERSION=1")
check("start" in out, f"converted has start command")
check("%BIN%winws.exe" in out, f"converted uses %BIN%winws.exe (not %~dp0winws.exe)")
check("%LISTS%ipset-all.txt" in out, f"converted uses %LISTS%ipset-all.txt")
check("%BIN%tls_clienthello_www_google_com.bin" in out, f"converted uses %BIN%*.bin")
# The 'cd /d "%~dp0"' line is the standard cmd idiom for "go to script dir",
# not a leftover from the source .cmd. The actual winws args must not contain
# any %~dp0 references.
args_section = out.split("start", 1)[1] if "start" in out else ""
check("%~dp0" not in args_section, f"args section has no %~dp0 left")

# Verify antizapret .bat files exist with z1 - prefix
antizapret_bats = list((ROOT / "zapret").glob("z1 - antizapret*.bat"))
data_check(len(antizapret_bats) >= 10,
      f"antizapret .bat files (z1 - prefix): {len(antizapret_bats)}")
# Verify no legacy un-prefixed antizapret files remain
legacy_antizapret = list((ROOT / "zapret").glob("antizapret*.bat"))
data_check(not legacy_antizapret,
      f"no legacy un-prefixed antizapret .bat files: {legacy_antizapret}")

print()
print("=" * 70)
print("TOOL 4: tools/download_zapret.ps1 (PowerShell)")
print("=" * 70)
ps1 = (ROOT / "tools" / "download_zapret.ps1").read_text(encoding="utf-8", errors="replace")
check("Get-LatestRelease" in ps1, "PS1 defines Get-LatestRelease function")
check("api.github.com" in ps1, "PS1 uses GitHub Releases API")
check("bol-van/zapret" in ps1, "PS1 references bol-van/zapret")
check("bol-van/zapret2" in ps1, "PS1 references bol-van/zapret2")
check("zapret-win-bundle" in ps1, "PS1 references zapret-win-bundle")
check("Flowseal" in ps1, "PS1 references Flowseal")
check("CopyFrom" in ps1, "PS1 defines CopyFrom function")
check("cmd.exe /c" in ps1 and "move /Y" in ps1, "PS1 uses cmd move /Y for locked files")

print()
print("=" * 70)
print("TOOL 5: tools/download_proxies.ps1 (PowerShell)")
print("=" * 70)
ps1 = (ROOT / "tools" / "download_proxies.ps1").read_text(encoding="utf-8", errors="replace")
check("Get-LatestAsset" in ps1, "PS1 defines Get-LatestAsset function")
check("api.github.com" in ps1, "PS1 uses GitHub Releases API")
check("Alexey71/opera-proxy" in ps1, "PS1 references opera-proxy repo")
check("Skiro1/warp-awg-gen" in ps1, "PS1 references warp-awg-gen repo")
check("snawoot-proxies-forks/hola-proxy" in ps1, "PS1 references hola-proxy repo")
check("windows-amd64" in ps1, "PS1 matches amd64 assets")

print()
print("=" * 70)
print("TOOL 6: tests/test_zapret_selection.py (sibling test)")
print("=" * 70)
# Don't import as a module (it would run the tests and sys.exit the parent).
# Read the file and assert it has the expected structure.
test_sel = (ROOT / "tests" / "test_zapret_selection.py").read_text(encoding="utf-8", errors="replace")
check("def check(" in test_sel, "test_zapret_selection.py has check() function")
check("if __name__" in test_sel, "test_zapret_selection.py guarded by __main__")

# Run test_zapret_selection.py as a subprocess to verify it passes
print()
print("  Running tests/test_zapret_selection.py as subprocess...", flush=True)
res = subprocess.run(
    [sys.executable, str(ROOT / "tests" / "test_zapret_selection.py")],
    capture_output=True, text=True, timeout=180,
)
print(f"  [subprocess done, returncode={res.returncode}]", flush=True)
last_lines = res.stdout.strip().splitlines()[-5:]
print("  " + "\n  ".join(last_lines), flush=True)
check(res.returncode == 0, f"test_zapret_selection.py exits 0 (got {res.returncode})")

print()
print("=" * 70)
print("TOOL 7: tools/setup.bat and tools/update.bat (batch)")
print("=" * 70)
setup_bat = (ROOT / "tools" / "setup.bat").read_text(encoding="utf-8", errors="replace")
update_bat = (ROOT / "tools" / "update.bat").read_text(encoding="utf-8", errors="replace")
check("download_proxies.ps1" in setup_bat, "setup.bat calls download_proxies.ps1")
check("download_zapret.ps1" in setup_bat, "setup.bat calls download_zapret.ps1")
check("fetch_zapret_presets.py" in setup_bat, "setup.bat calls fetch_zapret_presets.py")
check("fetch_flowseal_presets.py" in setup_bat, "setup.bat calls fetch_flowseal_presets.py")
check("fetch_antizapret_presets.py" in setup_bat, "setup.bat calls fetch_antizapret_presets.py")
check("download_proxies.ps1" in update_bat, "update.bat calls download_proxies.ps1")
check("fetch_flowseal_presets.py" in update_bat, "update.bat calls fetch_flowseal_presets.py")
check("fetch_antizapret_presets.py" in update_bat, "update.bat calls fetch_antizapret_presets.py")

print()
print("=" * 70)
print("TOOL 8: build_release.bat and build_debug.bat (root)")
print("=" * 70)
build_r = (ROOT / "build_release.bat").read_text(encoding="utf-8", errors="replace")
build_d = (ROOT / "build_debug.bat").read_text(encoding="utf-8", errors="replace")
check("tools\\setup.bat" in build_r or "tools/setup.bat" in build_r,
      "build_release.bat calls tools/setup.bat (fresh install)")
check("tools\\update.bat" in build_r or "tools/update.bat" in build_r,
      "build_release.bat calls tools/update.bat (existing venv)")
check("tools\\setup.bat" in build_d or "tools/setup.bat" in build_d,
      "build_debug.bat calls tools/setup.bat (fresh install)")
check("tools\\update.bat" in build_d or "tools/update.bat" in build_d,
      "build_debug.bat calls tools/update.bat (existing venv)")
check("--windowed" in build_r, "build_release uses --windowed (no console)")
check("--console" in build_d, "build_debug uses --console (debug output)")

print()
print("=" * 70)
print("TOOL 9: update.bat (root)")
print("=" * 70)
update_root = (ROOT / "update.bat").read_text(encoding="utf-8", errors="replace")
check("tools\\update.bat" in update_root or "tools/update.bat" in update_root,
      "update.bat calls tools/update.bat")

print()
print("=" * 70)
print("TOOL 10: root has only build_*.bat and update.bat")
print("=" * 70)
root_bats = sorted(p.name for p in ROOT.glob("*.bat"))
check(root_bats == ["build_debug.bat", "build_release.bat", "update.bat"],
      f"root .bat files: {root_bats}")

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
