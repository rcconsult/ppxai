# Runtime hook: suppress SIGINT during the entire startup/import phase.
#
# PyInstaller on macOS has a race condition (issue #2349, open since 2017):
# SIGINT can arrive during the import of large modules (e.g. google.genai.types
# with its 15000-line pydantic model construction), crashing the process before
# the server has a chance to install its own signal handlers.
#
# SIG_IGN is set here (before ANY module imports) to discard any pending or
# in-flight SIGINT during startup. Uvicorn installs its own SIGINT handler
# when it starts, restoring normal Ctrl+C behavior for the running server.
import signal

signal.signal(signal.SIGINT, signal.SIG_IGN)
