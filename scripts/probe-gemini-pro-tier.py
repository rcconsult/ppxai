#!/usr/bin/env python3
"""Ask Google's ListModels API whether a GA Gemini 3.x Pro exists yet.

Debt Item 54. `GEMINI_DEPRECATIONS` migrates `gemini-2.5-pro` (sunset
2026-10-16, earliest) to `gemini-3.1-pro-preview` — a PREVIEW — because on
2026-09-01 no GA successor existed in the Pro tier. That is a deliberate
choice, not staleness, and it stays correct only while it stays true.

This script is the check. One read-only ListModels call, no generation, so
it costs nothing beyond the request.

The subtlety worth keeping: `gemini-pro-latest` LOOKS like a GA id and is
not a usable migration target. It is an unpinned alias — `displayName`
"Gemini Pro Latest", no `version` field — so it names no stable contract
and can silently change under an operator. A named preview is the better
target. Any GA candidate this script reports must therefore be checked for
a real `version`, which it does.

Usage:
    uv run python scripts/probe-gemini-pro-tier.py
    uv run python scripts/probe-gemini-pro-tier.py --json

Exit codes:
    0  probe ran; no GA 3.x Pro found (the table's advice stands)
    1  probe ran; a GA 3.x Pro candidate EXISTS -> update the table
    2  probe could not run (no key, network failure)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models"


def _key() -> str | None:
    try:
        from ppxai.config.loader import initialize as _init

        _init()  # loads ~/.ppxai/.env
    except Exception:  # noqa: BLE001 — the env may already carry the key
        pass
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _list_models(key: str) -> list[dict]:
    url = f"{API}?key={key}&pageSize=200"
    with urllib.request.urlopen(url, timeout=45) as resp:
        return json.loads(resp.read()).get("models", [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    key = _key()
    if not key:
        print("no GEMINI_API_KEY / GOOGLE_API_KEY found", file=sys.stderr)
        return 2

    try:
        models = _list_models(key)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    pro = [
        m
        for m in models
        if "pro" in m["name"].lower() and "gemini-3" in m["name"].lower()
    ]

    # A GA candidate must clear three filters. The first version of this
    # script had only the first two and reported `gemini-3-pro-image` as a
    # GA successor to `gemini-2.5-pro` — i.e. it would have told an operator
    # to migrate a TEXT workload onto an IMAGE model. Caught by running it.
    #
    #  1. not a preview, and carries a real pinned `version` — this is what
    #     rejects `gemini-pro-latest`, an unpinned alias whose `version`
    #     merely repeats its displayName;
    #  2. not an image/tts/live variant — `supportedGenerationMethods` does
    #     NOT separate these (both text and image Pro list generateContent),
    #     so the name is the only signal the API gives;
    #  3. supports `createCachedContent`, which on 2026-09-01 the text Pro
    #     models carry and the image ones do not. Kept as a second, positive
    #     signal so a future id whose name we do not anticipate still has to
    #     look like a text model to qualify.
    NON_TEXT = ("image", "tts", "live", "embedding", "vision")
    ga = [
        m
        for m in pro
        if "preview" not in m["name"]
        and (m.get("version") or "").strip()
        and (m.get("version") or "") != m.get("displayName")
        and not any(t in m["name"].lower() for t in NON_TEXT)
        and "createCachedContent" in (m.get("supportedGenerationMethods") or [])
    ]

    if args.json:
        print(
            json.dumps(
                {
                    "total_models": len(models),
                    "gemini_3_pro_ids": [m["name"].split("/")[-1] for m in pro],
                    "ga_candidates": [m["name"].split("/")[-1] for m in ga],
                },
                indent=2,
            )
        )
    else:
        print(f"ListModels returned {len(models)} models\n")
        print("Gemini 3.x Pro ids:")
        for m in pro:
            mid = m["name"].split("/")[-1]
            kind = "PREVIEW" if "preview" in mid else "ga-looking"
            print(f"  {mid:42} {kind:11} version={m.get('version') or '(none)'}")
        print()
        if ga:
            print("GA CANDIDATE(S) FOUND — the table's preview target is now stale:")
            for m in ga:
                print(f"  {m['name'].split('/')[-1]}  version={m.get('version')}")
            print("\nUpdate `replacement` for gemini-2.5-pro and gemini-3-pro-preview")
            print("in ppxai/engine/model_deprecations.py, and drop the preview caveat.")
        else:
            print("No GA 3.x Pro. Pointing at gemini-3.1-pro-preview remains correct.")
            print("(`gemini-pro-latest` is an unpinned alias, not a GA target.)")

    return 1 if ga else 0


if __name__ == "__main__":
    raise SystemExit(main())
