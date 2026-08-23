"""THE admission boundary for agent runs of every tier (ADR 0003 §9).

Every client that can start a run — the HTTP routes
(`server/routes/agent_v1.py`, `server/routes/oneshot.py`), the in-process TUI
backend (`engine/task_backend.py`), and any SDK embedder — passes a
`TaskRequest` through `authorize()` and gets back an `AuthorizedTask` or a
`TaskAuthorizationError`. **A caller that skips this module is the bug this
module exists to make impossible.**

One function serves both tiers. What differs between them is DATA in the
`TIERS` table, not a second code path: `/task` takes its grant from the
request, `/run` takes it from config and cannot be widened. The gates below
the grant — shell reject, operator kill-switch, provider validation, egress
assembly, ceiling — are shared unconditionally, because a per-tier copy of
them is precisely what drifts. See `TierPolicy` for why the table is
compiled rather than operator-described.

Why it exists
-------------
Until v1.19.1 these gates lived inside `create_agent_task`, so they were
*route* behavior rather than *tier* behavior. T8b then gave the TUIs an
in-process path to the same runner, and it reached `build_task_runner`
without any of them: a TUI could start a tool-capable run while
`execution.task.enabled` was false, and a grant containing
`execute_shell_command` evaded the server's explicit rejection. The suite
was green throughout — no test drove one request through both paths.

This is the second instance of that shape. `execution.egress_ceiling` had
the same story (route-only enforcement, in-process callers unguarded,
demonstrated live 2026-08-09) and was fixed by moving it into
`build_task_runner`. See that function's docstring for why the ceiling and
the shell reject belong at the construction site while the *tier* gate
deliberately does not.

What is NOT here
----------------
- Pydantic request-shape validation (422). It runs at parse time and has no
  in-process equivalent; the TUI's counterpart is `TaskArgs.errors`.
- `_caller_owner()` — HTTP principal extraction, passed in as `owner`.
- The response fields: `workdir_ignored` and `stripped` ride out on
  `AuthorizedTask`; each client renders them its own way.

Layering: imports only `config/*` and `engine/*`. It must never import
`fastapi`, `server/`, or `commands/` — fastapi is an optional dependency at
the commands layer, so a TUI import of this module has to stay cheap.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import execution as _execution_config
from ..config import get_default_model
from ..config.providers import get_api_key, get_available_providers
from ..config.tools import get_tool_config
from .agent_skill import AgentSkillError, LoadedSkill, load_skill
from .agent_spec import (
    AgentSpec,
    AgentSpecError,
    load_spec_file,
    spec_from_mapping,
)
from .tools.network_policy import apply_egress_ceiling, grant_has_shell


class TaskAuthorizationError(Exception):
    """A task request that must not start.

    Carries the HTTP-equivalent `status` because that IS the decision, not
    the transport: 403 means "operator policy forbids this capability here",
    400 means "this request is malformed or self-contradictory". The route
    maps it mechanically to `HTTPException`; a TUI renders `detail` and may
    use `status` to distinguish a policy refusal from a usage error.

    Precedent: `apply_egress_ceiling` already documents that callers at the
    trust boundary map its `ValueError` to a 4xx. Carrying the status makes
    that mapping lossless instead of collapsing everything to 400.
    """

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


def _task_cfg() -> Dict[str, Any]:
    """Single indirection for `execution.task.*` reads in this module.

    `get_execution_task_config` is imported per-module across the codebase
    (`agent_v1`, `task_runner`, here). Patching one module's binding does not
    affect the others — a trap that has cost real time, and one this module
    would make worse by adding a third binding that every existing test would
    have to learn about.

    So the read resolves through the ROUTE's binding when the route module is
    loaded, falling back to the config source. That keeps the established
    `monkeypatch.setattr(agent_v1, "get_execution_task_config", ...)` idiom
    authoritative for the gate that used to live there, while a pure-engine
    caller (a TUI, an SDK embedder — no server import) still reads real
    config. Tests with no route in play can patch `task_authorizer._task_cfg`.
    """
    routes = sys.modules.get("ppxai.server.routes.agent_v1")
    getter = getattr(routes, "get_execution_task_config", None) if routes else None
    return getter() if getter is not None else _execution_config.get_execution_task_config()


@dataclass
class TaskRequest:
    """Client-agnostic `/task` launch intent.

    Field-for-field the subset of the HTTP `AgentTaskRequest` that survives
    Pydantic parsing, and field-for-field reachable from
    `engine.task_grammar.TaskArgs` — so the two clients cannot describe
    different things.

    `network` is `Optional[list]` and the distinction is load-bearing:
    `None` means "not stated" (inherit from a less specific layer), `[]`
    means "stated: no egress" (narrow to nothing). Collapsing them lets a
    deliberately egress-free request inherit a spec's allowlist.

    `kind` names the registry run kind and therefore selects the `TierPolicy`
    row that governs admission. It is a field rather than an `authorize()`
    parameter on purpose: a caller must not be able to pair one tier's gates
    with another tier's grant (e.g. ask for task-tier gating while supplying
    a config grant). One DTO describes both use cases; the tier row supplies
    the semantics. Fields a tier does not use are inert for that tier —
    `tools`/`spec`/`skills`/`profile` are ignored under
    `grant_source="config"`, which is what makes "the request cannot widen
    the grant" true by construction rather than by a check.
    """

    task: str
    kind: str = "task"
    tools: List[str] = field(default_factory=list)
    spec: Optional[str] = None
    skills: List[str] = field(default_factory=list)
    profile: Optional[str] = None
    enrichment: Optional[bool] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    system: Optional[str] = None
    budget: Optional[Dict[str, Any]] = None
    network: Optional[List[Any]] = None
    workdir: Optional[str] = None


@dataclass
class AuthorizedTask:
    """An approved, fully-resolved launch. Every gate has passed.

    The only things left for a caller are minting a run and building a
    runner. `read_roots` holds RESOLVED skill directories only — never a
    client-supplied string. That asymmetry is the fix for the `--skill`
    path escape: read scope is an OUTPUT of authorization, never an input.
    """

    task: str
    tools: List[str]
    provider: str
    model: str
    system: Optional[str]
    budget: Dict[str, Any]
    network: List[Any]
    read_roots: List[str]
    workdir: Optional[str]
    workdir_ignored: bool
    enrichment: bool
    enrichment_layer: Optional[str]
    tools_layer: Optional[str]
    stripped: List[Any]


# --- tier policy -----------------------------------------------------------

@dataclass(frozen=True)
class TierPolicy:
    """WHAT a registry `kind` is allowed to be, expressed as DATA.

    Admission has ONE gate order (`authorize`); the gates that differ between
    tiers read their answer from this row instead of branching on the kind.
    That is deliberate: a second `authorize_oneshot()` would duplicate the
    egress assembly — the part with the actual security value — and the two
    copies would drift. Every field here is a difference that genuinely
    exists between the tiers; anything NOT in this table is shared code.

    **Compiled on purpose (design decision, v1.19.1).** The capability
    SWITCHES are JSON (`execution.task.enabled`, `execution.run.web_search`);
    the INVARIANTS are code. `grant_source` and `allows_empty_grant` together
    decide whether a request can widen its own privileges, so an operator
    typo in a JSON-described tier would be a privilege escalation that no
    test can catch — and the fail-safe-to-closed rule that
    `get_execution_task_config` documents cannot protect a table whose SHAPE
    is untrusted. If tiers ever become operator-describable, the JSON must be
    NARROWING-ONLY against this row (the intersective rule
    `execution.egress_ceiling` already uses), never widening.
    """

    kind: str
    # `execution.*` switch that must be true, or None for an always-available
    # tier. `/v1/oneshot` is byte-identical since v1.18.4 and its route
    # docstring promises the tool-free tier is always available — gating it
    # would break that surface on every box with the task tier off.
    gated_by: Optional[str]
    # "request": the grant is merged from request/spec/skills/profile.
    # "config":  the grant is decided by config alone and the request CANNOT
    #            widen it (ADR 0011 "no tools by design" for the one-off tier).
    grant_source: str
    # config key -> tools it grants, consulted only when grant_source=="config".
    config_grant: Dict[str, List[str]]
    allows_empty_grant: bool
    # May a CLIENT's ambient UI selection supply provider/model? False for the
    # one-off tier: provider is per-run INJECTED INTENT (ADR 0003 §9), chosen
    # for the sub-agent's task, not for whatever the UI happens to be on.
    honors_client_fallback: bool
    # Hardwired iteration budget for a config-granted tier, or None to take
    # the budget from the request/spec.
    iterations: Optional[int]
    # Does admission pre-validate the provider name/key?
    #
    # True for the task tier, which builds its provider LATER (inside the run)
    # and would otherwise mint a run that fails asynchronously. False for the
    # one-off tier, which builds the provider immediately after admission —
    # `_build_provider` already raises the same 400 for an unknown provider or
    # a missing key, so validating here would be a redundant second check
    # AND a stricter one: it consults real config, which callers that inject a
    # provider (spawn_subagent, tests) deliberately bypass.
    validates_provider: bool = True


TIERS: Dict[str, TierPolicy] = {
    "task": TierPolicy(
        kind="task",
        gated_by="execution.task.enabled",
        grant_source="request",
        config_grant={},
        allows_empty_grant=False,
        honors_client_fallback=True,
        iterations=None,
    ),
    "oneshot": TierPolicy(
        kind="oneshot",
        gated_by=None,
        grant_source="config",
        # The ONLY tool the one-off tier can ever grant (ADR 0011).
        config_grant={"execution.run.web_search": ["web_search"]},
        allows_empty_grant=True,
        honors_client_fallback=False,
        # Small §4 cap: enough for search -> answer, not an agent budget.
        iterations=2,
        # The route builds the provider immediately after admission.
        validates_provider=False,
    ),
}


def tier_for(kind: str) -> TierPolicy:
    """The policy row for a registry `kind`. Unknown kinds fail CLOSED."""
    try:
        return TIERS[kind]
    except KeyError:
        raise TaskAuthorizationError(400, f"Unknown run kind: {kind!r}.")


# --- tier gate -------------------------------------------------------------

def check_tier_enabled(kind: str = "task") -> None:
    """403 unless `kind`'s gating switch is on for this deployment.

    Exported because `InProcessTaskBackend.resume` needs the same gate
    (rebuilding a persisted run is a second admission path) and the HTTP
    resume route already has it. A tier with `gated_by=None` is a no-op.
    """
    policy = tier_for(kind)
    if policy.gated_by is None:
        return
    if not _task_cfg().get("enabled", False):
        raise TaskAuthorizationError(
            403,
            "The tool-capable agent tier (/v1/agent/task) is disabled. It is "
            "sandboxed in-process only and intended for trusted operators; "
            "enable it deliberately via execution.task.enabled=true in "
            "ppxai-config.json. The tool-free tier (/v1/agent/run) is always "
            "available.",
        )


# --- T3/T4: name-only resolution under an operator-configured root --------

def reject_unsafe_name(name: str, kind: str) -> None:
    """400 unless `name` is a bare name (no separator / parent-ref / absolute).

    Shared by the spec (T3) and skill (T4) resolvers so both enforce the SAME
    traversal defence at the trust boundary — a caller may name a file/dir
    under the configured root, never point at an arbitrary path.
    """
    if not name or "/" in name or "\\" in name or ".." in name or Path(name).is_absolute():
        raise TaskAuthorizationError(
            400,
            f"Invalid {kind} name {name!r}: a bare name is required (no path).",
        )


def within_root(root: Path, candidate: Path) -> bool:
    """True if `candidate` resolves to `root` or something under it.

    Symlink-escape defence: `candidate` is already `.resolve()`d by the caller;
    we confirm containment against the resolved root.
    """
    return root == candidate or root in candidate.parents


def resolve_named_spec(name: str) -> AgentSpec:
    """Load a spec by NAME from the configured specs_dir (T3).

    Security: name-only, no path. Reject any name with a path separator, a
    parent ref, or an absolute form; then confirm the resolved real path is
    still INSIDE specs_dir (defends against symlink escape) — the same
    name-only discipline the T4 skills resolver uses. 400 on any problem: a
    bad/unknown spec is a request error, not a server fault.
    """
    specs_dir = _task_cfg()["sandbox"].get("specs_dir")
    if not specs_dir:
        raise TaskAuthorizationError(
            400,
            "Spec files are not enabled: set "
            "execution.task.sandbox.specs_dir in ppxai-config.json.",
        )
    reject_unsafe_name(name, "spec")
    root = Path(specs_dir).expanduser().resolve()
    # Accept an explicit extension, else try the known ones in a stable order.
    candidates = (
        [root / name]
        if Path(name).suffix
        else [root / f"{name}{ext}" for ext in (".md", ".json", ".yaml", ".yml")]
    )
    for cand in candidates:
        try:
            real = cand.resolve()
        except OSError:
            continue
        # Containment check: the resolved file must live under specs_dir.
        if not within_root(root, real):
            continue
        if real.is_file():
            try:
                return load_spec_file(real)
            except AgentSpecError as exc:
                raise TaskAuthorizationError(400, f"Spec {name!r}: {exc}")
    raise TaskAuthorizationError(
        400, f"Spec {name!r} not found under specs_dir ({root})."
    )


def resolve_named_skill(name: str) -> LoadedSkill:
    """Load a skill by NAME from the configured skills_dir (T4).

    Same name-only discipline as the spec resolver: reject any name with a
    path separator / parent-ref / absolute form, resolve `<skills_dir>/<name>`,
    and confirm the real directory is still INSIDE skills_dir (symlink-escape
    defence) BEFORE reading its SKILL.md. 400 on any problem — an unknown or
    malformed skill is a request error, not a server fault.
    """
    skills_dir = _task_cfg()["sandbox"].get("skills_dir")
    if not skills_dir:
        raise TaskAuthorizationError(
            400,
            "Skills are not enabled: set "
            "execution.task.sandbox.skills_dir in ppxai-config.json.",
        )
    reject_unsafe_name(name, "skill")
    root = Path(skills_dir).expanduser().resolve()
    try:
        real = (root / name).resolve()
    except OSError as exc:
        raise TaskAuthorizationError(400, f"Skill {name!r}: {exc}")
    if not within_root(root, real) or not real.is_dir():
        raise TaskAuthorizationError(
            400, f"Skill {name!r} not found under skills_dir ({root})."
        )
    try:
        return load_skill(real, name)
    except AgentSkillError as exc:
        raise TaskAuthorizationError(400, str(exc))


def load_skills(names: List[str]) -> List[LoadedSkill]:
    """Resolve every `--skill <name>`, refusing a scripts-requiring skill unless
    `allow_skill_scripts` is on.

    A skill's scripts/ can never run in the in-process tier (no shell grant),
    so a skill that ships scripts/ is refused up front UNLESS the operator has
    explicitly set allow_skill_scripts — matching the plan's "reject/warn on a
    skill that requires scripts/ while allow_skill_scripts:false". The gate is
    an operator ceiling, not a per-request field.
    """
    if not names:
        return []
    allow_scripts = bool(_task_cfg()["sandbox"].get("allow_skill_scripts", False))
    loaded: List[LoadedSkill] = []
    for name in names:
        skill = resolve_named_skill(name)
        if skill.has_scripts and not allow_scripts:
            raise TaskAuthorizationError(
                400,
                f"Skill {name!r} ships a scripts/ directory, which cannot run "
                "in the in-process tier (no shell grant; scripts need the "
                "container tier). Set "
                "execution.task.sandbox.allow_skill_scripts to acknowledge "
                "they stay inert, or use a skill without scripts/.",
            )
        loaded.append(skill)
    return loaded


def resolve_named_profile(name: str) -> AgentSpec:
    """Resolve `execution.profiles.<name>` → AgentSpec (ADR 0009 §1, step ③).

    A profile IS a spec mapping in a config location — same fields, same
    `spec_from_mapping` normalizer as a `--spec` file, zero new schema shape.
    Unknown name / malformed mapping → 400 PRE-START (§5 two-stage
    validation: config-resolvable checks never become async run failures).
    """
    # Function-local import, as in the original: it resolves the CURRENT
    # source attribute on every call, so a test (or a config reload) that
    # replaces `config.execution.get_execution_profiles` is honored. A
    # module-level binding would freeze whatever existed at import time.
    from ..config.execution import get_execution_profiles

    profiles = get_execution_profiles()
    if name not in profiles:
        available = ", ".join(sorted(profiles)) or "(none configured)"
        raise TaskAuthorizationError(
            400,
            f"Unknown execution profile {name!r}. Configured profiles "
            f"under execution.profiles: {available}.",
        )
    try:
        return spec_from_mapping(profiles[name])
    except AgentSpecError as exc:
        raise TaskAuthorizationError(
            400, f"Invalid execution profile {name!r}: {exc}"
        )


def _resolve_task_default_grant() -> AgentSpec:
    """Resolve `execution.task.default_grant` → AgentSpec (Item 58).

    The user's standing default `/task` grant. Returns an empty AgentSpec when
    the operator has disabled it (`allow_user_default:false` → fail-closed, a
    bare task keeps 422-ing) or when nothing is configured, so the merge just
    falls through to the built-in empty default. A malformed mapping is a
    pre-start 400 — the same `spec_from_mapping` normalizer profiles use, so a
    bad default grant can never become an async run failure or a silent bypass.
    """
    from ..config.execution import (
        get_execution_task_allow_user_default,
        get_execution_task_default_grant,
    )

    if not get_execution_task_allow_user_default():
        return AgentSpec()
    raw = get_execution_task_default_grant()
    if not raw:
        return AgentSpec()
    try:
        return spec_from_mapping(raw)
    except AgentSpecError as exc:
        raise TaskAuthorizationError(
            400, f"Invalid execution.task.default_grant: {exc}"
        )


# §5 layer ranks for the contradiction rule: LOWER = more specific. Skills sit
# between spec and profile — an explicitly named per-run mount is more
# specific than a standing config profile, less than the authored spec file.
# default_grant is the LEAST specific real layer (rank 4) — below profile,
# above only the built-in empty default — so a request/spec/skill/profile that
# omits web_search always wins the enrichment contradiction check against it.
_LAYER_RANK = {"request": 0, "spec": 1, "skill": 2, "profile": 3, "default_grant": 4}


def merge_task_fields(
    req: TaskRequest,
    *,
    fallback_provider: Optional[str] = None,
    fallback_model: Optional[str] = None,
) -> dict:
    """Effective run fields, precedence: request > spec > skills > profile >
    client fallback > default_subagent (ADR 0009 Q1; step ③ inserts the
    named-profile layer).

    Returns {task, tools, provider, model, system, budget(dict), network(list),
    read_roots(list), enrichment(bool), enrichment_layer, tools_layer}.

    **List fields (tools, network) REPLACE, never union** (Q1): the most
    specific layer that STATES the field supplies all of it, so a narrower
    layer can actually remove a tool or a host — a security surface must be
    able to narrow. The one deliberate exception stays: SKILLS union their
    tool grants into the effective grant (that is their purpose — mount
    capability) and each skill dir joins `read_roots` (T4).

    **Enrichment (§5)** resolves here as an ordinary scalar, then the caller
    derives web_search + its egress baseline ONCE from the resolved value —
    never per layer. The contradiction rule is enforced here, pre-start: an
    explicit tools list omitting web_search, stated at or more specific than
    the layer declaring enrichment:true, is a 400 naming both layers.

    `fallback_provider`/`fallback_model` are the CLIENT's ambient default (the
    TUI's currently-selected provider/model). They sit BELOW the spec layer
    and ABOVE `execution.default_subagent`, because a UI selection is a
    client default, not a statement about this request — so an explicit
    `--provider` flag, or a spec, still wins. The HTTP route passes neither,
    so its precedence is unchanged.

    The caller runs the SAME ceiling guards (shell-reject, non-empty grant,
    provider/model present) on these merged values — so no spec, skill, or
    profile can smuggle a grant past the checks a direct request faces.
    """
    from ..config.execution import get_execution_default_subagent

    spec = resolve_named_spec(req.spec) if req.spec else AgentSpec()
    skills = load_skills(req.skills)
    profile = resolve_named_profile(req.profile) if req.profile else AgentSpec()
    # Item 58: the user's own default grant — a NEW precedence layer BELOW
    # profile, ABOVE the built-in empty default. It seeds a bare `/task` from
    # `execution.task.default_grant` (AgentSpec-shaped {tools?, network?,
    # budget?}) so a user can set up their own working environment without a
    # per-run flag. Gated by `allow_user_default` (operator fail-closed switch)
    # and — like every other source — CLAMPED downstream by the unchanged
    # ceiling guards (shell-reject, egress_ceiling, kill-switches), so it is a
    # convenience layer, never a capability escalation.
    default_grant = _resolve_task_default_grant()
    sub_defaults = get_execution_default_subagent()

    # A skill scalar is the first skill (in --skill order) that sets it — so
    # composition is deterministic and skill order is meaningful for scalars.
    def _skill_scalar(attr: str):
        for s in skills:
            val = getattr(s.spec, attr, None)
            if val is not None:
                return val
        return None

    task = req.task or spec.task

    # Base grant = the most specific layer that STATES tools (replace, Q1).
    # An empty request list means "not stated"; a spec/profile distinguishes
    # stated-empty (narrows to nothing → the post-merge 400) from absent.
    if req.tools:
        tools, tools_layer = list(req.tools), "request"
    elif spec.tools is not None:
        tools, tools_layer = list(spec.tools), "spec"
    elif profile.tools is not None:
        tools, tools_layer = list(profile.tools), "profile"
    elif default_grant.tools is not None:
        # Item 58: the user's standing default seeds a bare `/task`.
        tools, tools_layer = list(default_grant.tools), "default_grant"
    else:
        tools, tools_layer = [], None
    # Skills UNION on top — a skill ADDS capability; it never removes what
    # the request/spec/profile asked for.
    for s in skills:
        for t in (s.spec.tools or []):
            if t not in tools:
                tools.append(t)

    provider = (req.provider or spec.provider or _skill_scalar("provider")
                or profile.provider or fallback_provider
                or sub_defaults.get("provider"))
    model = req.model or spec.model or _skill_scalar("model") or profile.model
    if not model:
        # The client's ambient model only pairs with the client's ambient
        # provider — same cross-pairing guard the subagent default uses, so a
        # spec-chosen provider never inherits an unrelated UI model.
        if fallback_model and provider == fallback_provider:
            model = fallback_model
        # Same cross-pairing guard as /run: the subagent default model only
        # pairs with the subagent default provider; otherwise the chosen
        # provider's own default_model.
        if not model and provider == sub_defaults.get("provider"):
            model = sub_defaults.get("model")
        if not model and provider:
            model = get_default_model(provider) or None
    system = (req.system if req.system is not None
              else spec.system if spec.system is not None
              else _skill_scalar("system") if _skill_scalar("system") is not None
              else profile.system)
    budget = (dict(req.budget or {}) or dict(spec.budget or {})
              or dict(_skill_scalar("budget") or {}) or dict(profile.budget or {})
              or dict(default_grant.budget or {}))

    # Network REPLACES per layer too (Q1) — `is not None` per layer, so a
    # stated-empty list is an expressible "no egress", not a fall-through.
    # Item 58 slots default_grant below profile: a user's default egress
    # applies only when no more specific layer stated one — and it is still
    # clamped by execution.egress_ceiling downstream.
    if req.network is not None:
        network = list(req.network)
    elif spec.network is not None:
        network = list(spec.network)
    elif _skill_scalar("network") is not None:
        network = list(_skill_scalar("network"))
    elif profile.network is not None:
        network = list(profile.network)
    elif default_grant.network is not None:
        network = list(default_grant.network)
    else:
        network = []

    # §5 step 1: enrichment resolves as an ordinary scalar, tracking WHICH
    # layer stated it (for the contradiction rule).
    if req.enrichment is not None:
        enrichment, enrichment_layer = req.enrichment, "request"
    elif spec.enrichment is not None:
        enrichment, enrichment_layer = spec.enrichment, "spec"
    elif _skill_scalar("enrichment") is not None:
        enrichment, enrichment_layer = _skill_scalar("enrichment"), "skill"
    elif profile.enrichment is not None:
        enrichment, enrichment_layer = profile.enrichment, "profile"
    else:
        enrichment, enrichment_layer = False, None

    # §5 contradiction rule (pre-start 400): a tools list stated at or more
    # specific than the enrichment declaration, omitting web_search, disagrees
    # with it about the same run — fail naming both layers, don't guess.
    if (enrichment and "web_search" not in tools and tools_layer is not None
            and _LAYER_RANK[tools_layer] <= _LAYER_RANK[enrichment_layer]):
        raise TaskAuthorizationError(
            400,
            f"Contradictory grant: the {enrichment_layer} layer declares "
            f"enrichment:true, but the {tools_layer} layer states an "
            "explicit tools list that omits web_search. Either add "
            "web_search to that tools list or set enrichment:false at "
            "the more specific layer (ADR 0009 §5).",
        )
    # §5 step 2: derive ONCE from the resolved value — effective enrichment
    # adds web_search (the egress baseline is merged below, where the
    # allowlist is assembled). Only reachable when the tools statement is
    # LESS specific than the enrichment declaration, or absent.
    if enrichment and "web_search" not in tools:
        tools.append("web_search")

    # T4: each skill dir is mounted into the run read-scope. De-dup while
    # preserving --skill order so the run can read references/ (and only these
    # new roots), not siblings outside the skills.
    read_roots: List[str] = []
    for s in skills:
        if s.read_root not in read_roots:
            read_roots.append(s.read_root)
    return {
        "read_roots": read_roots,
        "task": task, "tools": tools, "provider": provider, "model": model,
        "system": system, "budget": budget, "network": network,
        "enrichment": bool(enrichment), "enrichment_layer": enrichment_layer,
        "tools_layer": tools_layer,
    }


# --- grant + egress guards -------------------------------------------------

def web_search_banned(tools: list) -> bool:
    """True when the grant includes web_search but the operator disabled it.

    `tools.web_search.enabled=false` is a config kill-switch for the task tier
    — e.g. a locked-down coder pod that must never let a sandboxed run search
    the web. Absent/true → allowed (backward compatible)."""
    if "web_search" not in tools:
        return False
    try:
        return get_tool_config("web_search").get("enabled", True) is False
    except Exception:
        return False


def with_tool_egress_defaults(network: list, tools: list) -> list:
    """Merge per-tool operator egress baselines into a run's allowlist.

    ADR 0009 §2 (step ②, generalizes the old web_search-only
    `task_default_allow`): **`tools.<tool>.egress`** — a list of host
    strings per tool — is trusted operator input, the same trust level as a
    per-run `--allow`. The union across the run's GRANTED tools is merged
    in, so an operator declares once what each tool needs and a run granting
    that tool just works — one config-driven mechanism across local `/task`,
    coder pods, and the oneshot facade.

    Dual-read: for `web_search`, the legacy
    `tools.web_search.task_default_allow` spelling is honored when no
    `egress` key is present; an explicit `egress` wins. Dedups against
    existing entries; string hosts only.
    """
    merged = list(network)
    existing = {e for e in merged if isinstance(e, str)}
    for tool in tools or []:
        try:
            cfg = get_tool_config(tool) or {}
        except Exception:
            continue
        if "egress" in cfg:
            hosts = cfg.get("egress") or []
        elif tool == "web_search":
            hosts = cfg.get("task_default_allow", []) or []  # legacy dual-read
        else:
            hosts = []
        for host in hosts:
            if isinstance(host, str) and host and host not in existing:
                merged.append(host)
                existing.add(host)
    return merged


def apply_ceiling_or_error(network: list) -> tuple:
    """`apply_egress_ceiling` at the trust boundary: (kept, stripped), with a
    malformed `execution.egress_ceiling` surfacing as a pre-start 400 — a
    security cap fails loud, never open, and never as an async run failure."""
    try:
        return apply_egress_ceiling(network)
    except ValueError as exc:
        raise TaskAuthorizationError(400, str(exc))


def web_search_egress_hosts(provider_name: Optional[str] = None) -> list:
    """The bare HOSTNAMES of web_search's EFFECTIVE egress set, for the run's
    allowlist. Resolver entries are URLs (the shape `tool_targets` compares
    against), but `NetworkPolicy` allowlist rules take bare hosts — passing
    the URLs verbatim silently matches nothing (fail-closed deny; caught
    live in the F3 trial via the run's own network_policy_denied event).

    Step ④ (ADR 0009 Q5): reads the shared backend resolver, so under an
    effective `strict` pin the enrichment baseline narrows to the pinned
    backend's host(s) — the §3-sanctioned narrowing — and in auto/ordering
    mode it is the full superset (session parity = the fallback chain)."""
    from urllib.parse import urlparse

    from .tools.search_backends import resolve_web_search_backend

    hosts = resolve_web_search_backend(provider_name).egress_hosts
    return sorted({urlparse(u).netloc for u in hosts if urlparse(u).netloc})


def enrichment_survives_ceiling(
    kept: list, provider_name: Optional[str] = None
) -> bool:
    """Q3 check: does the EFFECTIVE web_search egress set survive the cap
    in full?

    Step ④ refinement (replaces step ③'s any-surviving-host approximation):
    `NetworkPolicy.authorize` enforces ALL-OF over the tool's target set, so
    a partially-surviving baseline passes grant time but the tool is
    un-callable at run time — exactly the half-enriched failure Q3 exists
    to prevent. The effective set comes from the shared resolver: the full
    superset in auto/ordering mode, the pinned backend's host(s) under
    `strict` — so an operator who wants a narrow ceiling pins with
    `strict: true` and the two configs compose instead of colliding."""
    baseline = set(web_search_egress_hosts(provider_name))
    return baseline <= {e for e in kept if isinstance(e, str)}


def validate_provider_or_error(provider_name: str) -> None:
    """Cheap fail-fast: raise 400 if `provider_name` is unknown or has no API
    key, WITHOUT constructing the provider.

    Same two checks `_build_provider` does up front, factored out so a caller
    that only needs to validate (e.g. the `/v1/agent/task` tier, which builds
    its own provider later inside the run) doesn't instantiate and immediately
    throw away an SDK client. Keep this in sync with `_build_provider`'s guards.
    """
    # Same binding-indirection rationale as `_task_cfg`: this check moved down
    # from the route, where callers (and a long tail of tests) stub it as
    # `agent_v1._validate_provider_or_400`. Honor that stub when the route is
    # loaded so the move doesn't silently re-enable real provider lookups in
    # suites that deliberately bypass them.
    routes = sys.modules.get("ppxai.server.routes.agent_v1")
    stub = getattr(routes, "_validate_provider_or_400", None) if routes else None
    if stub is not None:
        try:
            stub(provider_name)
            return
        except Exception as exc:  # the route's own HTTPException
            status = getattr(exc, "status_code", None)
            detail = getattr(exc, "detail", None)
            if status is None or detail is None:
                raise
            raise TaskAuthorizationError(int(status), str(detail))

    if provider_name not in get_available_providers():
        raise TaskAuthorizationError(
            400,
            f"Unknown provider: {provider_name!r}. "
            f"Configure it in ppxai-config.json.",
        )
    if not get_api_key(provider_name):
        raise TaskAuthorizationError(
            400,
            f"No API key for provider {provider_name!r}. "
            f"Set it in ~/.ppxai/.env.",
        )


def enriched_oneshot_egress_or_error(provider_name: Optional[str] = None) -> list:
    """The one-off tier's enrichment allowlist: effective backend egress set
    (resolver: superset, or the strict-pinned backend) + operator
    `tools.web_search.egress` baseline, capped by `execution.egress_ceiling`
    — with the Q3 fail-fast when the cap breaks the set (pre-start 4xx, no
    half-enriched run).

    The ONE copy of this assembly. `authorize` reaches it through the shared
    tail below; the `/v1/oneshot` facade calls it directly (that route builds
    its allowlist before it has a request to authorize).
    """
    hosts = with_tool_egress_defaults(
        web_search_egress_hosts(provider_name), ["web_search"]
    )
    kept, stripped = apply_ceiling_or_error(hosts)
    if not enrichment_survives_ceiling(kept, provider_name):
        raise TaskAuthorizationError(
            400,
            "execution.run.web_search is on, but execution.egress_ceiling "
            "strips part of web_search's effective egress set "
            f"(stripped: {', '.join(sorted(str(s) for s in stripped))}). "
            "The egress check is all-of over the whole set, so a partial "
            "allowlist makes the tool un-callable — never a half-enriched "
            "run (ADR 0009 Q3). Widen the ceiling, pin one backend with "
            "tools.web_search.{preferred,strict:true}, or turn "
            "execution.run.web_search off.",
        )
    return kept


def _config_grant_fields(req: TaskRequest, policy: TierPolicy) -> dict:
    """Effective fields for a tier whose grant is CONFIG-decided.

    Same dict shape `merge_task_fields` returns, so gates 3-8 cannot tell the
    two tiers apart — that shared tail is the whole point of the table.

    The precedence here is deliberately SHORTER than the request-granted
    tier's: request value → `execution.default_subagent` → the provider's own
    default_model. No spec/skill/profile layer (nothing to merge) and no
    client fallback (`honors_client_fallback=False`): a sub-agent's provider
    is per-run injected intent (ADR 0003 §9), chosen for its task rather than
    inherited from whatever the interactive UI happens to be on.
    """
    tools: List[str] = []
    granted_by: Optional[str] = None
    for key, granted in policy.config_grant.items():
        if _config_flag(key):
            tools = list(granted)
            granted_by = key
            break

    sub_defaults = _default_subagent()
    provider = req.provider or sub_defaults.get("provider")
    model = req.model
    if not model:
        # default_subagent.model belongs to default_subagent.provider —
        # cross-pairing it with a DIFFERENT explicit provider must not happen
        # (e.g. perplexity handed a Qwen model id). For any other provider,
        # fall back to its own default_model, mirroring /v1/oneshot.
        if provider == sub_defaults.get("provider"):
            model = sub_defaults.get("model")
        if not model and provider:
            model = _default_model(provider) or None

    return {
        "task": req.task,
        "tools": tools,
        "provider": provider,
        "model": model,
        "system": req.system,
        "budget": (
            {"iterations": policy.iterations}
            if tools and policy.iterations is not None
            else dict(req.budget or {})
        ),
        # A config-granted tier states its egress; it never inherits one.
        "network": list(req.network or []),
        "read_roots": [],
        "enrichment": bool(tools),
        "enrichment_layer": granted_by,
        "tools_layer": granted_by,
    }


def _via_route(name: str, fallback):
    """Resolve `name` through the ROUTE's binding when the route is loaded.

    The per-module-binding trap, generalized. `get_execution_task_config`,
    `get_default_model` and `get_execution_default_subagent` are each imported
    by several modules; patching one module's binding does not affect the
    others. These resolutions all moved DOWN from `agent_v1`, where the
    established idiom is `monkeypatch.setattr(agent_v1, "<name>", ...)`, so
    the engine has to honor that binding or silently reach real config
    instead. A pure-engine caller (TUI, SDK — no server import) gets
    `fallback`.

    Used for every config getter this module reads. Adding a read without it
    is the bug: it passes until someone patches the route and wonders why.
    """
    routes = sys.modules.get("ppxai.server.routes.agent_v1")
    return getattr(routes, name, None) or fallback if routes else fallback


def _default_model(provider_name: str) -> Optional[str]:
    """`get_default_model`, route-binding aware. See `_via_route`."""
    return _via_route("get_default_model", get_default_model)(provider_name)


def _default_subagent() -> Dict[str, Any]:
    """`get_execution_default_subagent`, route-binding aware. See `_via_route`."""
    return _via_route(
        "get_execution_default_subagent",
        _execution_config.get_execution_default_subagent,
    )()


def _config_flag(dotted_key: str) -> bool:
    """Read a boolean `execution.*` switch named by the tier row.

    Indirection so the TABLE names the key as data. Unknown or unreadable →
    False: a capability must never survive the failure of the config that
    governs it (the fail-safe-to-closed rule the getters already document).
    """
    from ..config.execution import get_execution_run_config

    readers = {"execution.run.web_search": lambda: get_execution_run_config()}
    reader = readers.get(dotted_key)
    if reader is None:
        return False
    try:
        return bool(reader().get(dotted_key.rsplit(".", 1)[1], False))
    except Exception:
        return False


# --- the boundary ----------------------------------------------------------

def _reject_tool_incapable_model(
    provider: Optional[str], model: Optional[str], tools: List[str]
) -> None:
    """Refuse a tool-carrying run on a model that cannot call tools.

    Debt Item 43: Perplexity's `sonar` answers a tools request with HTTP 400
    ("Tool calling is not supported for this model"), and
    `sonar-deep-research` rejects the parameter shape. Neither degrades. The
    engine's fallback for a non-tool-capable model is PROMPT-BASED calling,
    and that fallback is exactly what produced Item 43's refusals,
    confabulated tool results ("a child agent has been spawned, it read
    ...") and answers grounded in an unrelated web page.

    So a tool-capable run targeting such a model is refused BEFORE a run is
    minted, with the capable models named. Failing loud beats a plausible
    wrong answer — the same reason the shell reject and the tier gate live
    at admission rather than at send time.

    Silent on anything it cannot resolve: an unknown provider, no model, or
    a provider whose capability lookup raises. This gate exists to convert a
    KNOWN-bad combination into a clear error, never to block a combination
    it merely failed to look up.
    """
    if not tools or not provider or not model:
        return
    try:
        from ..config.capabilities import config_model_overrides
        from .providers import get_provider_class

        provider_cls = get_provider_class(provider)
        if provider_cls is None:
            return
        caps = provider_cls.default_capabilities
        shipped = getattr(provider_cls, "shipped_capabilities_for_model", None)
        capable: Optional[bool] = None
        if shipped is not None:
            # Read the class-level table without constructing a provider (no
            # API key here). Fall back to the declared default when the
            # implementation needs an instance.
            try:
                capable = shipped(
                    _CapabilityProbe(caps), model  # type: ignore[arg-type]
                ).native_tool_calling
            except Exception:  # noqa: BLE001
                capable = None
        if capable is None:
            capable = bool(getattr(caps, "native_tool_calling", False))
        # Operator config wins, same precedence as everywhere else.
        override = config_model_overrides(provider, model).get(
            "native_tool_calling"
        )
        if override is not None:
            capable = bool(override)
    except Exception:  # noqa: BLE001 — never block on a lookup failure
        return

    if capable:
        return

    hint = _tool_capable_models_hint(provider)
    raise TaskAuthorizationError(
        400,
        f"Model {model!r} on provider {provider!r} does not support tool "
        f"calling, so a run granted {sorted(tools)!r} cannot execute them. "
        "Running it anyway would fall back to prompt-based tool calling, "
        "which this model ignores — producing a refusal or a confabulated "
        f"result rather than a real tool call (debt Item 43).{hint}",
    )


class _CapabilityProbe:
    """Minimal stand-in so a provider's capability table can be read without
    constructing the provider (which would need an API key)."""

    def __init__(self, capabilities):
        self.capabilities = capabilities


def _tool_capable_models_hint(provider: str) -> str:
    """" Use <models> instead." when the provider names tool-capable models."""
    try:
        from .providers import get_provider_class

        cls = get_provider_class(provider)
        names = getattr(cls, "NATIVE_TOOL_MODELS", None)
        if not names:
            import importlib

            mod = importlib.import_module(cls.__module__)
            names = getattr(
                mod, f"{provider.upper()}_NATIVE_TOOL_MODELS", None
            )
        if names:
            return f" Tool-capable models here: {', '.join(sorted(names))}."
    except Exception:  # noqa: BLE001
        pass
    return ""


def authorize(
    req: TaskRequest,
    *,
    fallback_provider: Optional[str] = None,
    fallback_model: Optional[str] = None,
) -> AuthorizedTask:
    """Full preflight for a run of ANY tier. Raises `TaskAuthorizationError`.

    ONE gate order serves every tier; the gates that differ read their answer
    from `req.kind`'s `TierPolicy` row rather than branching. Gates 4-8 — the
    egress assembly, where the security value is — are unconditionally shared,
    which is the point: a per-tier copy of them is what drifts.

    1. tier enabled — FIRST, so a disabled tier never touches the filesystem
       (spec/skill resolution below reads operator-configured directories).
       Row: `gated_by`.
    2. the grant. Row: `grant_source` — merged from request/spec/skills/
       profile, or decided by config with the request unable to widen it.
    3. non-empty grant. Row: `allows_empty_grant`.
    4. shell reject — arbitrary shell escapes the egress allowlist entirely.
    5. web_search operator kill-switch. Applies to EVERY tier: it is a
       predicate over the resolved grant, so a config-granted tier is subject
       to the same operator veto as a request-granted one.
    6. provider/model present, then provider validated. Row:
       `honors_client_fallback` decides whether a UI selection may supply them.
    7. workdir: the seal wins over a caller's request (warn-don't-fail).
    8. egress assembly: enrichment hosts → per-tool baselines → ceiling →
       enrichment-survives-ceiling. The ceiling is LAST, immediately before
       the result is handed back, so operator-trusted additions can only
       widen within the cap and never bypass an earlier gate.
    """
    policy = tier_for(req.kind)
    check_tier_enabled(req.kind)

    # A client that offers its ambient UI selection to a tier that must not
    # take one is a BUG IN THE CALLER, not a request to silently ignore.
    # Dropping it quietly would make `honors_client_fallback` decorative —
    # the same "reads like enforcement, enforces nothing" shape this module
    # exists to remove. Caught by mutation: gating the value at the merge
    # call below changes no behaviour, because the config-granted branch
    # never reads it.
    if not policy.honors_client_fallback and (fallback_provider or fallback_model):
        raise TaskAuthorizationError(
            400,
            f"A {req.kind!r} run cannot inherit the client's selected "
            "provider/model: a sub-agent's provider is per-run injected "
            "intent (ADR 0003 §9), resolved from the request or "
            "execution.default_subagent. Pass provider/model on the request "
            "instead of forwarding the UI context.",
        )

    if policy.grant_source == "config":
        # The request CANNOT widen a config-decided grant: req.tools/spec/
        # skills/profile are never consulted, so "no tools by design" holds by
        # construction rather than by a check that could be forgotten.
        eff = _config_grant_fields(req, policy)
    else:
        eff = merge_task_fields(
            req,
            fallback_provider=(
                fallback_provider if policy.honors_client_fallback else None
            ),
            fallback_model=(
                fallback_model if policy.honors_client_fallback else None
            ),
        )
    tools = eff["tools"]

    # Post-merge non-empty grant (400, not 422): the HTTP model_validator lets
    # a spec-carrying request through with no request-level tools; if neither
    # the request nor the spec yields a grant, reject here. A tool-free tier
    # legitimately resolves to [] and skips this.
    if not tools and not policy.allows_empty_grant:
        raise TaskAuthorizationError(
            400,
            "Empty tool grant: neither the request nor the resolved "
            "spec/skills/profile provided any tools. A tool-capable run "
            "needs a non-empty grant.",
        )

    # A shell-execution tool runs arbitrary commands whose network egress the
    # allowlist cannot inspect (curl/pip/Invoke-WebRequest/…), so it would
    # bypass the egress chokepoint entirely. The filesystem seal cannot see it
    # either: the jail confines named path-taking tools by inspecting their
    # path kwarg, and a shell command string carries no such kwarg. The only
    # tier that can contain shell is OS isolation (ADR 0003 §3 tier-d).
    if grant_has_shell(tools):
        raise TaskAuthorizationError(
            400,
            "execute_shell_command is not permitted in a tool-capable "
            "agent run: arbitrary shell escapes the egress allowlist "
            "(AC-2). It requires the OS-isolation tier (ADR 0003 §3 "
            "tier-d), which is deferred past the MVP. Grant any other "
            "tool instead — every non-shell builtin (read_file, grep, "
            "web_search, fetch_url, write_file, apply_patch, …) is "
            "permitted; only the shell tool is held back.",
        )

    # Operator kill-switch (AC-2 policy surface): web_search can be banned for
    # the task tier via tools.web_search.enabled=false — e.g. a locked-down
    # coder pod. Checked on the MERGED grant so a spec/skill can't smuggle it in.
    if web_search_banned(tools):
        # Wording differs by tier because the remedy does: a task-tier caller
        # can drop the tool from its own grant, while a one-off caller cannot
        # (the grant is config-decided) and must change config instead.
        if policy.grant_source == "config":
            raise TaskAuthorizationError(
                403,
                "web_search is disabled by operator config "
                "(tools.web_search.enabled=false), but execution.run"
                ".web_search is on — the one-off tier's grant would contain "
                "a tool the operator has switched off. Turn execution.run"
                ".web_search off, or enable the tool in ppxai-config.json.",
            )
        raise TaskAuthorizationError(
            403,
            "web_search is disabled for the tool-capable tier by operator "
            "config (tools.web_search.enabled=false). Remove it from the "
            "grant, or enable it in ppxai-config.json.",
        )

    provider_name = eff["provider"]
    model = eff["model"]
    if not provider_name or not model:
        # Tier-specific wording: the one-off tier has no spec layer to point
        # at, and its historical messages name the missing field precisely —
        # existing clients (and tests) assert on those substrings.
        if policy.grant_source == "config":
            if not provider_name:
                raise TaskAuthorizationError(
                    400,
                    "No provider for the agent run. Pass `provider` in the "
                    "request, or set execution.default_subagent.provider in "
                    "ppxai-config.json.",
                )
            raise TaskAuthorizationError(
                400,
                f"No model for provider {provider_name!r}. Pass `model` in "
                f"the request, or set execution.default_subagent.model in "
                f"config.",
            )
        raise TaskAuthorizationError(
            400,
            "Agent task needs provider+model (request, spec, or "
            "execution.default_subagent config).",
        )
    if policy.validates_provider:
        validate_provider_or_error(provider_name)
        _reject_tool_incapable_model(provider_name, model, tools)

    # The per-run jail always wins over a caller-supplied workdir: under the
    # seal the run's writable root IS its jail workdir. Warn-don't-fail — the
    # flag rides out on the result so each client can surface it.
    workdir: Optional[str] = None
    workdir_ignored = False
    if req.workdir:
        sealed = _task_cfg()["sandbox"].get("enforcement") == "in_process"
        if sealed:
            workdir_ignored = True
        else:
            wd = os.path.abspath(os.path.expanduser(req.workdir))
            if not os.path.isdir(wd):
                raise TaskAuthorizationError(
                    400,
                    f"workdir does not exist or is not a directory: "
                    f"{req.workdir}",
                )
            workdir = wd

    if eff["enrichment"]:
        existing = {e for e in eff["network"] if isinstance(e, str)}
        for host in web_search_egress_hosts(provider_name):
            if host not in existing:
                eff["network"].append(host)
                existing.add(host)

    # Operator per-tool baselines merge AFTER the grant gates above, so a
    # trusted egress addition can only widen the allowlist — never be used to
    # slip a tool past the shell/kill-switch checks.
    eff["network"] = with_tool_egress_defaults(eff["network"], tools)

    # §5 step 3 (Q3): the deployment egress ceiling caps the assembled
    # allowlist — intersective, config-only, unset = no cap. For an ENRICHED
    # run, stripping any backend host is a pre-start 400: the run must not
    # start half-enriched (a silently closed-book "enriched" run is the exact
    # failure this ADR exists to fix).
    kept, stripped = apply_ceiling_or_error(eff["network"])
    if eff["enrichment"] and not enrichment_survives_ceiling(kept, provider_name):
        raise TaskAuthorizationError(
            400,
            "This run resolves enrichment:true "
            f"(declared at the {eff['enrichment_layer']} layer), but "
            "execution.egress_ceiling strips part of web_search's "
            "effective egress set (stripped: "
            f"{', '.join(sorted(str(s) for s in stripped))}). The egress "
            "check is all-of over the whole set, so a partial allowlist "
            "makes the tool un-callable — never a half-enriched run "
            "(ADR 0009 Q3). Widen the ceiling, pin one backend with "
            "tools.web_search.{preferred,strict:true}, or set "
            "enrichment:false.",
        )

    return AuthorizedTask(
        task=eff["task"],
        tools=tools,
        provider=provider_name,
        model=model,
        system=eff["system"],
        budget=eff["budget"],
        network=kept,
        read_roots=eff["read_roots"],
        workdir=workdir,
        workdir_ignored=workdir_ignored,
        enrichment=eff["enrichment"],
        enrichment_layer=eff["enrichment_layer"],
        tools_layer=eff["tools_layer"],
        stripped=list(stripped),
    )



def authorize_task(
    req: TaskRequest,
    *,
    fallback_provider: Optional[str] = None,
    fallback_model: Optional[str] = None,
) -> AuthorizedTask:
    """`authorize` pinned to the tool-capable tier.

    Not a wrapper for its own sake: it makes the task tier's admission
    un-mistakable at the call site and refuses a request carrying another
    tier's `kind`, so a caller cannot reach `/task`'s gates with a
    `kind="oneshot"` DTO.
    """
    if req.kind != "task":
        raise TaskAuthorizationError(
            400, f"authorize_task called with kind={req.kind!r}."
        )
    return authorize(
        req, fallback_provider=fallback_provider, fallback_model=fallback_model
    )


def authorize_oneshot(
    task: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    system: Optional[str] = None,
    network: Optional[List[Any]] = None,
) -> AuthorizedTask:
    """`authorize` pinned to the tool-free one-off tier (`kind="oneshot"`).

    Takes scalars rather than a DTO because the tier ignores every grant
    field: there is no `tools`/`spec`/`skills`/`profile` parameter to pass,
    which is how "the request cannot widen the grant" reads at the call site.
    """
    return authorize(
        TaskRequest(
            task=task, kind="oneshot", provider=provider, model=model,
            system=system, network=network,
        )
    )
