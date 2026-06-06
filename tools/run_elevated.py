# -*- coding: utf-8 -*-
"""
Self-elevating launcher. Re-launches itself with UAC prompt if not already
admin. Used to run the runtime strategy-launch test which needs to spawn
winws.exe (and therefore load the WinDivert kernel driver).

Usage:
    python tools/run_elevated.py tests/test_strategies_launch.py
"""
import sys
import os
import ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


if __name__ == "__main__":
    script_args = sys.argv[1:]
    if not script_args:
        print("Usage: run_elevated.py <script.py> [args...]")
        sys.exit(1)

    if is_admin():
        # Already elevated: just exec the target script
        with open(script_args[0], "r", encoding="utf-8") as f:
            code = f.read()
        sys.argv = script_args
        exec(compile(code, script_args[0], "exec"), {"__name__": "__main__"})
    else:
        # Re-launch ourselves via ShellExecuteW with "runas" verb -> UAC prompt.
        params = " ".join(f'"{a}"' for a in script_args)
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{__file__}" {params}', None, 0,
        )
        if rc <= 32:
            print(f"Elevation failed (ShellExecuteW returned {rc}).")
            print("Please run the test from an elevated PowerShell/cmd.")
            sys.exit(2)
        else:
            print("Elevation requested. Approve the UAC dialog to continue.")
            sys.exit(0)
