# -*- coding: utf-8 -*-
"""
Runtime launch test: actually start winws/winws2.exe with the parsed
arguments of every strategy and check that the process stays alive
for a few seconds. This catches:

  - bad / unknown command-line flags
  - missing .bin / .txt / lua files
  - lua script syntax errors
  - mismatched --filter-* / --wf-* arguments

WinDivert may fail to load (we are not running elevated) - that's an
expected "soft" failure: we only mark a strategy as broken if winws
exits within the first 1.5s with an argument- or file-related error.
"""
import os
import re
import sys
import time
import json
import signal
import subprocess
from pathlib import Path

# Disable output buffering: print() should be visible immediately, not after
# the test finishes. Without this, the user sees only the first line and then
# nothing for ~10 minutes (Python buffers stdout when not connected to TTY).
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Pre-flight: if zapret/ is missing, abort with a clear actionable
# message instead of letting the test crash on a wall of file-not-found.
sys.path.insert(0, str(ROOT / "tests"))
from _preflight import check_setup

SETUP_OK, SETUP_MISSING = check_setup(verbose=True)
if not SETUP_OK:
    print()
    print("=" * 70)
    print("ABORTED: zapret/ working tree is missing.")
    print("=" * 70)
    print("Run `tools\\setup.bat` once to fetch binaries and strategies,")
    print("then re-run this test.")
    print("=" * 70)
    sys.exit(0)  # 0 = "no failure", just nothing to do

import vpn_client

api = vpn_client.Api.__new__(vpn_client.Api)
files = api._list_strategy_files()
print(f"Total strategies: {len(files)}")

if not files:
    print()
    print("=" * 70)
    print("ABORTED: no .bat strategy files found in zapret/.")
    print("Run `tools\\setup.bat` to generate them.")
    print("=" * 70)
    sys.exit(0)

# WinDivert registers itself as a service that points to the *first*
# directory it was ever run from. If that path is gone (e.g. tmp dir cleaned),
# EVERY subsequent winws run fails with
#   "windivert: error opening filter: The system cannot find the file specified."
# The fix is `sc stop windivert` + `sc delete windivert` (admin only).
# We call _cleanup_windivert() so the user's elevated run benefits.
print("[*] Clearing stale WinDivert service registration (admin required)...")
api._cleanup_windivert()
# Перерегистрируем сервис на наш путь к WinDivert64.sys.
# Без этого winws из D:\SKKVPN\VPN2\zapret\bin\ падает с
# "cannot find the file specified", если ранее сервис был зарегистрирован
# на другой путь (например D:\zapret\bin\ от чужой копии zapret).
print("[*] Re-registering WinDivert service to point at our .sys (admin required)...")
if api._register_windivert(1):
    print("[OK] WinDivert service points at our WinDivert64.sys")
else:
    print("[!] Could not re-register (no admin or other issue).")

# Pre-check: запускаем winws с минимальным фильтром, чтобы выяснить, может ли
# WinDivert загрузиться вообще. Если даже минимальный запуск падает с
# "windivert: error opening filter: The system cannot find the file specified."
# — это проблема СРЕДЫ (Secure Boot + истёкший сертификат, нет admin, и т.п.),
# и все 261 ошибки будут environment-related, а не багами стратегий.

# Паттерны ошибок СРЕДЫ (используются в probe и в основном цикле)
ENV_PROBE_PATTERNS = [
    r"windivert.*error opening filter.*cannot find",
    r"failed to load windivert",
    r"windivert.*not found",
    r"windivert.*access",
    r"windivert filter\s*:",  # "windivert filter : must specify port..."
    r"must specify port or/and partial raw filter",
]

def _probe_windivert():
    """Запускает winws с минимальным набором аргументов и возвращает (ok, output).

    winws требует ОБА фильтра:
    - --wf-tcp=... (WinDivert port filter — какой трафик перехватывать)
    - --filter-tcp=... (strategy filter — к какому трафику применять DPI)
    Без --wf-tcp= будет ошибка "must specify port or/and partial raw filter".
    """
    import tempfile as _tf
    exe = api._find_winws_exe(1)
    if not exe:
        return None, "winws.exe not found"
    bin_dir = api._zapret_bin_dir(1)
    probe_log = Path(_tf.gettempdir()) / "winws_probe.log"
    try:
        with open(probe_log, "wb") as fh:
            proc = subprocess.Popen(
                [exe, "--wf-tcp=80,443", "--filter-tcp=80",
                 "--dpi-desync=fake", "--dpi-desync-fake-tls=!"],
                cwd=bin_dir, stdout=fh, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        time.sleep(1.5)
        rc = proc.poll()
        try:
            proc.terminate(); proc.wait(timeout=2)
        except Exception:
            try: proc.kill()
            except Exception: pass
        out = probe_log.read_text(encoding="utf-8", errors="replace") if probe_log.exists() else ""
        try: probe_log.unlink()
        except Exception: pass
        return (rc is None), out
    except OSError as e:
        # WinError 740 = "Операция требует повышения" — winws.exe манифест
        # содержит requireAdministrator. Это среда, не баг стратегии.
        if getattr(e, "winerror", None) == 740:
            return False, f"WinError 740 (winws requires admin elevation): {e}"
        return None, f"spawn error: {e}"
    except Exception as e:
        return None, f"spawn error: {e}"

print("[*] Probing WinDivert driver load (minimal winws run)...")
winws_ok, probe_out = _probe_windivert()
if winws_ok is True:
    print("[OK] WinDivert loaded — testing strategies for real bugs.")
elif winws_ok is None:
    print(f"[!!] Could not probe: {probe_out}")
else:
    # winws exited within 1.5s — likely environment issue
    is_env = any(re.search(p, probe_out.lower()) for p in ENV_PROBE_PATTERNS)
    if is_env:
        print("[!!] ENVIRONMENT ISSUE detected — WinDivert driver cannot load.")
        print(f"    First error lines: {probe_out.strip().splitlines()[-3:]}")
        print("    Likely causes:")
        print("      1) Secure Boot ON + WinDivert64.sys signature expired (2023-05-26)")
        print("         -> Disable Secure Boot in UEFI/BIOS, or get a newer WinDivert")
        print("      2) Process not elevated (admin required for driver load)")
        print("      3) AV blocking WinDivert")
        print("    All strategy failures will be tagged as [ENV], not real bugs.")
    else:
        print(f"[??] winws probe failed but error is not windivert-related: {probe_out[-300:]}")

# Outcomes
RAN     = []  # alive after wait
BADARG  = []  # exited with bad-arg error
MISSING = []  # exited with missing-file error
ENV     = []  # exited due to ENVIRONMENT (WinDivert/Secure Boot/etc)
OTHER   = []  # exited with other error
SAMPLE_OUT = {}  # last 200 chars of stdout for first 5 broken strategies

# Patterns that distinguish a broken strategy from a "no admin" soft fail.
BADARG_PATTERNS = [
    r"bad value for",
    r"unknown option",
    r"invalid argument",
    r"unrecognized",
    r"syntax error",
    r"failed to parse",
    r"unknown.*flag",
    r"unhandled.*argument",
    r"invalid.*option",
]
MISSING_PATTERNS = [
    r"cannot (?:open|find|read|access) (?:file )?['\"]?([^\s'\"]+)",
    r"no such file",
    r"does not exist",
    r"missing (?:file|argument)",
    r"file not found",
    r"could not open",
]
# ENVIRONMENT errors — проблемы среды, а не стратегии.
# "windivert: error opening filter: The system cannot find the file specified."
# — типичная ошибка когда WinDivert64.sys не может загрузиться
# (Secure Boot + истёкший сертификат, нет admin, или повреждён сервис).
# Файл WinDivert64.sys СУЩЕСТВУЕТ в CWD, ошибка вводит в заблуждение.
ENV_PATTERNS = [
    r"windivert.*error opening filter.*cannot find",
    r"failed to load windivert",
    r"windivert.*not found",
    r"windivert.*access",
]
LUA_PATTERNS = [
    r"lua.*error",
    r"\[string \".*\"\]:",
    r"attempt to (?:call|index) ",
]

WINWS_WAIT_SEC = 1.8   # how long to let winws run before checking
WINWS_KILL_GRACE = 2   # graceful terminate timeout

for i, (v, bat) in enumerate(files):
    name = os.path.basename(bat)
    exe = api._find_winws_exe(v)
    if not exe:
        OTHER.append((v, name, "winws.exe not found"))
        continue

    args = api._parse_strategy(bat, v)
    if not args:
        OTHER.append((v, name, "parse returned empty"))
        continue

    bin_dir = api._zapret_bin_dir(v)
    log_path = Path(os.environ.get("TEMP", "/tmp")) / f"winws_test_{i}.log"

    try:
        proc = subprocess.Popen(
            [exe] + args,
            cwd=bin_dir,
            stdout=open(log_path, "wb"),
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError as e:
        OTHER.append((v, name, f"FileNotFoundError: {e}"))
        continue
    except OSError as e:
        # WinError 740 = "Операция требует повышения" — winws.exe манифест
        # содержит requireAdministrator. Это среда, не баг стратегии.
        if getattr(e, "winerror", None) == 740:
            ENV.append((v, name, "WinError 740", "[winws requires admin elevation]", log_path))
        else:
            OTHER.append((v, name, f"spawn error: {e}"))
        continue
    except Exception as e:
        OTHER.append((v, name, f"spawn error: {e}"))
        continue

    time.sleep(WINWS_WAIT_SEC)
    rc = proc.poll()
    out = ""
    try:
        out = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if rc is None:
        # Still running - good
        RAN.append((v, name))
        try:
            proc.terminate()
            proc.wait(timeout=WINWS_KILL_GRACE)
        except Exception:
            try: proc.kill()
            except Exception: pass
    else:
        # Process exited within the wait window. Classify.
        out_low = out.lower()
        is_badarg  = any(re.search(p, out_low) for p in BADARG_PATTERNS)
        is_missing = any(re.search(p, out_low) for p in MISSING_PATTERNS)
        is_env     = any(re.search(p, out_low) for p in ENV_PATTERNS)
        is_lua     = any(re.search(p, out_low) for p in LUA_PATTERNS)

        # show last ~25 lines for the report so the real error isn't hidden
        tail = "\n".join(out.strip().splitlines()[-25:])
        # for bad-arg errors, also show FIRST 5 lines (where winws prints
        # "unknown option 'X'" or "bad value for 'Y'" above the help)
        head = "\n".join(out.strip().splitlines()[:5]) if is_badarg else ""

        if is_badarg:
            BADARG.append((v, name, rc, tail, head, log_path))
        elif is_env:
            # WinDivert driver load failure — проблема СРЕДЫ, не стратегии
            ENV.append((v, name, rc, tail, log_path))
        elif is_missing:
            MISSING.append((v, name, rc, tail, log_path))
        elif is_lua:
            BADARG.append((v, name, rc, "[lua] " + tail, head, log_path))
        else:
            OTHER.append((v, name, rc, tail, log_path))

    # KEEP logs for broken strategies (don't unlink) so the user can inspect them
    if i >= 0:
        # We'll unlink at the end if no broken strategies
        pass

print()
print("=" * 70)
print(f"Total tested:     {len(files)}")
print(f"Stayed alive:     {len(RAN)}")
print(f"Bad-arg error:    {len(BADARG)}")
print(f"Missing file:     {len(MISSING)}")
print(f"ENV error:        {len(ENV)}  (WinDivert/Secure Boot — NOT a strategy bug)")
print(f"Other error:      {len(OTHER)}")
print()

if BADARG:
    print("--- BAD ARG ERRORS (broken strategies) ---")
    seen_heads = {}
    seen_heads_str = []
    for v, n, rc, out, head, logp in BADARG:
        # Group by error head to spot patterns
        if head:
            # Use first 2 non-empty lines of head as the key
            key = "\n".join([l for l in head.splitlines() if l.strip()][:2])
            seen_heads.setdefault(key, []).append(n)
    print("--- UNIQUE BADARG HEADS ---")
    for k, names in sorted(seen_heads.items(), key=lambda x: -len(x[1])):
        print(f"  [{len(names)}] {k[:200]}")
        for nm in names[:3]:
            print(f"      {nm}")
    print()
    for v, n, rc, out, head, logp in BADARG[:10]:
        print(f"  [v{v}] {n} (rc={rc}):")
        # Show first 3 lines (where winws prints the actual error)
        head_lines = [l for l in head.splitlines() if l.strip()][:3]
        for line in head_lines:
            print(f"      >>> {line}")
        # Then show last 5 lines of help
        for line in out.splitlines()[-5:]:
            print(f"      ... {line}")
    if len(BADARG) > 10:
        print(f"  ... and {len(BADARG) - 10} more bad-arg")

if ENV:
    print("--- ENVIRONMENT ERRORS (NOT strategy bugs) ---")
    seen = {}
    for v, n, rc, out, logp in ENV:
        first_lines = [l for l in out.splitlines() if l.strip()][:2]
        key = "\n".join(first_lines) if first_lines else "(empty)"
        seen.setdefault(key, []).append(n)
    print("--- UNIQUE ENV HEADS ---")
    for k, names in sorted(seen.items(), key=lambda x: -len(x[1])):
        print(f"  [{len(names)}] {k[:200]}")
        for nm in names[:3]:
            print(f"      {nm}")
    print()
    print("All ENV errors are due to environment (WinDivert driver),")
    print("not strategy bugs. Re-test after fixing environment.")
    print()

if MISSING:
    print("--- MISSING FILE ERRORS ---")
    # Group by first error line to identify common cause
    seen = {}
    for v, n, rc, out, logp in MISSING:
        first_lines = [l for l in out.splitlines() if l.strip()][:2]
        key = "\n".join(first_lines) if first_lines else "(empty)"
        seen.setdefault(key, []).append(n)
    print("--- UNIQUE MISSING HEADS ---")
    for k, names in sorted(seen.items(), key=lambda x: -len(x[1])):
        print(f"  [{len(names)}] {k[:200]}")
        for nm in names[:3]:
            print(f"      {nm}")
    print()
    for v, n, rc, out, logp in MISSING[:5]:
        print(f"  [v{v}] {n} (rc={rc}):")
        for line in out.splitlines()[-10:]:
            print(f"      {line}")
    if len(MISSING) > 5:
        print(f"  ... and {len(MISSING) - 5} more missing")

if OTHER:
    print("--- OTHER ERRORS ---")
    for v, n, rc_or_msg, *rest in OTHER[:30]:
        out = rest[0] if rest else ""
        logp = rest[1] if len(rest) > 1 else None
        print(f"  [v{v}] {n} (info={rc_or_msg}):")
        # Show first 3 lines of out
        for line in [l for l in out.splitlines() if l.strip()][:3]:
            print(f"      >>> {line}")
        # Then show last 5 lines
        for line in out.splitlines()[-5:]:
            print(f"      ... {line}")
    if len(OTHER) > 30:
        print(f"  ... and {len(OTHER) - 30} more")

# Final pass/fail: ENV errors don't count (they're environment issues,
# not strategy bugs). Only BADARG, MISSING and OTHER are real bugs.
sys.exit(0 if not BADARG and not MISSING and not OTHER else 1)
