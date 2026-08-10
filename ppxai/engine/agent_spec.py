"""Agent spec files (`/task` T3): configure a run from a file.

A *spec* is a declarative description of a `/task` run — task, system prompt,
tool grant, provider/model, budget, egress, read-scope — authored as one of:

- **`.md`**  YAML front-matter (`---` delimited) + a markdown body. The body
  becomes the `system` prompt (the persona / rendered AGENT.md) unless the
  front-matter sets `system:` explicitly.
- **`.json` / `.yaml` / `.yml`**  a single mapping of the same fields.
- **`.jsonl`**  batch: one JSON object per line, each a spec mapping (fan-out;
  loaded via `load_batch_lines`).

This module is pure normalization — it produces an :class:`AgentSpec` and does
NOT apply precedence, resolve names, or enforce the operator ceiling. The
server route (`server/routes/agent_v1.py`) owns resolution-by-name under
`execution.task.sandbox.specs_dir`, the request > spec > default precedence merge,
and the shell-reject / non-empty-grant clamp — so the security decisions live
at the trust boundary, not in the loader.

`read_paths` is parsed for forward-compatibility (the schema is complete) but
is NOT consumed until T4 wires per-run read-scope; T3 leaves it inert.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

# Bound the file we read: a spec is a small config document, not a payload.
MAX_SPEC_BYTES = 256 * 1024

# The fields a spec may carry. Unknown keys are ignored (forward-compatible).
_SPEC_FIELDS = frozenset(
    {"task", "system", "tools", "provider", "model", "budget", "network",
     "read_paths", "enrichment"}
)

_FRONT_MATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)$", re.DOTALL)


class AgentSpecError(ValueError):
    """A spec file couldn't be parsed into a valid :class:`AgentSpec`."""


@dataclass
class AgentSpec:
    """Normalized spec fields. Every field is optional — the merge at the route
    fills gaps from the request and server defaults; missing everywhere is the
    caller's problem to surface (e.g. an empty grant → 400)."""

    task: Optional[str] = None
    system: Optional[str] = None
    tools: Optional[list] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    budget: Optional[dict] = None        # {iterations?, time_s?, tokens?}
    network: Optional[list] = None       # allow_outbound entries
    read_paths: Optional[dict] = None    # {allow?, deny?} — parsed for T4; inert in T3
    # ADR 0009 §3/§5 (step ③): tri-state — True/False when the layer states
    # it, None = absent-means-inherit through the precedence chain. Effective
    # True derives web_search + its egress baseline AFTER resolution (§5),
    # never per layer.
    enrichment: Optional[bool] = None
    warnings: list = field(default_factory=list)


def _coerce_tools(value: Any) -> Optional[list]:
    if value is None:
        return None
    if isinstance(value, str):
        # Allow a comma/space list in a scalar for author convenience.
        return [t for t in re.split(r"[,\s]+", value.strip()) if t]
    if isinstance(value, (list, tuple)):
        return [str(t) for t in value]
    raise AgentSpecError(f"`tools` must be a list or string, got {type(value).__name__}")


def _coerce_network(value: Any) -> Optional[list]:
    """Accept either a bare list (allow_outbound) or {allow_outbound: [...]}."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("allow_outbound", [])
    if not isinstance(value, (list, tuple)):
        raise AgentSpecError("`network` must be a list or {allow_outbound: [...]}")
    return list(value)


def _coerce_budget(value: Any) -> Optional[dict]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AgentSpecError("`budget` must be a mapping of {iterations?, time_s?, tokens?}")
    out = {}
    for k in ("iterations", "time_s", "tokens"):
        if value.get(k) is not None:
            try:
                out[k] = int(value[k])
            except (TypeError, ValueError):
                raise AgentSpecError(f"budget.{k} must be an integer")
    return out or None


def spec_from_mapping(data: Any) -> AgentSpec:
    """Normalize a already-parsed mapping into an :class:`AgentSpec`."""
    if not isinstance(data, dict):
        raise AgentSpecError(
            f"spec must be a mapping of fields, got {type(data).__name__}"
        )
    spec = AgentSpec()
    unknown = [k for k in data if k not in _SPEC_FIELDS]
    if unknown:
        spec.warnings.append(f"ignored unknown spec keys: {sorted(unknown)}")

    if data.get("task") is not None:
        spec.task = str(data["task"])
    if data.get("system") is not None:
        spec.system = str(data["system"])
    spec.tools = _coerce_tools(data.get("tools"))
    if data.get("provider") is not None:
        spec.provider = str(data["provider"])
    if data.get("model") is not None:
        spec.model = str(data["model"])
    spec.budget = _coerce_budget(data.get("budget"))
    spec.network = _coerce_network(data.get("network"))
    if data.get("enrichment") is not None:
        # A scalar the author must mean: truthy strings like "no" silently
        # reading as True would invert a security intent, so only booleans.
        if not isinstance(data["enrichment"], bool):
            raise AgentSpecError(
                "`enrichment` must be a boolean (true/false), got "
                f"{data['enrichment']!r}"
            )
        spec.enrichment = data["enrichment"]
    rp = data.get("read_paths")
    if rp is not None:
        if not isinstance(rp, dict):
            raise AgentSpecError("`read_paths` must be a mapping of {allow?, deny?}")
        spec.read_paths = rp
    return spec


def _load_yaml_mapping(text: str) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AgentSpecError(f"invalid YAML/JSON: {exc}") from exc
    if data is None:
        return {}
    return data


def parse_spec(text: str, fmt: str) -> AgentSpec:
    """Parse spec text of a known format (`md` | `json` | `yaml`) → AgentSpec.

    Pure: no filesystem access. `md` splits `---` front-matter from the body;
    the body becomes `system` unless the front-matter set it.
    """
    if fmt == "md":
        m = _FRONT_MATTER_RE.match(text)
        if m:
            front, body = m.group(1), m.group(2)
            spec = spec_from_mapping(_load_yaml_mapping(front))
        else:
            # No front-matter: the whole document is the system prompt (prose),
            # matching --system-file semantics.
            spec, body = AgentSpec(), text
        body = body.strip()
        if body and not spec.system:
            spec.system = body
        return spec
    if fmt in ("json", "yaml"):
        return spec_from_mapping(_load_yaml_mapping(text))
    raise AgentSpecError(f"unknown spec format {fmt!r}")


_SUFFIX_FMT = {".md": "md", ".json": "json", ".yaml": "yaml", ".yml": "yaml"}


def load_spec_file(path: Path) -> AgentSpec:
    """Read + parse a spec file, dispatching on its suffix. Bounded by
    :data:`MAX_SPEC_BYTES`. Raises :class:`AgentSpecError` on any problem."""
    path = Path(path)
    fmt = _SUFFIX_FMT.get(path.suffix.lower())
    if fmt is None:
        raise AgentSpecError(
            f"unsupported spec extension {path.suffix!r} "
            f"(expected one of {sorted(_SUFFIX_FMT)})"
        )
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise AgentSpecError(f"cannot stat spec file: {exc}") from exc
    if size > MAX_SPEC_BYTES:
        raise AgentSpecError(
            f"spec file too large ({size} bytes > {MAX_SPEC_BYTES} limit)"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentSpecError(f"cannot read spec file: {exc}") from exc
    return parse_spec(text, fmt)


def load_batch_lines(text: str) -> list:
    """Parse `.jsonl` batch content → a list of spec mappings (one per line).

    Blank lines are skipped. Each non-blank line must be a JSON object; the
    line number is reported on a parse error so a bad batch is diagnosable.
    """
    out = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AgentSpecError(f"batch line {lineno}: invalid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise AgentSpecError(f"batch line {lineno}: expected a JSON object")
        out.append(obj)
    return out
