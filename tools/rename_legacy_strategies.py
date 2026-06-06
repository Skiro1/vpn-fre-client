# -*- coding: utf-8 -*-
"""
Migration: rename legacy Zapret strategy files to the unified naming scheme
(prefixed with "z1 - " so they sort together with youtubediscord z1 - files).

Why:
    Old releases stored Flowseal files as `general (ALT).bat` and AntiZapret
    files as `antizapret (auto v1).bat` (no version prefix). The new
    convention used by the GUI is to prefix every v1 strategy with `z1 - `.

What this does:
    1. For every `*.bat` directly in zapret/ that does NOT start with
       `z1 - ` or `z2 - `, and is not `service*.bat`, rename it to
       `z1 - <old_name>.bat`. (Skip if the target already exists.)
    2. Idempotent: running it twice is a no-op.
    3. Safe by default: prints the plan, asks `y/N` unless `--yes` is given.

Usage:
    python tools/rename_legacy_strategies.py            # interactive
    python tools/rename_legacy_strategies.py --yes      # non-interactive
    python tools/rename_legacy_strategies.py --dry-run  # show what would happen
"""
import argparse
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V1_DIR = ROOT / "zapret"
V2_DIR = ROOT / "zapret" / "zapret2"

PREFIX_V1 = "z1 - "
PREFIX_V2 = "z2 - "
EXCLUDE_PREFIXES = ("service",)


def has_any_prefix(name: str) -> bool:
    low = name.lower()
    return low.startswith(PREFIX_V1) or low.startswith(PREFIX_V2)


def is_excluded(name: str) -> bool:
    low = name.lower()
    return any(low.startswith(p) for p in EXCLUDE_PREFIXES)


def plan_renames(directory: Path, prefix: str) -> list[tuple[Path, Path]]:
    """Return [(source, target), ...] for legacy files in directory."""
    if not directory.is_dir():
        return []
    out = []
    for p in sorted(directory.glob("*.bat")):
        if has_any_prefix(p.name):
            continue
        if is_excluded(p.name):
            continue
        target = directory / f"{prefix}{p.name}"
        if target.exists():
            # Don't overwrite an existing prefixed file
            continue
        out.append((p, target))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--yes", "-y", action="store_true",
                    help="Apply renames without confirmation")
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="Print what would be renamed, but do nothing")
    args = ap.parse_args()

    plan_v1 = plan_renames(V1_DIR, PREFIX_V1)
    plan_v2 = plan_renames(V2_DIR, PREFIX_V2)
    total = len(plan_v1) + len(plan_v2)

    if total == 0:
        print("[OK] No legacy strategy files to rename (already migrated).")
        return 0

    print(f"Will rename {len(plan_v1)} file(s) in zapret/ and "
          f"{len(plan_v2)} in zapret/zapret2/:")
    for src, dst in plan_v1:
        print(f"  {src.name}  ->  {dst.name}")
    for src, dst in plan_v2:
        print(f"  {src.relative_to(ROOT)}  ->  {dst.name}")

    if args.dry_run:
        print("\n[dry-run] No changes made.")
        return 0

    if not args.yes:
        try:
            ans = input("\nProceed? [y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 1

    moved = 0
    for src, dst in plan_v1 + plan_v2:
        shutil.move(str(src), str(dst))
        moved += 1
    print(f"\n[OK] Renamed {moved} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
