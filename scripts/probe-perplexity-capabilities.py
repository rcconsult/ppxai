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
  python3 scripts/probe-perplexity-capabilities.py --api-path responses
  python3 scripts/probe-perplexity-capabilities.py --survey-responses

`--api-path responses` runs the same drift check over POST /v1/responses --
the wire the Agent API serves and the one the whole provider moves to when
the chat-completions endpoint retires (2026-09-27, see
docs/plan-adr-0012-implementation.md).

`--survey-responses` is plan W0's one-off measurement battery: model
existence under bare vs namespaced IDs, native tools, citation location in
the Responses envelope, streaming, and the max_output_tokens requirement.
It measures and reports -- it judges no table (exit 0 unless nothing could
be measured).

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
    PERPLEXITY_TOOL_REJECTING_MODELS,
)

BASE_URL = "https://api.perplexity.ai"

#: The Responses API lives under /v1 (measured 2026-08-15: POST /v1/responses
#: and POST /v1/agent are both live; /chat/completions has no /v1 prefix).
#: The survey re-verifies this rather than trusting it.
RESPONSES_BASE_URL = BASE_URL + "/v1"

#: Extra IDs the survey checks beyond the shipped roster: the namespaced
#: form of sonar (the 2026-08-13 Agent-API roster lists ONLY this form) and
#: one cross-vendor model (the planned W3 canary; also the measured carrier
#: of the max_output_tokens requirement).
SURVEY_EXTRA_MODELS = ("perplexity/sonar", "anthropic/claude-sonnet-5")

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

#: The survey's existence request doubles as the citation probe, so its
#: prompt must actually invite a web search -- the tool prompt above never
#: does, and a search-free answer carries no citations to find.
SURVEY_PROMPT = "In one short sentence: what is the latest stable Python release?"

#: The citation probe must actually trigger a search.
CITATION_PROMPT = "What is the latest stable Python release? Search the web."

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
    """What the SHIPPED RESOLVER claims for this model.

    Reads the same resolution the send path reads, deliberately. Until ADR
    0012 this asked `PERPLEXITY_NATIVE_TOOL_MODELS` -- a set the provider
    consulted at the time, but which the seed glob rows now decide instead.
    A probe that validates a table production no longer reads reports
    agreement while the live behaviour drifts, which is exactly the
    "declared here, decided there" shape debt Item 61 is about.

    Unmeasured models resolve `prompt_based`, so they map to REJECTS -- the
    table's safe default, unchanged.
    """
    return NATIVE if _resolver_says_capable(model) else REJECTS


def _resolver_says_capable(model):
    from ppxai.engine.model_facts import shipped_facts_for_model

    return shipped_facts_for_model(model).tool_mode != "prompt_based"


def classify(status, body):
    """Map an HTTP outcome onto a capability verdict."""
    if status == 200:
        return NATIVE
    if status == 400:
        low = str(body).lower()
        if "invalid_model" in low or "invalid model" in low:
            return ABSENT
        # Responses-wire wording (measured 2026-08-30): 'validation failed:
        # model "sonar" is not supported'. An unknown model, not a shape issue.
        if "model" in low and "is not supported" in low and "tool" not in low:
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


def to_responses_tool(chat_tool):
    """Convert a chat-completions tool to the Responses API's flat shape.

    Chat:      {"type": "function", "function": {"name", "description", "parameters"}}
    Responses: {"type": "function", "name", "description", "parameters"}

    Same conversion `openai_native._convert_tools_for_responses` performs;
    duplicated here only because the probe deliberately imports nothing from
    the provider under test beyond its capability tables.
    """
    fn = chat_tool["function"]
    return {
        "type": "function",
        "name": fn["name"],
        "description": fn["description"],
        "parameters": fn["parameters"],
    }


def find_citation_paths(payload, _prefix=""):
    """Walk a response payload; return dot-paths whose key smells of citations.

    Pure and offline-testable. The chat-completions envelope carries a
    top-level `citations` list; where (or whether) the Responses envelope
    carries them is exactly what W0 (c) exists to measure, so the survey
    reports every candidate path rather than asserting one.
    """
    hits = []
    keywords = ("citation", "search_result", "annotation", "source")
    # `search_results` arrives as an output ITEM whose type is the marker,
    # so match on the value too, not only on keys.
    if isinstance(payload, dict) and payload.get("type") == "search_results":
        hits.append("{}[type=search_results]".format(_prefix or "output"))
    if isinstance(payload, dict):
        for k, v in payload.items():
            path = "{}.{}".format(_prefix, k) if _prefix else str(k)
            if any(w in str(k).lower() for w in keywords) and v:
                hits.append(path)
            hits.extend(find_citation_paths(v, path))
    elif isinstance(payload, list):
        for i, item in enumerate(payload[:5]):  # sample, not exhaustive
            hits.extend(find_citation_paths(item, "{}[{}]".format(_prefix, i)))
    return hits


def probe_responses(client, model):
    """Drift-check one model over POST /v1/responses.

    Same verdict semantics as `probe()`: the capability is proven by the
    endpoint ACCEPTING the tools array. `called_tool` is true when the
    output contains a function_call item.
    """
    try:
        resp = client.responses.create(
            model=model,
            input=PROBE_PROMPT,
            tools=[to_responses_tool(PROBE_TOOL)],
            max_output_tokens=PROBE_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 -- classify, never swallow
        status = getattr(exc, "status_code", None)
        verdict = classify(status, exc) if status else ERROR
        return verdict, _one_line(exc), False

    called = False
    try:
        called = any(
            getattr(item, "type", "") == "function_call" for item in resp.output
        )
    except Exception:  # noqa: BLE001
        pass
    return NATIVE, "accepted tools array", called


def _survey_request(client, model, **overrides):
    """One Responses request; returns (status, resp_or_exc)."""
    kwargs = {
        "model": model,
        "input": SURVEY_PROMPT,
        "max_output_tokens": PROBE_MAX_TOKENS,
    }
    kwargs.update(overrides)
    for key in [k for k, v in list(kwargs.items()) if v is None]:
        del kwargs[key]
    try:
        return 200, client.responses.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        # Same idiom as probe()/probe_responses(): a missing status_code is
        # not a status, and classify() turns None into ERROR.
        return getattr(exc, "status_code", None), exc


def survey_responses(api_key, json_out):
    """Plan W0's measurement battery over the Responses wire.

    Measures, per model (roster + SURVEY_EXTRA_MODELS): existence, native
    tools, citation candidate paths, streaming. Plus two one-off checks:
    which base_url serves /responses, and whether max_output_tokens is
    required (measured on one Sonar and one anthropic/* model).
    Reports; judges no table.
    """
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=RESPONSES_BASE_URL)
    models = list(shipped_roster()) + list(SURVEY_EXTRA_MODELS)
    report = {"base_url": {}, "models": {}, "max_output_tokens_required": {}}

    # (f) which base_url serves /responses -- one cheap request each.
    for base in (RESPONSES_BASE_URL, BASE_URL):
        c = OpenAI(api_key=api_key, base_url=base)
        status, _ = _survey_request(c, "sonar-pro")
        report["base_url"][base] = status or "no status (connection/other)"
    if report["base_url"][RESPONSES_BASE_URL] not in (200, 400):  # noqa: PLR2004
        alt = report["base_url"][BASE_URL]
        if alt in (200, 400):
            client = OpenAI(api_key=api_key, base_url=BASE_URL)

    for model in models:
        row = {}
        # (a) existence: plain request, no tools
        status, resp = _survey_request(client, model)
        row["exists"] = classify(status, resp) if status else ERROR
        row["exists_detail"] = "" if status == 200 else _one_line(resp, 100)
        if status == 200:
            # (c) citations. MEASURED 2026-08-30: on this wire search is an
            # explicit TOOL, not implicit as on Sonar chat-completions -- a
            # plain request runs no search and carries no citations. So the
            # citation probe must ask for web_search, and the answer lives in
            # a `search_results` OUTPUT ITEM (not in text annotations, which
            # come back empty).
            c_status, c_resp = _survey_request(
                client, model, tools=[{"type": "web_search"}], input=CITATION_PROMPT
            )
            payload = {}
            if c_status == 200:
                try:
                    payload = c_resp.model_dump()
                except Exception:  # noqa: BLE001
                    payload = {}
            row["citation_paths"] = sorted(set(find_citation_paths(payload)))[:8]
            row["search_result_items"] = sum(
                len(i.get("results") or [])
                for i in payload.get("output", [])
                if isinstance(i, dict) and i.get("type") == "search_results"
            )
            # (b) tools
            verdict, detail, called = probe_responses(client, model)
            row["tools"] = verdict
            row["tools_called"] = called
            row["tools_detail"] = detail if verdict != NATIVE else ""
            # (d) streaming -- limited to the survey extras (the models
            # measured to EXIST on this wire) to keep the bill small.
            if model in SURVEY_EXTRA_MODELS:
                s_status, s_resp = _survey_request(client, model, stream=True)
                if s_status == 200:
                    try:
                        events = sum(1 for _ in s_resp)
                        row["streaming"] = "OK ({} events)".format(events)
                    except Exception as exc:  # noqa: BLE001
                        row["streaming"] = "BROKE mid-stream: " + _one_line(exc, 60)
                else:
                    row["streaming"] = "HTTP {}: {}".format(
                        s_status, _one_line(s_resp, 60)
                    )
        report["models"][model] = row

    # (e) is max_output_tokens required? One Sonar-family + one anthropic/*.
    for model in SURVEY_EXTRA_MODELS:
        if report["models"].get(model, {}).get("exists") != NATIVE:
            continue
        status, resp = _survey_request(client, model, max_output_tokens=None)
        report["max_output_tokens_required"][model] = (
            "no (200 without it)" if status == 200
            else "YES (HTTP {}: {})".format(status, _one_line(resp, 80))
        )

    if json_out:
        print(json.dumps(report, indent=2))
        return 0

    print("Responses-wire survey (plan W0) -- measured live")
    print()
    print("  base_url serving /responses:")
    for base, status in report["base_url"].items():
        print("    {:<38} HTTP {}".format(base, status))
    print()
    print(
        "  {:<28} {:<8} {:<8} {:<6} {:<22} CITATION PATHS".format(
            "MODEL", "EXISTS", "TOOLS", "CALLED", "STREAMING"
        )
    )
    for model, row in report["models"].items():
        print(
            "  {:<28} {:<8} {:<8} {:<6} {:<22} {}".format(
                model,
                row.get("exists", "?"),
                row.get("tools", "-"),
                "yes" if row.get("tools_called") else "-",
                row.get("streaming", "-"),
                (
                    "{} results @ {}".format(
                        row["search_result_items"],
                        ", ".join(row.get("citation_paths", [])) or "?",
                    )
                    if row.get("search_result_items")
                    else (", ".join(row.get("citation_paths", [])) or "-")
                ),
            )
        )
        for key in ("exists_detail", "tools_detail"):
            if row.get(key):
                print("  {:<28}   {}".format("", row[key]))
    print()
    print("  max_output_tokens required?")
    for model, answer in report["max_output_tokens_required"].items():
        print("    {:<28} {}".format(model, answer))

    measured = [r for r in report["models"].values() if r.get("exists") != ERROR]
    return 0 if measured else 2


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
    ap.add_argument(
        "--api-path",
        choices=("chat", "responses"),
        default="chat",
        help="which wire the drift check probes (default: chat)",
    )
    ap.add_argument(
        "--survey-responses",
        action="store_true",
        help="run plan W0's Responses-wire measurement battery instead of the drift check",
    )
    args = ap.parse_args()

    models = args.models or shipped_roster()

    if args.dry_run:
        endpoint = (
            RESPONSES_BASE_URL + "/responses"
            if args.api_path == "responses"
            else BASE_URL + "/chat/completions"
        )
        print(
            "DRY RUN -- no API calls. Would probe {} model(s) at "
            "{},".format(len(models), endpoint)
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

    if args.survey_responses:
        return survey_responses(api_key, args.json)

    wire_base = RESPONSES_BASE_URL if args.api_path == "responses" else BASE_URL
    probe_fn = probe_responses if args.api_path == "responses" else probe
    client = OpenAI(api_key=api_key, base_url=wire_base)

    if args.check_models_endpoint:
        print("Enumeration check:")
        check_models_endpoint(client)
        print()

    results = []
    for model in models:
        verdict, detail, called = probe_fn(client, model)
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
            "Perplexity capability probe -- {} model(s), live at {} ({})".format(
                len(results), wire_base, args.api_path
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
            if args.api_path == "responses" and r["verdict"] == ABSENT:
                # Not a table bug: the capability table describes the CHAT
                # wire. An ABSENT here means this model ID is not served on
                # the Responses wire at all -- a routing/ID fact (plan W0
                # (a)), whose remedy is the per-model wire table, not the
                # tool-capability sets.
                print(
                    "  {}: not served on the responses wire (ABSENT). This is "
                    "an ID/routing fact, not a tool-capability drift -- see "
                    "docs/plan-adr-0012-implementation.md W0 (a).".format(
                        r["model"]
                    ),
                    file=sys.stderr,
                )
            else:
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
