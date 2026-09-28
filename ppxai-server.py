#!/usr/bin/env python3
"""
ppxai-server launcher for standalone executable.

This is the entry point for PyInstaller builds.
"""
import os
import sys

# Ensure the bundled app can find its modules
if getattr(sys, 'frozen', False):
    # Running as compiled executable. Remember where we were started first:
    # an announced server (ADR 0013, `--uds --announce`) must run in, and
    # report, the directory its launcher chose, not this binary's directory.
    os.environ.setdefault("PPXAI_LAUNCH_CWD", os.getcwd())
    os.chdir(os.path.dirname(sys.executable))

from ppxai.server.http import run_server

if __name__ == "__main__":
    run_server()
