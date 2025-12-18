#!/usr/bin/env python3
"""
ppxai-server launcher for standalone executable.

This is the entry point for PyInstaller builds.
"""
import sys
import os

# Ensure the bundled app can find its modules
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    os.chdir(os.path.dirname(sys.executable))

from ppxai.server.http import run_server

if __name__ == "__main__":
    run_server()
