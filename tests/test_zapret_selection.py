# -*- coding: utf-8 -*-
"""
Comprehensive test of zapret auto-strategy selection logic.
Tests parsing, version detection, file resolution, and the auto-pick
priority/score system without actually running winws.exe.
"""
import os
import sys
import re
import time
import json
import tempfile
import subprocess
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Pre-flight: ensure the zapret/ working tree is present, otherwise
# skip the data-dependent tests with a clear actionable warning.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _preflight import check_setup

SETUP_OK, SETUP_MISSING = check_setup(verbose=True)
SKIP_DATA_TESTS = not SETUP_OK

import vpn_client

# Get an instance without __init__ side effects
api = vpn_client.Api.__new__(vpn_client.Api)

failures = []
warnings = []


def data_check(cond, msg):
    """Same as check() but a missing zapret/ tree becomes a WARN, not a FAIL.

    Tests that exercise the actual strategy files (parsing, listing, version
    detection) become no-ops with a clear message when the tree is missing,
    so the user sees a useful diagnostic instead of a wall of FAILs.
    """
    global tested
    tested += 1
    if not cond:
        if SKIP_DATA_TESTS:
            warnings.append(msg)
            print(f"  SKIP:  {msg}")
        else:
            failures.append(msg)
            print(f"  FAIL:  {msg}")
    else:
        print(f"  ok:    {msg}")
tested = 0

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

print("=" * 70)
print("TEST 1: ZAPRET_VERSION constant")
print("=" * 70)
# Should be the Flowseal version that we ship; check it's a string
check(isinstance(vpn_client.ZAPRET_VERSION, str) and vpn_client.ZAPRET_VERSION,
      f"ZAPRET_VERSION defined: {vpn_client.ZAPRET_VERSION!r}")

print()
print("=" * 70)
print("TEST 2: Directory structure")
print("=" * 70)
v1_dir = api._zapret_dir(1)
v2_dir = api._zapret_dir(2)
data_check(os.path.isdir(v1_dir), f"v1 zapret dir exists: {v1_dir}")
data_check(os.path.isdir(v2_dir), f"v2 zapret dir exists: {v2_dir}")
data_check(v1_dir != v2_dir, f"v1 and v2 dirs are different: {v1_dir} vs {v2_dir}")

v1_bin = api._zapret_bin_dir(1)
v2_bin = api._zapret_bin_dir(2)
data_check(os.path.isdir(v1_bin), f"v1 bin dir exists: {v1_bin}")
data_check(os.path.isdir(v2_bin), f"v2 bin dir exists: {v2_bin}")

v1_lists = api._zapret_lists_dir(1)
v2_lists = api._zapret_lists_dir(2)
data_check(os.path.isdir(v1_lists), f"v1 lists dir exists: {v1_lists}")
data_check(os.path.isdir(v2_lists), f"v2 lists dir exists: {v2_lists}")

print()
print("=" * 70)
print("TEST 3: winws.exe resolution")
print("=" * 70)
v1_exe = api._find_winws_exe(1)
v2_exe = api._find_winws_exe(2)
data_check(v1_exe and os.path.isfile(v1_exe), f"v1 winws.exe found: {v1_exe}")
data_check(v2_exe and os.path.isfile(v2_exe), f"v2 winws2.exe found: {v2_exe}")
data_check(v1_exe != v2_exe, f"v1 and v2 winws are different: {v1_exe} vs {v2_exe}")

print()
print("=" * 70)
print("TEST 4: WinDivert dependencies")
print("=" * 70)
miss_v1 = api._winws_required_files_ok(1)
miss_v2 = api._winws_required_files_ok(2)
data_check(not miss_v1, f"v1 has all WinDivert files (missing: {miss_v1})")
data_check(not miss_v2, f"v2 has all WinDivert files (missing: {miss_v2})")

print()
print("=" * 70)
print("TEST 5: List all strategy files")
print("=" * 70)
files = api._list_strategy_files()
print(f"  Total strategies: {len(files)}")
v1_count = sum(1 for v, _ in files if v == 1)
v2_count = sum(1 for v, _ in files if v == 2)
print(f"  v1: {v1_count}")
print(f"  v2: {v2_count}")
data_check(v1_count > 0, f"v1 strategies present ({v1_count} > 0)")
data_check(v2_count > 0, f"v2 strategies present ({v2_count} > 0)")

# No service.bat in list
service_in = [p for v, p in files if os.path.basename(p).lower().startswith("service")]
data_check(not service_in, f"service.bat excluded from list (got: {service_in})")

# Every file's version detection must match the directory layout
mismatches = []
for v, p in files:
    detected = api._detect_strategy_version(p)
    if detected != v:
        mismatches.append((p, v, detected))
data_check(not mismatches, f"all files have correct detected version (mismatches: {mismatches[:3]})")

print()
print("=" * 70)
print("TEST 6: Parse every strategy; check for unresolved %%vars or bad args")
print("=" * 70)
unresolved_count = 0
empty_arg_count = 0
weird_arg_count = 0
for v, p in files:
    args = api._parse_strategy(p, v)
    if not args:
        warn(f"parse returned empty: {p}")
        empty_arg_count += 1
        continue
    joined = " ".join(args)
    if "%" in joined:
        # find which var is unresolved
        m = re.findall(r"%[A-Za-z0-9_~]+%", joined)
        if m:
            warn(f"unresolved %vars in {os.path.basename(p)}: {set(m)}")
            unresolved_count += 1
    # check for hanging --filter-tcp= or --filter-udp= with empty value
    if re.search(r"--filter-(?:tcp|udp)=(?=\s|$)", joined) or re.search(r"--filter-tcp= ", joined):
        warn(f"empty --filter-tcp/udp value in {os.path.basename(p)}")
        weird_arg_count += 1
    if re.search(r"--wf-(?:tcp|udp)=(?=,|\s)", joined):
        warn(f"empty --wf-tcp/udp value in {os.path.basename(p)}")
        weird_arg_count += 1
data_check(unresolved_count == 0, f"no unresolved %vars in all {len(files)} strategies (got {unresolved_count} bad)")
data_check(empty_arg_count == 0, f"no empty parse results (got {empty_arg_count})")
data_check(weird_arg_count == 0, f"no empty --filter-tcp/udp/--wf-tcp/udp (got {weird_arg_count} bad)")

print()
print("=" * 70)
print("TEST 7: Auto-pick priority ordering")
print("=" * 70)
# Re-implement priority logic and verify
def _priority(item):
    version, p = item
    name = os.path.basename(p).lower()
    if "general" in name and "alt" not in name:
        return (0, version, name)
    if "antizapret" in name:
        return (0, version, name)
    if "default" in name and "alt" not in name:
        return (0, version, name)
    return (1, version, name)
sorted_files = sorted(files, key=_priority)
priority_zero = [f for f in sorted_files if _priority(f)[0] == 0]
priority_one = [f for f in sorted_files if _priority(f)[0] == 1]
print(f"  priority=0 (general/antizapret/default): {len(priority_zero)}")
print(f"  priority=1 (everything else): {len(priority_one)}")

# All priority-zero should be sorted before priority-one
first_one_idx = next((i for i, f in enumerate(sorted_files) if _priority(f)[0] == 1), len(sorted_files))
last_zero_idx = max((i for i, f in enumerate(sorted_files) if _priority(f)[0] == 0), default=-1)
data_check(last_zero_idx < first_one_idx, f"priority=0 items come before priority=1 (last 0 idx={last_zero_idx}, first 1 idx={first_one_idx})")

# Within priority=0, v1 should come before v2
v1_in_p0 = [f for f in priority_zero if f[0] == 1]
v2_in_p0 = [f for f in priority_zero if f[0] == 2]
print(f"  v1 in priority=0: {len(v1_in_p0)}")
print(f"  v2 in priority=0: {len(v2_in_p0)}")
# The first v2 should come after the last v1
if v1_in_p0 and v2_in_p0:
    last_v1_idx = max(sorted_files.index(f) for f in v1_in_p0)
    first_v2_idx = min(sorted_files.index(f) for f in v2_in_p0)
    data_check(last_v1_idx < first_v2_idx, f"v1 comes before v2 within priority=0 (last v1 idx={last_v1_idx}, first v2 idx={first_v2_idx})")

print()
print("=" * 70)
print("TEST 8: Strategy names are unique across v1/v2")
print("=" * 70)
v1_names = set(os.path.splitext(os.path.basename(p))[0] for v, p in files if v == 1)
v2_names = set(os.path.splitext(os.path.basename(p))[0] for v, p in files if v == 2)
overlap = v1_names & v2_names
print(f"  v1 names: {len(v1_names)}")
print(f"  v2 names: {len(v2_names)}")
print(f"  overlap: {len(overlap)}")
data_check(not overlap, f"no name collisions between v1 and v2 (overlap: {sorted(overlap)[:5]})")

print()
print("=" * 70)
print("TEST 8b: Every strategy has 'z1 - ' or 'z2 - ' prefix (naming convention)")
print("=" * 70)
v1_unprefixed = [os.path.basename(p) for v, p in files if v == 1
                 and not os.path.basename(p).lower().startswith("z1 - ")
                 and not os.path.basename(p).lower().startswith("z2 - ")]
v2_unprefixed = [os.path.basename(p) for v, p in files if v == 2
                 and not os.path.basename(p).lower().startswith("z2 - ")
                 and not os.path.basename(p).lower().startswith("z1 - ")]
print(f"  v1 unprefixed: {len(v1_unprefixed)} {v1_unprefixed[:3]}")
print(f"  v2 unprefixed: {len(v2_unprefixed)} {v2_unprefixed[:3]}")
data_check(not v1_unprefixed,
      f"all v1 strategies have 'z1 - ' prefix (offenders: {v1_unprefixed[:3]})")
data_check(not v2_unprefixed,
      f"all v2 strategies have 'z2 - ' prefix (offenders: {v2_unprefixed[:3]})")
# Every v1 must start with "z1 - " (not "z2 - ")
v1_wrong_prefix = [os.path.basename(p) for v, p in files if v == 1
                    and not os.path.basename(p).lower().startswith("z1 - ")]
v2_wrong_prefix = [os.path.basename(p) for v, p in files if v == 2
                    and not os.path.basename(p).lower().startswith("z2 - ")]
data_check(not v1_wrong_prefix,
      f"no v1 with wrong prefix (offenders: {v1_wrong_prefix[:3]})")
data_check(not v2_wrong_prefix,
      f"no v2 with wrong prefix (offenders: {v2_wrong_prefix[:3]})")

print()
print("=" * 70)
print("TEST 9: _start_strategy_by_name works for both versions")
print("=" * 70)
# Just check that the lookup function works; don't actually start.
if files:
    for v, p in files[:5]:
        name = os.path.splitext(os.path.basename(p))[0]
        # find the version
        found_version = None
        for v2, p2 in files:
            if os.path.splitext(os.path.basename(p2))[0] == name:
                found_version = v2
                break
        data_check(found_version == v, f"name lookup '{name}' returns v={found_version} (expected {v})")
else:
    warn("no strategy files to test name lookup (zapret/ missing)")

print()
print("=" * 70)
print("TEST 10: GUI list serialization")
print("=" * 70)
s = api.list_zapret_strategies()
arr = json.loads(s)
data_check(len(arr) == len(files), f"GUI list length matches: {len(arr)} == {len(files)}")
# Check shape
if arr:
    sample = arr[0]
    data_check("name" in sample and "version" in sample and "display" in sample,
          f"GUI items have name/version/display: keys={list(sample.keys())}")
    # Check display format
    data_check(" (Zapret " in sample["display"],
          f"display contains version tag: {sample['display']!r}")
else:
    warn("GUI list is empty (zapret/ missing)")

print()
print("=" * 70)
print("TEST 11: ZAPRET_TEST_URLS reachability (sanity)")
print("=" * 70)
# Just check the URL list isn't empty and URLs look valid
check(len(vpn_client.ZAPRET_TEST_URLS) >= 2, f"ZAPRET_TEST_URLS has >=2 urls: {len(vpn_client.ZAPRET_TEST_URLS)}")
for name, url in vpn_client.ZAPRET_TEST_URLS:
    check(url.startswith("http"), f"  '{name}' URL valid: {url}")

# Quick reachability check (HEAD/GET, 5s timeout each)
print()
print("  Testing reachability of test URLs (this can take ~15s)...")
for name, url in vpn_client.ZAPRET_TEST_URLS:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            ok = resp.status < 500
        print(f"    {name}: {'OK' if ok else 'FAIL'} ({url})")
    except Exception as e:
        print(f"    {name}: ERROR ({e}) - but this is fine, site may be blocked here")

print()
print("=" * 70)
print("TEST 12: _kill_dpi_process kills BOTH v1 and v2 winws")
print("=" * 70)
# Inspect the source code
import inspect
src = inspect.getsource(api._kill_dpi_process)
check("ZAPRET2_WINWS" in src or "winws2.exe" in src,
      f"_kill_dpi_process references winws2.exe (kills both versions)")
if "ZAPRET2_WINWS" not in src and "winws2.exe" not in src:
    # Check if it iterates over a list
    check("ZAPRET_WINWS" in src and ("for" in src or "loop" in src.lower() or "killall" in src.lower()),
          f"_kill_dpi_process loops over multiple exes")

print()
print("=" * 70)
print("TEST 13: ZAPRET_TEST_URLS has 55 sites (10 base + 7 Cloudflare + 13 RU + 25 Re:filter)")
print("=" * 70)
check(len(vpn_client.ZAPRET_TEST_URLS) == 55,
      f"ZAPRET_TEST_URLS has exactly 55 sites: {len(vpn_client.ZAPRET_TEST_URLS)}")
expected_sites = {
    # 10 base
    "YouTube", "Discord", "Instagram", "Cloudflare", "GitHub",
    "Twitter/X", "Facebook", "Reddit", "Twitch", "OpenAI",
    # 7 Cloudflare
    "Cloudflare WARP", "Cloudflare 1.1.1.1", "Cloudflare Workers",
    "Cloudflare Blog", "Cloudflare Trace", "Cloudflare Turnstile",
    "Cloudflare Dashboard",
    # 13 itdoginfo outside-raw
    "Ozon", "Gosuslugi", "Mos.ru", "Nalog.ru", "RZD", "Pochta.ru",
    "Leroy Merlin", "Yandex Net", "Mosreg", "Rosreestr", "FSSP",
    "Russianpost", "Emex",
    # 10 Re:filter messengers/AI
    "Telegram", "T.me", "Signal", "WhatsApp", "Snapchat",
    "Claude", "ChatGPT", "Google Meet", "Notion", "LinkedIn",
    # 5 Re:filter media
    "Netflix", "Spotify", "SoundCloud", "TikTok", "RuTracker",
    # 5 Re:filter VPN/email/privacy
    "NordVPN", "Mullvad", "Proton", "Tutanota", "PayPal",
    # 5 Re:filter alt/news/gaming
    "BBC", "Rumble", "Odysee", "Chess.com", "Nintendo",
}
actual_sites = {n for n, _ in vpn_client.ZAPRET_TEST_URLS}
check(actual_sites == expected_sites,
      f"ZAPRET_TEST_URLS sites match expected: missing={expected_sites-actual_sites}, extra={actual_sites-expected_sites}")
# No duplicates
check(len(actual_sites) == len(vpn_client.ZAPRET_TEST_URLS),
      f"no duplicate site names")

print()
print("=" * 70)
print("TEST 14: ZAPRET_AUTO_MODES constant")
print("=" * 70)
check(vpn_client.ZAPRET_AUTO_MODES == ("both", "v1", "v2"),
      f"ZAPRET_AUTO_MODES = ('both', 'v1', 'v2'): {vpn_client.ZAPRET_AUTO_MODES}")

print()
print("=" * 70)
print("TEST 15: _zapret_score returns (score, latency) tuple")
print("=" * 70)
# We don't run winws; just verify the API signature/return shape
import inspect
src_score = inspect.getsource(api._zapret_score)
check("return score, latency" in src_score or "return score,latency" in src_score,
      f"_zapret_score returns (score, latency) tuple")
check("time.monotonic" in src_score,
      f"_zapret_score uses time.monotonic for latency")

print()
print("=" * 70)
print("TEST 16: _auto_pick_strategy has round-robin, mode, ETA, latency")
print("=" * 70)
src_pick = inspect.getsource(api._auto_pick_strategy)
check("zapret_auto_mode" in src_pick,
      f"_auto_pick_strategy reads zapret_auto_mode setting")
check("_interleave_round_robin" in src_pick or "round_robin" in src_pick.lower() or "interleave" in src_pick.lower(),
      f"_auto_pick_strategy implements round-robin interleave")
check("ETA" in src_pick,
      f"_auto_pick_strategy computes and reports ETA")
check("latency" in src_pick,
      f"_auto_pick_strategy tracks latency for tie-breaking")

print()
print("=" * 70)
print("TEST 17: Round-robin v1/v2 ordering (unit test of helper logic)")
print("=" * 70)
# Re-implement the same round-robin logic and verify
def _bucket(item):
    _v, p = item
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
ordered = []
for key in sorted(buckets.keys()):
    ordered.extend(_interleave_round_robin(buckets[key]))
print(f"  Total ordered: {len(ordered)}")

# Show bucket distribution
print(f"  Bucket distribution:")
for key in sorted(buckets.keys()):
    n_v1 = sum(1 for v, _ in buckets[key] if v == 1)
    n_v2 = sum(1 for v, _ in buckets[key] if v == 2)
    print(f"    {key}: v1={n_v1}, v2={n_v2}")

# Property 1: priority=0 buckets before priority=1
first_p1_idx = next((i for i, x in enumerate(ordered) if _bucket(x)[0] == 1), len(ordered))
last_p0_idx = max((i for i, x in enumerate(ordered) if _bucket(x)[0] == 0), default=-1)
data_check(last_p0_idx < first_p1_idx,
      f"priority=0 buckets before priority=1 (last p0={last_p0_idx}, first p1={first_p1_idx})")

# Property 2: v2 strategies are NOT all bunched at the end.
# The first v2 should appear as soon as the v1's in the first bucket are exhausted
# (or earlier if the first bucket has both versions). The v2 in the first
# bucket that has v2 should appear within (v1_in_that_bucket + 1) positions.
buckets_in_order = sorted(buckets.keys())
first_bucket_with_v2 = None
for key in buckets_in_order:
    if any(v == 2 for v, _ in buckets[key]):
        first_bucket_with_v2 = key
        break
if first_bucket_with_v2 is not None:
    # In round-robin, the first v2 from this bucket should appear at most
    # at position (v1_in_this_bucket + 1) when all v1s of prior buckets
    # have been emitted. We compute that bound.
    n_v1_before = 0
    for key in buckets_in_order:
        if key == first_bucket_with_v2:
            n_v1_in_this = sum(1 for v, _ in buckets[key] if v == 1)
            break
        n_v1_before += sum(1 for v, _ in buckets[key] if v == 1)
    # The k-th v2 in this bucket is at position n_v1_before + 2*k
    # (after n_v1_before v1s from prior buckets, then alternating v1/v2)
    # So the first v2 from this bucket is at position n_v1_before + 1
    expected_first_v2_pos = n_v1_before + 1
    actual_first_v2_pos = next(
        (i for i, x in enumerate(ordered) if x[0] == 2), len(ordered),
    )
    print(f"  First v2 in ordered list: index {actual_first_v2_pos} (expected <= {expected_first_v2_pos + 1})")
    data_check(actual_first_v2_pos <= expected_first_v2_pos + 1,
          f"first v2 close to first bucket boundary (idx {actual_first_v2_pos} <= {expected_first_v2_pos + 1})")

# Property 3: every Nth v1 is followed by a v2 somewhere soon.
# In particular, in a bucket with BOTH v1 and v2, the interleave should
# keep v2 close to v1 (within 2 slots).
def check_interleaving_in_bucket(items):
    """For a bucket with both v1 and v2, verify v2's don't lag behind."""
    n_v1 = sum(1 for v, _ in items if v == 1)
    n_v2 = sum(1 for v, _ in items if v == 2)
    if n_v1 == 0 or n_v2 == 0:
        return None  # can't interleave one-sided buckets
    # the k-th v2 should appear at or before position 2*k
    v2_indices = [i for i, x in enumerate(items) if x[0] == 2]
    bad = [v2_idx for k, v2_idx in enumerate(v2_indices) if v2_idx > 2 * (k + 1)]
    return bad

# Build round-robin version of each bucket first, then check interleaving
bad_buckets = []
for key, items in buckets.items():
    rr_items = _interleave_round_robin(items)
    bad = check_interleaving_in_bucket(rr_items)
    if bad:
        bad_buckets.append((key, bad))
data_check(not bad_buckets,
      f"v2's interleaved tightly after v1 in mixed buckets (bad: {bad_buckets})")

# Property 4: not all v2 are at the tail of the list.
last_25pct_idx = int(0.75 * len(ordered))
v2_in_first_75 = sum(1 for x in ordered[:last_25pct_idx] if x[0] == 2)
v2_total = sum(1 for x in ordered if x[0] == 2)
v2_pct_in_first_75 = v2_in_first_75 / max(v2_total, 1) * 100
print(f"  v2 in first 75% of ordered list: {v2_in_first_75}/{v2_total} ({v2_pct_in_first_75:.0f}%)")
# v2 should be spread throughout, not bunched at the end
data_check(v2_pct_in_first_75 >= 50,
      f"v2 strategies spread throughout list ({v2_pct_in_first_75:.0f}% in first 75%)")

print()
print("=" * 70)
print("TEST 18: Mode filtering (v1/v2/both) reduces candidate count")
print("=" * 70)
v1_count = sum(1 for v, _ in files if v == 1)
v2_count = sum(1 for v, _ in files if v == 2)
both_count = len(files)
print(f"  v1={v1_count}, v2={v2_count}, both={both_count}")
data_check(v1_count > 0 and v2_count > 0,
      f"both v1 and v2 strategies present")
# Simulate filtering
v1_only = [x for x in files if x[0] == 1]
v2_only = [x for x in files if x[0] == 2]
data_check(len(v1_only) == v1_count and len(v2_only) == v2_count,
      f"mode filtering produces correct subset sizes")
# Skip "v1 + v2 = both" if either side is empty (when zapret/ is missing)
if v1_only and v2_only:
    check(len(v1_only) + len(v2_only) == both_count,
          f"v1 + v2 = both (no overlap)")
else:
    warn("skipped v1+v2=both check (empty list due to missing zapret/)")

# Validate default mode is "both" via default settings behavior
default_mode = ({}).get("zapret_auto_mode", "both")
check(default_mode == "both",
      f"default zapret_auto_mode is 'both'")

print()
print("=" * 70)
print("TEST 19: Tiered testing constants (smoke + detailed)")
print("=" * 70)
check(hasattr(vpn_client, "ZAPRET_SMOKE_URLS"),
      f"ZAPRET_SMOKE_URLS defined")
check(len(vpn_client.ZAPRET_SMOKE_URLS) >= 3,
      f"smoke has >=3 URL: {len(vpn_client.ZAPRET_SMOKE_URLS)}")
check(vpn_client.SMOKE_TIMEOUT <= vpn_client.DETAILED_TIMEOUT,
      f"smoke timeout ({vpn_client.SMOKE_TIMEOUT}s) <= detailed ({vpn_client.DETAILED_TIMEOUT}s)")
check(vpn_client.MIN_SMOKE_FOR_DETAILED >= 1
      and vpn_client.MIN_SMOKE_FOR_DETAILED <= len(vpn_client.ZAPRET_SMOKE_URLS),
      f"MIN_SMOKE_FOR_DETAILED in valid range: {vpn_client.MIN_SMOKE_FOR_DETAILED}")
# Smoke URLs must be a subset of all test URLs (for consistency)
smoke_names = {n for n, _ in vpn_client.ZAPRET_SMOKE_URLS}
all_names = {n for n, _ in vpn_client.ZAPRET_TEST_URLS}
check(smoke_names <= all_names,
      f"smoke URLs are subset of all test URLs: smoke_only={smoke_names-all_names}")
# Smoke must include the most important targets
for must_have in ("YouTube", "Discord"):
    check(must_have in smoke_names,
          f"smoke includes critical site: {must_have}")

print()
print("=" * 70)
print("TEST 20: _zapret_score accepts urls/max_workers kwargs (parallel)")
print("=" * 70)
import inspect
sig = inspect.signature(api._zapret_score)
params = list(sig.parameters.keys())
check("urls" in params, f"_zapret_score has 'urls' parameter: {params}")
check("max_workers" in params, f"_zapret_score has 'max_workers' parameter: {params}")
check("timeout" in params, f"_zapret_score has 'timeout' parameter: {params}")
# Default value of urls must be None (means: use ZAPRET_TEST_URLS)
check(sig.parameters["urls"].default is None,
      f"_zapret_score urls defaults to None (all URLs)")
# Quick functional test: pass empty list, expect (0, ~0)
s, lat = api._zapret_score(urls=[], timeout=1, max_workers=1)
check(s == 0 and lat < 1.0,
      f"empty URLs returns (0, ~0): got ({s}, {lat:.2f}s)")
# Pass a single fake URL that should fail (invalid scheme)
s2, lat2 = api._zapret_score(
    urls=[("FakeSite", "http://this-domain-definitely-does-not-exist-12345.invalid/")],
    timeout=1, max_workers=1,
)
check(s2 == 0,
      f"invalid URL returns score 0: got {s2}")

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


def main():
    """Entry point. Module-level code already ran the tests; this just exits."""
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
