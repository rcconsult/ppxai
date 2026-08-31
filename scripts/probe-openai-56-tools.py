#!/usr/bin/env python3
"""Probe the OpenAI 5.6 line for the function-tools / reasoning_effort hazard.

Re-runs the measurement behind
`benchmarks/tuning/openai-5.6-tools-hazard.json` (debt Item 55, ADR 0012 Q0h).

**What was measured 2026-08-31, and why the community report is misleading.**
The report said `gpt-5.6-sol` rejects function tools *combined with*
`reasoning_effort`. Both halves are wrong in the direction that matters:

- it is not sol-only — `terra` and `luna` behave identically;
- it is not the combination — sending `tools` **alone** already 400s, with no
  `reasoning_effort` in the request at all.

The 5.6 line evidently defaults to a non-`none` effort, so a caller does not
have to ask for reasoning to hit this. Any chat-completions-shaped client
that attaches a tools array to a 5.6 model gets a 400 out of the box, which
is exactly the shape ppxai sends for OpenAI.

OpenAI's own error names both remedies, and both were verified to produce a
REAL tool call rather than merely a 200:

    reasoning_effort="none"   -> works, but disables reasoning on models
                                 sold for reasoning
    /v1/responses             -> works, reasoning retained; ppxai already
                                 speaks this wire (ADR 0012 W2), so it is a
                                 table row rather than new code

Usage:

    uv run python scripts/probe-openai-56-tools.py            # matrix only
    uv run python scripts/probe-openai-56-tools.py --remedies # + both fixes
    uv run python scripts/probe-openai-56-tools.py --json

Costs a handful of tiny requests (16-400 max tokens each).
"""

import argparse
import json
import os
import sys

try:
    import httpx
    from openai import OpenAI
except ImportError:  # pragma: no cover - dependency guard
    print("needs the project venv: uv run python scripts/probe-openai-56-tools.py")
    sys.exit(2)


MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")

TOOL_CHAT = [
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get the current time in a timezone",
            "parameters": {
                "type": "object",
                "properties": {"tz": {"type": "string"}},
                "required": ["tz"],
            },
        },
    }
]
#: Same tool, the Responses wire's flatter shape (ADR 0012: each wire owns
#: its own request shape — this is that difference, concretely).
TOOL_RESPONSES = [
    {
        "type": "function",
        "name": "get_time",
        "description": "Get the current time in a timezone",
        "parameters": {
            "type": "object",
            "properties": {"tz": {"type": "string"}},
            "required": ["tz"],
        },
    }
]


def _client():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY not set")
        sys.exit(2)
    return OpenAI(api_key=key, http_client=httpx.Client(verify=True, timeout=120))


def _outcome(fn):
    """Run a call and reduce it to a short, comparable verdict."""
    try:
        return "200", fn()
    except Exception as exc:  # noqa: BLE001 - the error IS the measurement
        msg = str(exc)
        i = msg.find("'message':")
        detail = msg[i : i + 140] if i > 0 else msg[:140]
        return str(getattr(exc, "status_code", "?")), detail


def matrix(client, model):
    """The four cases that separate 'tools' from 'tools + effort'."""
    base = {"messages": [{"role": "user", "content": "say OK"}], "max_completion_tokens": 16}
    cases = {
        "baseline": {},
        "tools_only": {"tools": TOOL_CHAT},
        "reasoning_effort_only": {"reasoning_effort": "low"},
        "tools_plus_effort": {"tools": TOOL_CHAT, "reasoning_effort": "low"},
    }
    out = {}
    for label, extra in cases.items():
        status, _ = _outcome(
            lambda e=extra: client.chat.completions.create(model=model, **base, **e)
        )
        out[label] = status
    return out


def remedies(client, model):
    """Both documented fixes — and whether a tool actually FIRES, not just 200."""
    prompt = "What time is it in Tokyo? Use the get_time tool."
    out = {}

    def _chat():
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=200,
            tools=TOOL_CHAT,
            reasoning_effort="none",
        )

    status, res = _outcome(_chat)
    calls = 0
    if status == "200":
        calls = len(res.choices[0].message.tool_calls or [])
    out["reasoning_effort_none"] = {"status": status, "tool_calls": calls}

    def _resp():
        return client.responses.create(
            model=model, input=prompt, max_output_tokens=400, tools=TOOL_RESPONSES
        )

    status, res = _outcome(_resp)
    fcs = 0
    if status == "200":
        fcs = sum(
            1
            for i in (res.model_dump().get("output") or [])
            if isinstance(i, dict) and i.get("type") == "function_call"
        )
    out["responses_wire"] = {"status": status, "function_calls": fcs}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", action="append", dest="models", help="repeatable")
    ap.add_argument("--remedies", action="store_true", help="also probe both fixes")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args()

    client = _client()
    models = args.models or list(MODELS)
    report = {}

    for model in models:
        report[model] = {"matrix": matrix(client, model)}
        if args.remedies:
            report[model]["remedies"] = remedies(client, model)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("OpenAI 5.6 function-tools hazard -- /v1/chat/completions\n")
    for model, data in report.items():
        m = data["matrix"]
        print(f"  {model}")
        for label, status in m.items():
            flag = "  <-- THE FINDING" if label == "tools_only" and status != "200" else ""
            print(f"    {label:24s} {status}{flag}")
        if "remedies" in data:
            r = data["remedies"]
            print(
                f"    remedy effort=none       {r['reasoning_effort_none']['status']}"
                f" (tool_calls={r['reasoning_effort_none']['tool_calls']})"
            )
            print(
                f"    remedy responses wire    {r['responses_wire']['status']}"
                f" (function_calls={r['responses_wire']['function_calls']})"
            )
        print()

    broken = [m for m, d in report.items() if d["matrix"].get("tools_only") != "200"]
    if broken:
        print(
            "TOOLS ALONE FAIL on: " + ", ".join(broken) + "\n"
            "Not a tools+effort interaction — no reasoning_effort was sent.\n"
            "Fix by giving these models wire_protocol='responses' (ADR 0012);\n"
            "reasoning_effort='none' also works but disables the reasoning\n"
            "these models are sold for."
        )
    else:
        print(
            "Tools alone now succeed on every probed model — the hazard has\n"
            "been fixed upstream. Update\n"
            "benchmarks/tuning/openai-5.6-tools-hazard.json and debt Item 55."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
