"""`/task` and `/run` — registry runs from the TUIs (T8b).

Until v1.19.1 these existed only in the web and VSCode clients, registered in
`web/shared/commands.js` and deliberately absent from `CommandFactory`,
because the TUIs had no channel to a ppxai-server. The embed decision
(plan §T8b) removed that constraint: `engine/task_backend.py` drives the same
registry and the same `build_task_runner` sandbox in-process.

**Gating is per VERB on a capability, not per client.** Launching and
resuming schedule an `asyncio.Task`, so they need a live event loop; listing,
inspecting, cancelling and collecting are synchronous registry operations and
do not. Textual has a loop for its whole lifetime and gets everything. The
Rich TUI's prompt is blocking with a throwaway `asyncio.run()` per operation,
so it gets the read/act verbs now and a precise message for the two that
cannot work yet — rather than the command being absent and reading as
"unknown command", or present and silently minting runs that never advance.

Gating on the loop rather than on client identity means Rich starts working
the moment its main loop question is settled, with no change here.

Grammar (U2, ADR 0011) is shared with the web client via
`engine/task_grammar.py`, so the verb rules cannot drift between clients.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..engine.task_authorizer import (
    TIERS,
    TaskAuthorizationError,
    TaskRequest,
    authorize,
)
from ..engine.task_backend import get_task_backend
from ..engine.task_grammar import (
    RUN_ONLY_EXCLUDED_VERBS,
    Action,
    classify,
    parse_task_args,
)
from .factory import CommandFactory, CommandSpec
from .results import (
    CommandResult,
    ErrorResult,
    NotificationResult,
    ResultStatus,
    TableResult,
)

_NEEDS_LOOP = ("launch", "resume")


def _has_running_loop() -> bool:
    """Is there a live event loop this run could be scheduled on?

    The actual requirement, asked directly. `registry.run_in_background()`
    schedules a task and returns; with no loop the run is minted and then
    never advances — a failure that looks like success.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _no_loop_error(family: str, verb: str) -> ErrorResult:
    return ErrorResult(
        status=ResultStatus.ERROR,
        message=(
            f"`{family} {verb}` needs a running event loop, and this client "
            f"does not have one."
        ),
        error_details=(
            "A run executes as a background asyncio task. Without a live loop "
            "it would be created and never progress, which looks like success "
            "and isn't. The Textual TUI (`ppxaide`) has a loop and supports "
            "this; the Rich TUI's blocking prompt does not yet — see "
            "docs/plan-task-command-sequencing.md §T8b."
        ),
        suggestions=[
            "Run it from `ppxaide` (the Textual TUI)",
            f"`{family} ls` and `{family} get <id>` work here — they only read "
            f"the registry",
        ],
    )


def _fmt_status(meta) -> str:
    icons = {
        "completed_pending_ack": "📬", "finalized": "✅", "completed": "✅",
        "failed": "❌", "cancelled": "🚫", "interrupted": "⏸️",
        "waiting": "✋", "running": "🤖", "pending": "…",
    }
    status = getattr(meta, "status", "?")
    return f"{icons.get(status, '•')} {status}"


# A run registry is append-only and nothing prunes it — a dev host reaches
# hundreds of runs quickly (348 oneshots in the 2026-08-09 trial). Rendering
# all of them into a side panel is unusable, so the view is capped and says
# so; `ls all` is the escape hatch.
_LIST_CAP = 20


def _rows(runs) -> list:
    return [
        [r.run_id, _fmt_status(r), (r.task or "")[:60],
         ",".join(r.tools or []) or "—"]
        for r in runs
    ]


def _run_table(family: str, kind: str, runs: list, message: str) -> TableResult:
    """The panel view, shared by `ls` and by launch.

    Launch returns this rather than a bare notification so a spawned run is
    VISIBLE without knowing any command — the web client opens a pane per run
    at launch and the TUI did not, which is why a spawned run appeared to go
    nowhere.
    """
    shown = runs[:_LIST_CAP]
    if len(runs) > _LIST_CAP:
        message = f"{message}  ·  showing {len(shown)} of {len(runs)} — `{family} ls all` for every run"
    return TableResult(
        status=ResultStatus.SUCCESS,
        message=message,
        columns=["Run", "Status", "Task", "Grant"],
        rows=_rows(shown),
        metadata={
            # Do not take focus: these runs are asynchronous by design and the
            # command's promise is that chat stays usable.
            "focus_panel": False,
            # Enter on a row opens that run.
            "row_command": f"{family} get {{0}}",
        },
    )


def _lifecycle(family: str, kind: str, verb: str, run_id: str,
               args: str) -> CommandResult:
    """Verbs shared by `/task` and `/run` (U2 dispatch)."""
    backend = get_task_backend()

    if verb == "help":
        return _help(family)

    if verb in ("ls", "list"):
        runs = backend.list_runs(kind=kind)
        if not runs:
            return NotificationResult(
                status=ResultStatus.SUCCESS,
                message=f"No {kind} runs yet.",
            )
        if "all" in args.split():
            return _run_table(family, kind, runs,
                              f"{len(runs)} {kind} run(s) — all")
        return _run_table(family, kind, runs, f"{len(runs)} {kind} run(s)")

    if not run_id:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"`{family} {verb}` needs a run id.",
            suggestions=[f"`{family} ls` lists them"],
        )

    meta = backend.get_run(run_id)
    if meta is None and verb != "resume":
        return ErrorResult(status=ResultStatus.ERROR,
                           message=f"Unknown run: {run_id}")

    if verb in ("get", "show", "open", "watch"):
        return NotificationResult(
            status=ResultStatus.SUCCESS,
            message=(
                f"{run_id} {_fmt_status(meta)}\n"
                f"task: {meta.task}\n"
                f"grant: {', '.join(meta.tools or []) or '—'}\n"
                f"result: {meta.result if meta.result is not None else '—'}"
                + (f"\nerror: {meta.error}" if meta.error else "")
            ),
        )

    if verb == "cancel":
        ok = backend.cancel(run_id)
        return NotificationResult(
            status=ResultStatus.SUCCESS if ok else ResultStatus.WARNING,
            message=(f"🚫 cancel requested for {run_id}" if ok else
                     f"{run_id} is not in flight — nothing to cancel"),
        )

    if verb in ("collect", "ack"):
        ok, reason = backend.collect(run_id)
        return NotificationResult(
            status=ResultStatus.SUCCESS if ok else ResultStatus.WARNING,
            message=(f"✅ collected {run_id}" if ok
                     else f"cannot collect {run_id}: {reason}"),
        )

    if verb == "respond":
        # `respond <id> approve|deny` — the token rides on meta.waiting, so the
        # user never types it. A wrong token is refused by the registry.
        # `args` is the whole line: "respond <id> approve" — so the decision is
        # the THIRD token, not the second (that one is the run id).
        parts = args.split()
        decision = parts[2].lower() if len(parts) > 2 else ""
        if decision not in ("approve", "deny", "yes", "no"):
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"`{family} respond <id> approve|deny`",
            )
        waiting = getattr(meta, "waiting", None) or {}
        token = waiting.get("token")
        if not token:
            return ErrorResult(status=ResultStatus.ERROR,
                               message=f"{run_id} is not waiting for a response")
        backend.respond(run_id, token=token,
                        approved=decision in ("approve", "yes"))
        return NotificationResult(
            status=ResultStatus.SUCCESS,
            message=f"answered {run_id}: {decision}",
        )

    if verb == "resume":
        if not _has_running_loop():
            return _no_loop_error(family, "resume")
        ok, reason = backend.resume(run_id)
        return NotificationResult(
            status=ResultStatus.SUCCESS if ok else ResultStatus.WARNING,
            message=(f"▶️ resumed {run_id}" if ok
                     else f"cannot resume {run_id}: {reason}"),
        )

    return ErrorResult(status=ResultStatus.ERROR,
                       message=f"Unsupported verb: {verb}")


def _help(family: str) -> NotificationResult:
    shared = ("ls · get <id> · watch <id> · cancel <id> · collect <id> · help")
    if family == "/run":
        body = (
            "/run — one-off background runs (async, non-blocking)\n"
            "  /run <prompt>          launch; NO flags — the grant is decided "
            "by server config (execution.run.web_search)\n"
            f"  /run {shared}\n"
            "  A first token counts as a verb only when followed by a run id "
            "(or nothing) — anything else launches.\n"
            "  Runs open in the side panel; F6 switches pane, Enter on a row "
            "opens that run. `/keys` lists every binding."
        )
    else:
        body = (
            "/task — sandboxed tool-capable runs (async, non-blocking)\n"
            '  /task "<desc>" --tools a,b [--allow host] [--budget iters=,time=,'
            "tokens=] [--provider p] [--model m] [--work-dir path]\n"
            f"  /task {shared} · respond <id> approve|deny · resume <id>\n"
            "  A first token counts as a verb only when followed by a run id "
            "(or nothing) — anything else launches.\n"
            "  Runs open in the side panel; F6 switches pane, Enter on a row "
            "opens that run. `/keys` lists every binding."
        )
    return NotificationResult(status=ResultStatus.SUCCESS, message=body)


def _dispatch(family: str, kind: str, context: Any, args: str) -> CommandResult:
    d = classify(args)

    if d.action is Action.HELP:
        return _help(family)

    if d.action is Action.NEAR_MISS:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=(f"`{d.run_id}` looks like a run id but isn't one "
                     f"(run_ + 12 hex)."),
            suggestions=[f"`{family} ls` shows the real ids"],
        )

    if d.action is Action.LIFECYCLE:
        if family == "/run" and d.verb in RUN_ONLY_EXCLUDED_VERBS:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=f"`{family}` has no `{d.verb}` — a one-off run never parks.",
                suggestions=["`/task` runs can park for consent"],
            )
        return _lifecycle(family, kind, d.verb, d.run_id, args)

    # LAUNCH. Validate the ARGUMENTS first and gate on the loop second: a
    # malformed command is malformed in every client, and reporting the
    # capability gate first would hide the real error behind an unrelated one
    # ("needs a running event loop" for what is actually a typo'd flag).
    if family == "/run":
        prompt = d.rest
        # `"--" in tokens` would only match a BARE "--" token, never "--tools".
        if any(tok.startswith("--") for tok in prompt.split()):
            return ErrorResult(
                status=ResultStatus.ERROR,
                message=("/run takes no flags — the grant is decided by server "
                         "config (execution.run.web_search)."),
                suggestions=["Use /task for an explicit tool grant"],
            )
        req = TaskRequest(task=prompt.strip('"\''), kind=kind)
    else:
        parsed = parse_task_args(d.rest)
        if parsed.errors:
            return ErrorResult(status=ResultStatus.ERROR,
                               message="/task: " + "; ".join(parsed.errors))
        if not parsed.task:
            return ErrorResult(
                status=ResultStatus.ERROR,
                message='/task needs a description: /task "<desc>" --tools a,b',
            )
        # EVERY parsed field is forwarded. Previously --spec, --profile and
        # --enrichment were parsed and then dropped (silent no-ops the help
        # text advertised), and --skill tokens were passed straight through as
        # filesystem read paths. They are now what they always claimed to be:
        # names and flags the shared authorizer resolves.
        req = TaskRequest(
            task=parsed.task,
            kind=kind,
            tools=parsed.tools,
            spec=parsed.spec,
            skills=parsed.skills,
            profile=parsed.profile,
            enrichment=parsed.enrichment,
            provider=parsed.provider,
            model=parsed.model,
            system=parsed.system,
            budget=parsed.budget or None,
            # `--allow` absent means "not stated" (inherit from a spec/profile),
            # which is not the same as an explicit empty allowlist.
            network=parsed.network.get("allow_outbound") or None,
            workdir=parsed.workdir,
        )

    if not _has_running_loop():
        return _no_loop_error(family, "launch")

    # ADMISSION. Both families pass the SAME boundary the HTTP routes use —
    # `req.kind` selects the tier row, so the TUI cannot be a weaker door than
    # the server for either tier.
    #
    # The UI's selected provider/model ride in as FALLBACKS. They only apply
    # where the tier says so (`honors_client_fallback`): for `/task` they sit
    # below an explicit --provider/--model flag and below a spec/profile,
    # because a UI selection is this client's default rather than a statement
    # about this request; for `/run` they are ignored outright, since a
    # sub-agent's provider is per-run injected intent (ADR 0003 §9), not
    # whatever the chat pane happens to be on.
    # The fallbacks are offered only to a tier that accepts them; the
    # authorizer REFUSES a run whose tier must not inherit UI context rather
    # than dropping it silently, so this cannot decay into the old behaviour
    # where `/run` quietly used the chat pane's provider.
    offers_ui_context = TIERS[kind].honors_client_fallback
    try:
        auth = authorize(
            req,
            fallback_provider=_ctx_provider(context) if offers_ui_context else None,
            fallback_model=_ctx_model(context) if offers_ui_context else None,
        )
    except TaskAuthorizationError as exc:
        return ErrorResult(status=ResultStatus.ERROR, message=exc.detail)

    backend = get_task_backend()
    meta = backend.launch(auth, kind=kind)
    # Warn-don't-fail notices the authorizer resolved. Silence here would make
    # a sealed host look like it honored --work-dir, and an operator ceiling
    # look like the run got the egress it asked for.
    notes = ""
    if auth.workdir_ignored:
        notes += "  ·  ⚠️ --work-dir ignored (filesystem seal is on)"
    if auth.stripped:
        dropped = ", ".join(sorted(str(s) for s in auth.stripped))
        notes += f"  ·  ⚠️ egress ceiling stripped: {dropped}"
    # Open the panel on launch, like the web client does, and name the next
    # step. The previous breadcrumb pointed only at `ls`, so a user who wanted
    # the result had no way to learn `collect` at the moment they needed it —
    # reported 2026-08-09: "no idea and could not find in help how to collect".
    return _run_table(
        family, kind, backend.list_runs(kind=kind),
        (f"🤖 {meta.run_id} running — chat stays usable  ·  "
         f"`{family} get {meta.run_id}` to view  ·  "
         f"`{family} collect {meta.run_id}` when done  ·  F6 switches pane"
         + notes),
    )


def _ctx_provider(context: Any) -> str | None:
    """Provider from the client's current selection, tolerating any context.

    The three CommandContext patterns expose this differently, and a run
    launched with the wrong provider fails late and confusingly — so read
    defensively rather than assuming one shape.
    """
    for attr in ("provider", "get_provider"):
        value = getattr(context, attr, None)
        try:
            resolved = value() if callable(value) else value
        except Exception:  # noqa: BLE001
            continue
        if resolved:
            return resolved
    return None


def _ctx_model(context: Any) -> str | None:
    for attr in ("current_model", "get_model"):
        value = getattr(context, attr, None)
        try:
            resolved = value() if callable(value) else value
        except Exception:  # noqa: BLE001
            continue
        if resolved:
            return resolved
    return None


def handle_task(context: Any, args: str) -> CommandResult:
    return _dispatch("/task", "task", context, args or "")


def handle_run(context: Any, args: str) -> CommandResult:
    return _dispatch("/run", "oneshot", context, args or "")


CommandFactory.register(CommandSpec(
    name="task",
    description=("Sandboxed tool-capable background runs — "
                 "ls · get · watch · collect · cancel · respond · resume "
                 "(`/task help` for the full grammar)"),
    handler=handle_task,
    category="agent",
    usage='/task "<desc>" --tools a,b | /task ls·get·watch·cancel·collect·'
          'respond·resume·help',
))

CommandFactory.register(CommandSpec(
    name="run",
    description=("One-off background runs, no flags — "
                 "ls · get · watch · collect · cancel "
                 "(`/run help` for the full grammar)"),
    handler=handle_run,
    category="agent",
    usage="/run <prompt> | /run ls·get·watch·cancel·collect·help",
))
