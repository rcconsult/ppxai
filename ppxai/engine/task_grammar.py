"""Client-agnostic grammar for the `/task` and `/run` families (U2, ADR 0011).

This is a port of the grammar in `ppxai/web/shared/task-controller.js`, moved
to the engine layer for T8b so the TUIs consume it instead of re-deriving it.
The web client remains the behavioural reference: `tests/test_task_grammar_parity.py`
pins the verb set, the run-id shape and the flag set against the JS source, so
the two cannot drift silently.

Why engine-level and not in `ppxai/tui/`: Textual is the first consumer, but
Rich is the second (T8b's remaining half) and the parser is pure text→data with
no client dependency. Same reasoning as `engine/completion.py`.

Scope: parsing only. Nothing here talks to a registry, a server, or a run —
callers map the result onto whichever transport they use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# A registry run id is exactly `run_` + token_hex(6) — see
# `ppxai/engine/agent_runs.py`. Kept as a literal (not imported) so the
# grammar stays dependency-free; the parity test pins it against the JS.
RUN_ID_RE = re.compile(r"^run_[0-9a-f]{12}$")

# A `run_…`-ish token that ISN'T a full id is a near-miss (truncated paste,
# typo). Fail loud on the lifecycle path instead of silently launching a
# garbage run whose prompt is the mangled command.
RUN_ID_ISH_RE = re.compile(r"^run_\S*$")

TASK_VERBS = frozenset({
    "help", "ls", "list", "get", "show", "open", "watch",
    "cancel", "respond", "collect", "ack", "resume",
})

# Verbs a `kind=oneshot` run cannot honour: a oneshot never parks, so it can
# neither be responded to nor resumed (ADR 0011 U3).
RUN_ONLY_EXCLUDED_VERBS = frozenset({"respond", "resume"})

_TOKEN_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')
_NUM_RE = re.compile(r"^(\d+(?:\.\d+)?)([km]?)$", re.IGNORECASE)


class Action(Enum):
    """What a command line resolves to."""

    HELP = "help"            # empty line
    LIFECYCLE = "lifecycle"  # verb (+ optional run id)
    LAUNCH = "launch"        # everything else — the whole line is the prompt
    NEAR_MISS = "near_miss"  # verb + `run_…`-ish token that isn't a valid id


@dataclass
class Dispatch:
    """Result of classifying a command line."""

    action: Action
    verb: str = ""
    run_id: str = ""
    rest: str = ""


@dataclass
class TaskArgs:
    """Parsed `/task` launch line, shaped like an AgentTaskRequest.

    Field names deliberately mirror the JS `out` object so the parity test can
    compare them directly.
    """

    task: str = ""
    tools: list[str] = field(default_factory=list)
    provider: Optional[str] = None
    model: Optional[str] = None
    system: Optional[str] = None
    network: dict[str, Any] = field(default_factory=lambda: {"allow_outbound": []})
    budget: dict[str, Any] = field(default_factory=dict)
    spec: Optional[str] = None
    skills: list[str] = field(default_factory=list)
    profile: Optional[str] = None
    enrichment: Optional[bool] = None
    workdir: Optional[str] = None
    errors: list[str] = field(default_factory=list)


def tokenize(s: str) -> list[str]:
    """Split a command line, treating "…" / '…' as single tokens."""
    out = []
    for m in _TOKEN_RE.finditer(s or ""):
        dq, sq, bare = m.groups()
        out.append(dq if dq is not None else (sq if sq is not None else bare))
    return out


def egress_entry(s: str):
    """`host` → bare host (any path); `host/path` → scoped {host, paths}."""
    slash = s.find("/")
    if slash == -1:
        return s
    return {"host": s[:slash], "paths": [s[slash:]]}


def parse_num(s: str) -> Optional[float]:
    """"100" | "100k" | "1.5m" → number, or None if malformed."""
    m = _NUM_RE.match((s or "").strip())
    if not m:
        return None
    n = float(m.group(1))
    suffix = m.group(2).lower()
    if suffix == "k":
        n *= 1e3
    elif suffix == "m":
        n *= 1e6
    return n


def _parse_budget(v: str, out: TaskArgs) -> None:
    for pair in v.split(","):
        eq = pair.find("=")
        if eq == -1:
            out.errors.append(f"bad --budget term: {pair}")
            continue
        key = pair[:eq].strip().lower()
        num = parse_num(pair[eq + 1:])
        if num is None:
            out.errors.append(f"bad --budget value: {pair}")
            continue
        if key in ("iters", "iterations"):
            out.budget["iterations"] = round(num)
        elif key in ("time", "time_s"):
            out.budget["time_s"] = num
        elif key == "tokens":
            out.budget["tokens"] = round(num)
        else:
            out.errors.append(f"unknown --budget key: {key}")


def parse_task_args(argline: str) -> TaskArgs:
    """Parse a `/task` launch line.

    The description is the leading run of tokens before the first `--flag`
    (quoted or bare). A non-empty `errors` means don't send.
    """
    toks = tokenize((argline or "").strip())
    out = TaskArgs()

    i = 0
    desc = []
    while i < len(toks) and not toks[i].startswith("--"):
        desc.append(toks[i])
        i += 1
    out.task = " ".join(desc).strip()

    def value(name: str) -> Optional[str]:
        nonlocal i
        if i + 1 >= len(toks) or toks[i + 1].startswith("--"):
            out.errors.append(f"{name} needs a value")
            return None
        i += 1
        return toks[i]

    while i < len(toks):
        t = toks[i]
        if t == "--tools":
            v = value("--tools")
            if v:
                out.tools = [x.strip() for x in v.split(",") if x.strip()]
        elif t == "--allow":
            v = value("--allow")
            if v:
                out.network["allow_outbound"] = [
                    egress_entry(x.strip()) for x in v.split(",") if x.strip()
                ]
        elif t == "--provider":
            v = value("--provider")
            if v:
                out.provider = v
        elif t == "--model":
            v = value("--model")
            if v:
                out.model = v
        elif t == "--system":
            v = value("--system")
            if v:
                out.system = v
        elif t == "--budget":
            v = value("--budget")
            if v:
                _parse_budget(v, out)
        elif t == "--spec":
            v = value("--spec")
            if v:
                out.spec = v
        elif t == "--profile":
            # ADR 0009 step ③: named execution profile (execution.profiles).
            v = value("--profile")
            if v:
                out.profile = v
        elif t == "--enrichment":
            # ADR 0009 §3: tri-state intent (on|off). Effective true derives
            # web_search + its egress baseline server-side.
            v = value("--enrichment")
            if v in ("on", "true"):
                out.enrichment = True
            elif v in ("off", "false"):
                out.enrichment = False
            elif v is not None:
                out.errors.append("--enrichment takes on|off")
        elif t == "--work-dir":
            # v1.19.x workdir-alignment: explicit per-run working dir.
            v = value("--work-dir")
            if v:
                out.workdir = v
        elif t == "--skill":
            # T4: repeatable and/or comma-separated — skills compose.
            v = value("--skill")
            if v:
                for s in (x.strip() for x in v.split(",")):
                    if s and s not in out.skills:
                        out.skills.append(s)
        else:
            out.errors.append(f"unknown flag: {t}")
        i += 1

    return out


def classify(argline: str) -> Dispatch:
    """Decide whether a line is a lifecycle op or a launch (U2 grammar).

    Lifecycle iff the first token is a verb AND the remainder is empty or
    starts with a run id. ANYTHING else launches with the whole line as the
    prompt, so `/task get run_ab12…` is a get while `/task get the weather in
    Geneva --tools web_search` launches.

    Run ids never contain whitespace, so id-taking verbs use only the first
    token — a multi-line paste degrades to acting on the first id rather than
    sending the whole blob as one bogus id (live-trial stumble, 2026-07-11).
    """
    trimmed = (argline or "").strip()
    if trimmed == "":
        return Dispatch(action=Action.HELP)

    parts = trimmed.split(None, 1)
    verb = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    first_tok = rest.split(None, 1)[0] if rest else ""

    is_verb = verb in TASK_VERBS
    lifecycle = is_verb and (rest == "" or bool(RUN_ID_RE.match(first_tok)))

    if not lifecycle:
        if is_verb and RUN_ID_ISH_RE.match(first_tok):
            return Dispatch(action=Action.NEAR_MISS, verb=verb, run_id=first_tok)
        return Dispatch(action=Action.LAUNCH, rest=trimmed)

    return Dispatch(action=Action.LIFECYCLE, verb=verb, run_id=first_tok, rest=rest)
