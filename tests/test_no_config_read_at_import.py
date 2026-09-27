"""No ppxai module reads config at import time.

A module-level read loads the ConfigStore lazily, before any entry point's
`initialize()` has seeded `~/.ppxai/ppxai-config.json` or loaded `.env`,
and the store keeps that result. The one such read,
`engine/context.py`'s `MAX_FILE_SIZE = _get_max_injection_size()`, left the
first process on a fresh HOME with zero providers (ppxai-sre, 2026-09-27)
and froze `@tree`'s size limit for the life of the process. It was removed
the same day; this keeps new ones out.

Config belongs in a call made after `initialize()`: a property, a function,
or a value read when an object is built.

Runs in a fresh interpreter with a throwaway HOME, because this suite's
`pytest_configure` has already loaded config in-process. A planted
module-level read proves the probe detects one; a probe that detects
nothing would otherwise pass as clean.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

_PROBE = textwrap.dedent(r"""
    import importlib, json, os, pkgutil, sys

    hits, failed = [], {}

    def prof(frame, event, arg):
        if event != "call" or frame.f_code.co_name != "config":
            return
        if not frame.f_code.co_filename.replace("\\", "/").endswith("ppxai/config/store.py"):
            return
        f = frame.f_back
        while f is not None and f.f_code.co_name != "<module>":
            f = f.f_back
        if f is not None:
            hits.append(f"{f.f_globals.get('__name__')}:{f.f_lineno}")

    sys.setprofile(prof)
    import ppxai
    names = ["ppxai"] + [m.name for m in pkgutil.walk_packages(ppxai.__path__, "ppxai.")]
    if os.environ.get("PLANT"):
        names.append("planted_config_read")
    for name in names:
        if name.endswith("__main__"):
            continue
        try:
            importlib.import_module(name)
        except Exception as exc:  # optional extras; reported, not fatal
            failed[name] = type(exc).__name__
    sys.setprofile(None)
    print("RESULT " + json.dumps({"hits": sorted(set(hits)), "failed": failed,
                                  "imported": len(names) - len(failed)}))
""")

_PLANTED = "from ppxai.config import get_config\nVALUE = get_config()\n"


def _run(tmp_path, plant: bool) -> dict:
    home = tmp_path / ("home-plant" if plant else "home")
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "PPXAI_CONFIG_FILE"}
    env.update({"HOME": str(home), "USERPROFILE": str(home)})
    if plant:
        (tmp_path / "planted_config_read.py").write_text(_PLANTED, encoding="utf-8")
        env["PLANT"] = "1"
        env["PYTHONPATH"] = str(tmp_path) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE], cwd=home, env=env,
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")][-1]
    return json.loads(line[len("RESULT "):])


def test_no_module_reads_config_at_import(tmp_path):
    result = _run(tmp_path, plant=False)
    assert result["imported"] > 150, result  # the walk really covered the package
    assert result["hits"] == [], (
        "module-level config read(s) at import: "
        f"{result['hits']}. Read config in a call made after initialize() "
        "(a property, a function, or when an object is built), not at "
        "module scope."
    )


def test_the_probe_catches_a_planted_read(tmp_path):
    result = _run(tmp_path, plant=True)
    assert any(h.startswith("planted_config_read:") for h in result["hits"]), result
