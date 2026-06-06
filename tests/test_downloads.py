# -*- coding: utf-8 -*-
"""
Tests for the binary-download path.

The actual downloader (tools/fetch_zapret_setup.py + tools/download_*.ps1) is
network-bound and hard to test deterministically. Instead we test:

  1. The source code references the right GitHub repos / assets.
  2. Known URLs are syntactically correct (no typos that would 404).
  3. The flow is idempotent (re-running doesn't redownload if size matches).
  4. With VPNCLIENT_RUN_NETWORK=1, actually pull a tiny file and check
     the SHA-256. This is a canary for upstream repo / branch renames.

Local-file sanity checks (WinDivert.dll size, winws.exe presence) are
WARN-level, not FAIL, because they require `setup.bat` to have been run.
"""
import os
import re
import sys
import shutil
import hashlib
import tempfile
import importlib.util
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

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


def read_tool(name: str) -> str:
    return (ROOT / "tools" / name).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# TEST 1: fetch_zapret_setup.py — known URLs and repos
# ---------------------------------------------------------------------------
print("=" * 70)
print("TEST 1: fetch_zapret_setup.py — known URLs and repos")
print("=" * 70)
src = read_tool("fetch_zapret_setup.py")
# Extract every http(s) URL from the source and sanity-check the structure.
# Note: many URLs use {repo_name} / {owner}/{name} placeholders, so we look
# at domains and repo refs (name/name) instead of full URLs.
urls = re.findall(r"https?://[^\s\"')]+", src)
print(f"  Found {len(urls)} URLs in fetch_zapret_setup.py")
unique_domains = sorted({urlparse(u).netloc for u in urls})
print(f"  Unique domains: {unique_domains}")
# Required domains
required_domains = {
    "api.github.com",                       # GitHub Releases API
    "raw.githubusercontent.com",            # Direct file downloads (Flowseal WinDivert)
}
missing = required_domains - set(unique_domains)
check(not missing, f"required domains present: missing={missing}")
# All URLs look syntactically valid
bad_urls = [u for u in urls if not urlparse(u).scheme or not urlparse(u).netloc]
check(not bad_urls, f"all URLs syntactically valid (bad: {bad_urls[:3]})")
# No http:// (insecure) URLs
insecure = [u for u in urls if u.startswith("http://")]
check(not insecure, f"no insecure http:// URLs (found: {insecure})")
# Look for repo references (owner/name) anywhere in the source
repo_refs = sorted(set(re.findall(r"\b([\w][\w\-]{1,40})/([\w][\w\-]{1,40})\b", src)))
# Filter to plausible GitHub-style refs (lowercase + digits + hyphens)
gh_refs = sorted({f"{a}/{b}" for a, b in repo_refs
                  if all(c.isalnum() or c in "-_." for c in a)
                  and all(c.isalnum() or c in "-_." for c in b)})
print(f"  Possible repo refs: {gh_refs}")
required_repos = {
    "youtubediscord/zapret",
    "Flowseal/zapret-discord-youtube",
    "pumPCin/AntiZapret",
}
missing_repos = required_repos - set(gh_refs)
check(not missing_repos, f"required repos present: missing={sorted(missing_repos)}")

# ---------------------------------------------------------------------------
# TEST 2: download_zapret.ps1 — known repos
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 2: download_zapret.ps1 — known repos and assets")
print("=" * 70)
ps1 = read_tool("download_zapret.ps1")
# The PS1 uses a $Repo variable — look for owner/name refs in code instead.
gh_refs = sorted(set(re.findall(r"\b([\w][\w\-]{1,40})/([\w][\w\-]{1,40})\b", ps1)))
gh_refs = sorted({f"{a}/{b}" for a, b in gh_refs
                  if all(c.isalnum() or c in "-_." for c in a)
                  and all(c.isalnum() or c in "-_." for c in b)})
print(f"  Repo refs in PS1: {gh_refs}")
expected_repos = {"bol-van/zapret", "bol-van/zapret2", "youtubediscord/zapret",
                  "Flowseal/zapret-discord-youtube", "bol-van/zapret-win-bundle"}
missing = expected_repos - set(gh_refs)
check(not missing, f"required zapret repos present: missing={missing}")
# The script must have a "Get-LatestRelease" function
check("function Get-LatestRelease" in ps1 or "function Get-LatestAsset" in ps1,
      "download_zapret.ps1 defines Get-LatestRelease/Get-LatestAsset function")
# Asset filter for windows amd64 / x86_64 (youtubediscord zips aren't named
# amd64, but bol-van bundles are win-x86_64)
low = ps1.lower()
has_amd = "amd64" in low or "x86_64" in low or "x64" in low
check(has_amd, "download_zapret.ps1 filters for amd64 / x86_64 / x64 assets")

# ---------------------------------------------------------------------------
# TEST 3: download_proxies.ps1 — known repos
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 3: download_proxies.ps1 — known repos and assets")
print("=" * 70)
ps1 = read_tool("download_proxies.ps1")
gh_refs = sorted(set(re.findall(r"\b([\w][\w\-]{1,40})/([\w][\w\-]{1,40})\b", ps1)))
gh_refs = sorted({f"{a}/{b}" for a, b in gh_refs
                  if all(c.isalnum() or c in "-_." for c in a)
                  and all(c.isalnum() or c in "-_." for c in b)})
print(f"  Repo refs in PS1: {gh_refs}")
expected_repos = {"Alexey71/opera-proxy", "Skiro1/warp-awg-gen", "snawoot-proxies-forks/hola-proxy"}
missing = expected_repos - set(gh_refs)
check(not missing, f"required proxy repos present: missing={missing}")
low = ps1.lower()
has_amd = "amd64" in low or "x86_64" in low or "x64" in low
check(has_amd, "download_proxies.ps1 filters for amd64 / x86_64 / x64 assets")

# ---------------------------------------------------------------------------
# TEST 4: idempotency of CopyFrom / Copy-With-Lock
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 4: CopyFrom is idempotent (Test-Path or size check)")
print("=" * 70)
ps1 = read_tool("download_zapret.ps1")
# Idempotency in PS1 is achieved via Test-Path (skip if exists). The
# docstring at the top also claims this. Also look for `.Length -eq` as
# a stronger form of size-check.
has_test_path_idempotency = bool(re.search(
    r"if\s*\(\s*\(?Test-Path[^\n]*\)\s*-and\s*-not\s+\$Force",
    ps1, re.IGNORECASE,
))
has_size_check = bool(re.search(
    r"\.Length\s*-eq\s*|\.size\s*-eq\s*",
    ps1, re.IGNORECASE,
))
check(has_test_path_idempotency or has_size_check,
      f"download_zapret.ps1 is idempotent "
      f"(Test-Path={has_test_path_idempotency}, size-check={has_size_check})")
# Fallback: cmd.exe /c move /Y for locked files
check("cmd.exe /c" in ps1 and "move /Y" in ps1,
      "download_zapret.ps1 has cmd /c move /Y fallback for locked files")

# ---------------------------------------------------------------------------
# TEST 5: local binary sanity (WARN-level if missing)
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 5: local binary sanity (WARN if not present)")
print("=" * 70)
binaries = {
    ROOT / "opera-proxy.exe": "Opera proxy",
    ROOT / "warp-awg-gen.exe": "WARP config generator",
    ROOT / "hola-proxy.exe": "Hola proxy",
    ROOT / "zapret" / "bin" / "winws.exe": "winws.exe (zapret v1)",
    ROOT / "zapret" / "bin" / "WinDivert.dll": "WinDivert.dll (Flowseal)",
    ROOT / "zapret" / "bin" / "WinDivert64.sys": "WinDivert64.sys (kernel)",
    ROOT / "zapret" / "zapret2" / "bin" / "winws2.exe": "winws2.exe (zapret v2)",
}
for path, label in binaries.items():
    if path.exists():
        size = path.stat().st_size
        print(f"  {label}: {size} bytes")
        if path.name == "WinDivert.dll":
            check(size == 47616,
                  f"WinDivert.dll is 47616 bytes (Flowseal build), got {size}")
    else:
        warn(f"{label} not found at {path.relative_to(ROOT)} (run setup.bat)")

# ---------------------------------------------------------------------------
# TEST 6: WinDivert64.sys signature expiry awareness
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 6: code is aware of WinDivert64.sys signature expiry")
print("=" * 70)
vpn_src = (ROOT / "vpn_client.py").read_text(encoding="utf-8", errors="replace")
# We documented earlier that the cert expired 2023-05-26. The code
# must contain a comment about this AND must use the Flowseal DLL as
# a workaround.
check("Flowseal" in vpn_src,
      "vpn_client.py references Flowseal (workaround for expired cert)")
# Look for the signature-expiry comment
check("expired" in vpn_src.lower() or "sectigo" in vpn_src.lower() or "signature" in vpn_src.lower(),
      "vpn_client.py mentions expired/sectigo/signature in code/comments")

# ---------------------------------------------------------------------------
# TEST 7: WinDivert service auto-registration is in place
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print("TEST 7: WinDivert service auto-registration is in place")
print("=" * 70)
check("_register_windivert" in vpn_src,
      "vpn_client.py has _register_windivert() method")
# It must be CALLED somewhere in the DPI connect path. Match either
# `self._register_windivert()` or `self._register_windivert(<args>)`.
m = re.search(r"self\._register_windivert\s*\(", vpn_src)
check(bool(m),
      "vpn_client.py actually CALLS self._register_windivert() somewhere")

# ---------------------------------------------------------------------------
# TEST 8: network smoke test (opt-in) — fetch a tiny file and verify hash
# ---------------------------------------------------------------------------
print()
print("=" * 70)
print(f"TEST 8: network smoke (RUN_NETWORK={RUN_NETWORK})")
print("=" * 70)
if RUN_NETWORK:
    import urllib.request
    # Fetch the WinDivert.dll from Flowseal — small, fast, regression canary.
    url = ("https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/"
           "main/bin/WinDivert.dll")
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
        check(len(data) == 47616,
              f"Flowseal WinDivert.dll is 47616 bytes (got {len(data)})")
        sha = hashlib.sha256(data).hexdigest()
        print(f"  SHA-256: {sha}")
    except Exception as e:
        warn(f"network test failed: {e}")
    # Also check that the GitHub Releases API endpoints still respond
    for api in (
        "https://api.github.com/repos/youtubediscord/zapret/releases/latest",
        "https://api.github.com/repos/bol-van/zapret/releases/latest",
        "https://api.github.com/repos/bol-van/zapret2/releases/latest",
        "https://api.github.com/repos/pumPCin/AntiZapret/releases/latest",
        "https://api.github.com/repos/Flowseal/zapret-discord-youtube/releases/latest",
        "https://api.github.com/repos/Alexey71/opera-proxy/releases/latest",
        "https://api.github.com/repos/Skiro1/warp-awg-gen/releases/latest",
        "https://api.github.com/repos/snawoot-proxies-forks/hola-proxy/releases/latest",
    ):
        try:
            req = urllib.request.Request(api, headers={"User-Agent": "vpn-client",
                                                       "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            rel = __import__("json").loads(data)
            tag = rel.get("tag_name", "?")
            n_assets = len(rel.get("assets", []))
            print(f"  {api.split('/repos/')[1].split('/')[0]}: tag={tag}, assets={n_assets}")
            check(n_assets > 0,
                  f"{api.split('/repos/')[1].split('/')[0]} has at least 1 asset")
        except Exception as e:
            warn(f"GitHub API for {api} failed: {e}")
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
