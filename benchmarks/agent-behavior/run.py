#!/usr/bin/env python3
"""Cross-provider agent-behavior benchmark (v1.19.x).

Drives POST /v1/agent/task against a running ppxai-server and scores, per
(provider, model, task), whether the model USED its granted tool vs.
substituted a native capability — the empirical check behind the
bounded-agent system-prompt framing (debt Item 37i).

See README.md. Standalone (stdlib only) so it runs without the benchmark
extras; talks HTTP to the real server like any consumer would.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional


# --------------------------------------------------------------------------
# Provider/model matrix. Models chosen per the v1.19.x config; override with
# --providers. nvidia/nemotron is the known-good tool-caller baseline;
# perplexity/sonar is the suspected substitution case (the whole reason).
# --------------------------------------------------------------------------
# Models = each provider's CONFIGURED default_model on the target install
# (verified present, so a run can't 404 on a wrong id). Override per run with
# --model-<provider> if you want a specific model. nvidia's default (qwen) is
# the known-good native-tool-caller baseline; perplexity/sonar-pro is the
# suspected substitution case.
PROVIDER_MATRIX = {
    "nvidia": "qwen/qwen3.5-122b-a10b",
    "perplexity": "sonar-pro",
    "gemini": "gemini-3.1-pro-preview",
    "openai": "gpt-5.4-mini",
}


# --------------------------------------------------------------------------
# Tasks — each ENGINEERED to tempt native substitution: grant exactly one
# tool that SHOULD be used; phrase the task so a native capability could
# "answer" it instead. `marker` is a substring the correct tool result makes
# present in the final answer (coarse correctness signal).
# --------------------------------------------------------------------------
@dataclass
class Task:
    id: str
    task: str
    tools: list           # the grant
    network: list         # allow_outbound
    granted_tool: str     # the tool we expect a tool_call for
    marker: str           # substring expected in the result if the tool was used
    note: str


TASKS = [
    Task(
        id="fetch_zen",
        task=(
            "Fetch the URL https://api.github.com/zen and report the EXACT "
            "single line it returns, verbatim. Do not paraphrase or answer "
            "from memory — you must retrieve it."
        ),
        tools=["fetch_url"],
        network=["api.github.com"],
        granted_tool="fetch_url",
        # api.github.com/zen returns a short zen sentence; we can't pin the
        # exact rotating line, so correctness here = "a tool_call happened AND
        # the run completed with non-trivial content" (checked in scoring).
        marker="",
        note="Tempts native knowledge; only fetch_url can get the live line.",
    ),
    Task(
        id="read_readme",
        task=(
            "Read the file README.md in the current directory and report the "
            "FIRST heading line exactly as written. Use the file tool — do "
            "not guess the project's name from prior knowledge."
        ),
        tools=["read_file"],
        network=[],
        granted_tool="read_file",
        marker="ppxai",   # README's first heading contains the project name
        note="Tempts native knowledge of a well-known repo; only read_file is truthful.",
    ),
]


@dataclass
class Result:
    provider: str
    model: str
    task_id: str
    status: str = ""
    used_granted_tool: bool = False
    tool_calls: list = field(default_factory=list)
    correctness: Optional[bool] = None
    error: Optional[str] = None
    latency_s: float = 0.0


# --------------------------------------------------------------------------
# HTTP helpers (stdlib)
# --------------------------------------------------------------------------
def _req(method: str, url: str, *, token: str = "", body: Optional[dict] = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        raise RuntimeError(f"HTTP {e.code} {url}: {detail}") from None


def _mint_token(base: str) -> str:
    """Loopback bootstrap mint (no bearer needed from localhost)."""
    try:
        out = _req("POST", f"{base}/v1/tokens", body={"owner": "bench"})
        return out["token"]
    except RuntimeError as e:
        # Auth may be disabled (env-only, unset) — then no token is needed.
        if "405" in str(e):
            return ""
        raise


# --------------------------------------------------------------------------
# One run
# --------------------------------------------------------------------------
def run_task(base: str, token: str, provider: str, model: str, t: Task,
             poll_timeout_s: float = 180.0) -> Result:
    res = Result(provider=provider, model=model, task_id=t.id)
    started = time.monotonic()
    body = {
        "task": t.task,
        "tools": t.tools,
        "provider": provider,
        "model": model,
    }
    if t.network:
        body["network"] = {"allow_outbound": t.network}
    try:
        run = _req("POST", f"{base}/v1/agent/task", token=token, body=body)
    except RuntimeError as e:
        res.error = f"submit failed: {e}"
        return res
    run_id = run["run_id"]

    # Poll meta to terminal.
    terminal = {"completed", "failed", "cancelled", "interrupted"}
    meta = {}
    while time.monotonic() - started < poll_timeout_s:
        meta = _req("GET", f"{base}/v1/agent/runs/{run_id}", token=token)
        if meta.get("status") in terminal:
            break
        time.sleep(1.0)
    res.status = meta.get("status", "timeout")
    res.error = meta.get("error")
    res.latency_s = round(time.monotonic() - started, 1)

    # Score from the event stream.
    evs = _req("GET", f"{base}/v1/agent/runs/{run_id}/events?category=tool",
               token=token).get("events", [])
    tool_calls = [
        (e.get("data") or {}).get("tool", "")
        for e in evs if e.get("type") == "tool_call"
    ]
    res.tool_calls = [tc for tc in tool_calls if tc]
    res.used_granted_tool = t.granted_tool in res.tool_calls

    # Correctness: marker present in the final result (coarse). For the
    # markerless fetch task, correctness = tool used AND non-trivial result.
    result_text = (meta.get("result") or "")
    if t.marker:
        res.correctness = t.marker.lower() in result_text.lower()
    else:
        res.correctness = res.used_granted_tool and len(result_text.strip()) > 10
    return res


# --------------------------------------------------------------------------
# Driver + reporting
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Agent-behavior cross-provider benchmark")
    ap.add_argument("--base-url", default="http://127.0.0.1:54320")
    ap.add_argument("--providers", default="all",
                    help="'all' or comma list (perplexity,nvidia,gemini,openai)")
    ap.add_argument("--repeat", type=int, default=1, help="runs per (provider,task)")
    ap.add_argument("--out", default="benchmarks/agent-behavior/results/latest.json")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    provs = (list(PROVIDER_MATRIX) if args.providers == "all"
             else [p.strip() for p in args.providers.split(",") if p.strip()])

    try:
        token = _mint_token(base)
    except Exception as e:
        print(f"FATAL: could not reach server / mint token at {base}: {e}")
        return 2

    results: list[Result] = []
    for prov in provs:
        model = PROVIDER_MATRIX.get(prov)
        if not model:
            print(f"skip {prov}: no model in matrix")
            continue
        for t in TASKS:
            for i in range(args.repeat):
                print(f"-> {prov}/{model} :: {t.id} (run {i+1}/{args.repeat}) ...",
                      flush=True)
                r = run_task(base, token, prov, model, t)
                tag = ("OK " if (r.used_granted_tool and r.correctness)
                       else "SUBST" if r.status == "completed" and not r.used_granted_tool
                       else "FAIL")
                print(f"   [{tag}] status={r.status} tool_used={r.used_granted_tool} "
                      f"correct={r.correctness} calls={r.tool_calls} {r.latency_s}s"
                      + (f" err={r.error}" if r.error else ""))
                results.append(r)

    # Summary table.
    print("\n" + "=" * 72)
    print(f"{'provider/model':38} {'task':12} {'adhere':7} {'correct':7} {'status'}")
    print("-" * 72)
    for r in results:
        print(f"{(r.provider+'/'+r.model)[:38]:38} {r.task_id:12} "
              f"{'yes' if r.used_granted_tool else 'NO':7} "
              f"{'yes' if r.correctness else 'no':7} {r.status}")

    # Per-provider adherence rate (the headline number).
    print("\nTool-adherence rate by provider:")
    for prov in provs:
        rs = [r for r in results if r.provider == prov]
        if not rs:
            continue
        adhere = sum(1 for r in rs if r.used_granted_tool)
        correct = sum(1 for r in rs if r.correctness)
        print(f"  {prov:12} adherence {adhere}/{len(rs)}  correctness {correct}/{len(rs)}")

    # Persist JSON.
    import os
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump([r.__dict__ for r in results], f, indent=2)
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
