#!/usr/bin/env python3
"""Probe Perplexity models for native tool-calling support, live.

Perplexity has **no `/models` endpoint** (404, re-verifiable here with
``--check-models-endpoint``), so its roster and capabilities cannot be
enumerated the way every other provider's can. Capability must therefore be
either DECLARED (the table in ``ppxai/engine/providers/perplexity.py``) or
PROBED. This script is the probe, and it answers exactly one question:

    does the shipped capability table still match what the API serves?

The table went stale once already -- Perplexity shipped tool calling for
``sonar-pro`` and nothing told us for roughly a month, which is the whole of
debt Item 43. A stale table is silent by construction: every layer above it
resolves a confident ``native=False`` and users simply get worse answers.

Method: one ``/chat/completions`` request per model carrying a minimal but
REAL ``tools=[...]`` array, then classify the outcome:

  NATIVE    HTTP 200 -- whether or not the model chose to call the tool. The
            capability is proven by the endpoint ACCEPTING the array, not by
            the model's willingness to use it on one prompt.
  REJECTS   HTTP 400 naming tool calling as unsupported.
  SHAPE     HTTP 400 complaining about the tool PARAMETER SHAPE. A different
            kind of failure (``sonar-deep-research``): the model may be usable
            with a stricter schema, so it is not the same as REJECTS.
  ABSENT    HTTP 400 ``invalid_model`` -- not served by this endpoint at all.
  ERROR     anything else (auth, network, 5xx) -- NOT a capability verdict.

That ERROR row is deliberate and load-bearing. An infrastructure failure must
never be scored as "model lacks the capability": on this project a provider
error was twice misread as a clean zero-tool-call result in a single session.
ERROR exits non-zero and is never folded into a drift verdict.

Usage:
  python3 scripts/probe-perplexity-capabilities.py              # shipped roster
  python3 scripts/probe-perplexity-capabilities.py --dry-run    # no API calls
  python3 scripts/probe-perplexity-capabilities.py --json
  python3 scripts/probe-perplexity-capabilities.py --model sonar-pro
  python3 scripts/probe-perplexity-capabilities.py --check-models-endpoint

Exit codes:
  0  every probed model matched the shipped table
  1  DRIFT -- a model's measured capability disagrees with the table
  2  ERROR -- a probe could not be completed (no verdict; table NOT judged)
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ppxai.engine.providers.perplexity import (  # noqa: E402
    PERPLEXITY_NATIVE_TOOL_MODELS,
    PERPLEXITY_TOOL_REJECTING_MODELS,
)

BASE_URL = "https://api.perplexity.ai"

#: Verdicts. Only NATIVE/REJECTS/SHAPE/ABSENT are capability statements.
NATIVE, REJECTS, SHAPE, ABSENT, ERROR = "NATIVE", "REJECTS", "SHAPE", "ABSENT", "ERROR"

#: A minimal, well-formed tool. Trivial on purpose: the probe tests whether
#: the ENDPOINT accepts a tools array, not whether the model can solve
#: anything. A complex schema would confound "model can't" with "schema
#: rejected" -- precisely the ambiguity that makes sonar-deep-research's 400
#: hard to read.
PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "Get the current time in a given timezone.",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "IANA timezone name"},
            },
            "required": ["timezone"],
        },
    },
}

PROBE_PROMPT = "What time is it in UTC? Use the get_time tool."

#: Cheap on purpose -- this runs against a real, billed key.
PROBE_MAX_TOKENS = 64


def shipped_roster():
    """The models ppxai actually configures, read from the example config.

    Read from the file rather than hardcoded so the probe follows the shipped
    roster automatically: a model added to config but never measured starts
    being probed without anyone editing this script.
    """
    cfg = json.loads(
        (REPO_ROOT / "ppxai-config.example.json").read_text(encoding="utf-8")
    )
    models = cfg.get("providers", {}).get("perplexity", {}).get("models", {})
    return sorted(models.keys())


def expected_verdict(model):
    """What the shipped capability table claims for this model."""
    if model in PERPLEXITY_NATIVE_TOOL_MODELS:
        return NATIVE
    if model in PERPLEXITY_TOOL_REJECTING_MODELS:
        return REJECTS
    return REJECTS  # table's safe default: unmeasured => assumed not capable


def classify(status, body):
    """Map an HTTP outcome onto a capability verdict."""
    if status == 200:
        return NATIVE
    if status == 400:
        low = str(body).lower()
        if "invalid_model" in low or "invalid model" in low:
            return ABSENT
        # Order matters: a parameter-SHAPE complaint mentions "tool" too, so
        # test the shape wording before the generic unsupported wording.
        if "must be a json object" in low or "tool parameters" in low:
            return SHAPE
        if "tool" in low and ("not supported" in low or "does not support" in low):
            return REJECTS
        return SHAPE
    return ERROR


def _one_line(text, limit=150):
    flat = " ".join(str(text).split())
    return flat[:limit] + ("..." if len(flat) > limit else "")


def probe(client, model):
    """Probe one model. Returns (verdict, detail, called_tool)."""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": PROBE_PROMPT}],
            tools=[PROBE_TOOL],
            tool_choice="auto",
            max_tokens=PROBE_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 -- classify, never swallow
        status = getattr(exc, "status_code", None)
        verdict = classify(status, exc) if status else ERROR
        return verdict, _one_line(exc), False

    called = False
    try:
        msg = resp.choices[0].message
        called = bool(getattr(msg, "tool_calls", None))
    except Exception:  # noqa: BLE001
        pass
    return NATIVE, "accepted tools array", called


def check_models_endpoint(client):
    """Re-verify the documented absence of a /models endpoint."""
    try:
        listing = client.models.list()
        ids = [m.id for m in listing.data]
        print(
            "  /models RESPONDED with {} models -- the plan's 'no /models "
            "endpoint' premise has CHANGED:".format(len(ids))
        )
        for mid in sorted(ids):
            print("    {}".format(mid))
    except Exception as exc:  # noqa: BLE001
        status = getattr(exc, "status_code", "?")
        print(
            "  /models -> HTTP {} (expected 404: capability cannot be "
            "enumerated) [{}]".format(status, _one_line(exc, 80))
        )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--model",
        action="append",
        dest="models",
        help="probe only this model (repeatable); default: shipped roster",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be probed, make no API calls",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument(
        "--check-models-endpoint",
        action="store_true",
        help="also re-verify that GET /models is still absent",
    )
    args = ap.parse_args()

    models = args.models or shipped_roster()

    if args.dry_run:
        print(
            "DRY RUN -- no API calls. Would probe {} model(s) at "
            "{}/chat/completions,".format(len(models), BASE_URL)
        )
        print(
            "one request each, max_tokens={}, tool={}.".format(
                PROBE_MAX_TOKENS, PROBE_TOOL["function"]["name"]
            )
        )
        print()
        for m in models:
            print("  {:<24} table says {}".format(m, expected_verdict(m)))
        return 0

    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        env = Path.home() / ".ppxai" / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("PERPLEXITY_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        print("ERROR: no PERPLEXITY_API_KEY (env or ~/.ppxai/.env)", file=sys.stderr)
        return 2

    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai SDK not installed", file=sys.stderr)
        return 2

    client = OpenAI(api_key=api_key, base_url=BASE_URL)

    if args.check_models_endpoint:
        print("Enumeration check:")
        check_models_endpoint(client)
        print()

    results = []
    for model in models:
        verdict, detail, called = probe(client, model)
        exp = expected_verdict(model)
        # The table has only two sets, so it cannot express SHAPE separately
        # from REJECTS -- both mean "not natively tool-capable". Only a
        # NATIVE-vs-not disagreement constitutes drift.
        measured_native = verdict == NATIVE
        table_native = exp == NATIVE
        if verdict == ERROR:
            state = "ERROR"
        elif measured_native == table_native:
            state = "OK"
        else:
            state = "DRIFT"
        results.append(
            {
                "model": model,
                "verdict": verdict,
                "expected": exp,
                "state": state,
                "called_tool": called,
                "detail": detail,
            }
        )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(
            "Perplexity capability probe -- {} model(s), live at {}".format(
                len(results), BASE_URL
            )
        )
        print()
        print("  {:<24} {:<9} {:<9} {:<6} DETAIL".format("MODEL", "MEASURED", "TABLE", ""))
        for r in results:
            mark = {"OK": "ok", "DRIFT": "DRIFT", "ERROR": "ERROR"}[r["state"]]
            tool = " (called tool)" if r["called_tool"] else ""
            print(
                "  {:<24} {:<9} {:<9} {:<6} {}{}".format(
                    r["model"], r["verdict"], r["expected"], mark, r["detail"], tool
                )
            )
        print()

    errors = [r for r in results if r["state"] == "ERROR"]
    drift = [r for r in results if r["state"] == "DRIFT"]

    if errors:
        print(
            "ERROR: {} probe(s) did not complete -- no capability verdict, "
            "table NOT judged:".format(len(errors)),
            file=sys.stderr,
        )
        for r in errors:
            print("  {}: {}".format(r["model"], r["detail"]), file=sys.stderr)
        return 2
    if drift:
        print(
            "DRIFT: {} model(s) disagree with the shipped table.".format(len(drift)),
            file=sys.stderr,
        )
        for r in drift:
            print(
                "  {}: measured {}, table says {} -- update "
                "PERPLEXITY_NATIVE_TOOL_MODELS in "
                "ppxai/engine/providers/perplexity.py".format(
                    r["model"], r["verdict"], r["expected"]
                ),
                file=sys.stderr,
            )
        return 1
    print("Table matches the live API for every probed model.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
