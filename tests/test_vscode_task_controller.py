"""Static structural tests for the VSCode /task port (v1.19.x build plan T8a).

Why structural-only: the repo has no TS runtime test harness (see
test_vscode_visibility_reanchor.py for the precedent); `npm run compile`
typechecks the sources, and these fences pin the cross-client contract —
the parts that would drift silently:

  - VERB PARITY: the VSCode controller must route exactly the web
    controller's verb set (run/ls/list/show/watch/cancel/respond/ack/
    resume/help). A verb added to one client and not the other is the
    T8 "parity sentinel" failure the plan calls out.
  - ENDPOINT PARITY: both clients must drive the same /v1/agent/* paths.
  - WIRING: chatPanel routes `/task` to the controller BEFORE factory
    dispatch (the factory would 404 it); httpClient exposes the typed
    agent* methods; the consent QuickPick answers with the park token.
  - STATUS PARITY: the terminal/success status sets match the web sets
    (a status added server-side must reach both watchers).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS_CONTROLLER = ROOT / "vscode-extension" / "src" / "taskController.ts"
TS_CHAT_PANEL = ROOT / "vscode-extension" / "src" / "chatPanel.ts"
TS_HTTP_CLIENT = ROOT / "vscode-extension" / "src" / "httpClient.ts"
WEB_TASK = ROOT / "ppxai" / "web" / "shared" / "task-controller.js"
WEB_BASE = ROOT / "ppxai" / "web" / "shared" / "agent-run-controller.js"
WEB_RUN = ROOT / "ppxai" / "web" / "shared" / "run-controller.js"
WEB_DISPATCHER = ROOT / "ppxai" / "web" / "shared" / "command-dispatcher.js"
WEB_COMMANDS = ROOT / "ppxai" / "web" / "shared" / "commands.js"
ENGINE_COMPLETION = ROOT / "ppxai" / "engine" / "completion.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _case_verbs(src: str) -> set[str]:
    """Verbs routed by a `switch (verb)` handle() — `case 'x':` labels."""
    # Scope to the handle() routing switch: both files put it in a method
    # whose cases are single-word verbs; filter out non-verb switches
    # (event-type switches use snake_case/longer names).
    # U2 (ADR 0011): no `run` case label — launch is the grammar fallthrough;
    # get/collect are canonical, show/open/ack stay as alias labels.
    verbs = set(re.findall(r"case '([a-z]+)':", src))
    return {v for v in verbs if v in {
        "ls", "list", "get", "show", "open", "watch",
        "cancel", "respond", "collect", "ack", "resume", "help",
    }}


class TestVerbParity:
    def test_vscode_routes_the_full_web_verb_set(self):
        web = _case_verbs(_read(WEB_TASK))
        ts = _case_verbs(_read(TS_CONTROLLER))
        assert web, "web verb set unexpectedly empty (regex drift?)"
        missing = web - ts
        extra = ts - web
        assert not missing, f"VSCode /task is missing web verbs: {sorted(missing)}"
        assert not extra, f"VSCode /task grew verbs the web lacks: {sorted(extra)}"


class TestEndpointParity:
    # Every /v1/agent/* path the web pair drives must appear in the
    # VSCode httpClient (template-literal form).
    _ENDPOINTS = [
        "/v1/agent/task",
        "/v1/agent/runs",
        "/events?live=1",
        "/cancel",
        "/respond",
        "/ack",
        "/resume",
    ]

    def test_http_client_covers_all_agent_endpoints(self):
        src = _read(TS_HTTP_CLIENT)
        for ep in self._ENDPOINTS:
            assert ep in src, f"httpClient.ts lacks the {ep} endpoint"

    def test_web_drives_the_same_endpoints(self):
        # The other half of the sentinel: if the web client adds an agent
        # endpoint, this fails until the VSCode list above grows too.
        web = _read(WEB_TASK) + _read(WEB_BASE)
        for ep in self._ENDPOINTS:
            assert ep in web, f"web controllers lack the {ep} endpoint"

    def test_backend_interface_matches_http_client_methods(self):
        # The controller's TaskBackend slice and the concrete httpClient
        # must agree on method names, or chatPanel's wiring breaks at
        # runtime (structural typing hides a *missing* method until call).
        controller = _read(TS_CONTROLLER)
        client = _read(TS_HTTP_CLIENT)
        methods = re.findall(r"^\s{4}(agent\w+)\(", controller, re.M)
        assert set(methods) >= {
            "agentTask", "agentRunCreate", "agentRuns", "agentRun",
            "agentRunEvents", "agentRunCancel", "agentRunRespond",
            "agentRunAck", "agentRunResume",
        }
        for m in methods:
            # `async *name(` — the events tail is an async generator.
            assert re.search(rf"async \*?{m}\(", client), (
                f"httpClient.ts lacks async {m}() required by TaskBackend"
            )

    def test_run_launch_endpoint_in_both_clients(self):
        # U3: POST /v1/agent/run (the one-off launch). Substring-ambiguous
        # with /v1/agent/runs, so match the string terminator on each side.
        assert "/v1/agent/run'" in _read(WEB_RUN)
        assert "/v1/agent/run`" in _read(TS_HTTP_CLIENT)


class TestRunFamilyParity:
    """U3 (ADR 0011): the /run one-off family — cross-client sentinels."""

    def test_run_controller_extends_task_controller_in_both_clients(self):
        assert "extends _TaskControllerBase" in _read(WEB_RUN)
        assert "class RunController extends TaskController" in _read(TS_CONTROLLER)

    def test_kind_filter_drives_ls_in_both_clients(self):
        # /run ls shows only oneshots, /task ls only tasks — both clients
        # must pass the kind through to GET /v1/agent/runs.
        assert "kind=${this._kind}" in _read(WEB_BASE)
        assert "this.backend.agentRuns(this.kind)" in _read(TS_CONTROLLER)
        assert "_kind = 'oneshot'" in _read(WEB_RUN)
        assert "_kind = 'task'" in _read(WEB_TASK)
        assert "kind: string | undefined = 'oneshot'" in _read(TS_CONTROLLER)
        assert "kind: string | undefined = 'task'" in _read(TS_CONTROLLER)

    def test_no_flags_guard_in_both_clients(self):
        # /run takes no flags — the grant is config-decided; a --flag must
        # be rejected, not silently folded into the prompt.
        for src in (_read(WEB_RUN), _read(TS_CONTROLLER)):
            assert "takes no flags" in src

    def test_run_routed_before_factory_dispatch_in_vscode(self):
        assert "getRunController().handle(argsText)" in _read(TS_CHAT_PANEL)

    def test_agentrun_family_retired(self):
        # Hard removal (no aliases): the dispatcher no longer routes the
        # old commands, the catalogs no longer list them, and completion
        # no longer offers them.
        assert "cmd === '/agentrun'" not in _read(WEB_DISPATCHER)
        assert "cmd === '/agentruns'" not in _read(WEB_DISPATCHER)
        assert "'/agentrun':" not in _read(WEB_COMMANDS)
        assert "'/agentruns':" not in _read(WEB_COMMANDS)
        assert '"/agentrun"' not in _read(ENGINE_COMPLETION)
        assert "'/run':" in _read(WEB_COMMANDS)


class TestStatusParity:
    def _web_set(self, name: str) -> set[str]:
        src = _read(WEB_BASE)
        m = re.search(rf"{name} = new Set\(\[(.*?)\]\)", src, re.S)
        assert m, f"web {name} set not found"
        return set(re.findall(r"'([a-z_]+)'", m.group(1)))

    def _ts_set(self, name: str) -> set[str]:
        src = _read(TS_CONTROLLER)
        m = re.search(rf"{name} = new Set\(\[(.*?)\]\)", src, re.S)
        assert m, f"TS {name} set not found"
        return set(re.findall(r"'([a-z_]+)'", m.group(1)))

    def test_terminal_statuses_match(self):
        assert self._ts_set("TERMINAL_STATUSES") == self._web_set("_TERMINAL")

    def test_success_statuses_match(self):
        assert self._ts_set("SUCCESS_STATUSES") == self._web_set("_SUCCESS")

    def test_terminal_events_match(self):
        # The SSE tail loops of both clients must break on the same
        # stream-terminal run-event set (the live stream stays open after
        # the run ends — a mismatch parks one client's tail forever).
        assert self._ts_set("TERMINAL_EVENTS") == self._web_set("_TERMINAL_EVENTS")

    def test_terminal_event_break_confirms_run_status_in_both_clients(self):
        # T7 live-trial bug (2026-07-12): the SSE replays the persisted
        # backlog first, so a RESUMED run's tail sees the historical
        # agent_run_interrupted from before the resume. Breaking on that
        # stale replay silently detaches the fresh tail (no live events, no
        # consent card — the park can only time out). Both clients must
        # confirm against the run record (source of truth) before breaking:
        # a terminal-event match followed by a status GET + terminal-set
        # check, never a bare `break`.
        web = _read(WEB_BASE)
        assert re.search(
            r"_TERMINAL_EVENTS\.has\(ev\.type\)\)\s*\{[^}]*apiClient\.get\("
            r"`/v1/agent/runs/\$\{runId\}`\)",
            web, re.S,
        ), "web tail must confirm run status before breaking on a terminal event"
        assert "._TERMINAL.has(now.status)) break" in web.replace("AgentRunController", "."), \
            "web tail must gate the break on the CURRENT run status"
        ts = _read(TS_CONTROLLER)
        assert re.search(
            r"TERMINAL_EVENTS\.has\(ev\.type\)\)\s*\{[^}]*agentRun\(runId\)",
            ts, re.S,
        ), "TS tail must confirm run status before breaking on a terminal event"
        assert re.search(
            r"TERMINAL_STATUSES\.has\(now\.status\)\)\s*\{\s*break;\s*\}",
            ts,
        ), "TS tail must gate the break on the CURRENT run status"


class TestChatPanelWiring:
    def test_task_routed_before_factory_dispatch(self):
        src = _read(TS_CHAT_PANEL)
        task_pos = src.find("command === 'task'")
        factory_pos = src.find("await this.dispatchFactoryCommand(command, argsText)")
        assert task_pos != -1, "chatPanel does not route /task"
        assert factory_pos != -1, "factory dispatch anchor moved (test drift)"
        assert task_pos < factory_pos, (
            "/task must be intercepted BEFORE factory dispatch — the "
            "CommandFactory has no /task handler and would 404 it"
        )
        assert "getTaskController().handle(argsText)" in src

    def test_controller_constructed_with_backend_ui_defaults(self):
        # U3 refactor: both controllers share buildTaskUi()/buildTaskDefaults()
        # — the wiring (webview transcript + session defaults) lives there.
        src = _read(TS_CHAT_PANEL)
        for ctor in ("new TaskController(", "new RunController("):
            m = re.search(
                re.escape(ctor) + r"\s*\n\s+this\._backend, "
                r"this\.buildTaskUi\(\), this\.buildTaskDefaults\(\)", src)
            assert m, f"{ctor} not wired via the shared builders"
        assert "systemMessage" in src and "fullResponse" in src
        assert "currentProvider" in src and "currentModel" in src

    def test_consent_quickpick_answers_with_approved_flag(self):
        # The T5 park answer path: QuickPick → {approved: bool}; a dismissed
        # dialog returns undefined (the TTL is the fail-closed backstop).
        src = _read(TS_CHAT_PANEL)
        assert "askConsent" in src
        assert "approved: selected.value === 'approve'" in src
        assert re.search(r"if \(!selected\) \{ return undefined; \}", src)


class TestConsentTokenDiscipline:
    def test_watcher_sends_the_park_token(self):
        # The respond payload must carry the resume token from the run meta
        # (waiting.token) — the server 409s otherwise (T5 token check).
        src = _read(TS_CONTROLLER)
        assert "token: run.waiting.token" in src
        assert "consentSeen" in src  # one QuickPick per park, not per poll

    def test_respond_verb_reads_token_from_meta(self):
        src = _read(TS_CONTROLLER)
        assert "token: meta.waiting.token" in src


class TestBearerParity:
    """Item 40: both clients must attach the /v1 bearer the same way.

    The bearer is scoped to /v1/* ONLY — server/auth.py validates any
    presented bearer even on loopback-exempt UI routes, so a stale token
    attached everywhere would 401 the whole client. These fences pin:
    (a) each client has the setter + scoped-header seam, (b) every
    /v1/agent call site actually uses it, (c) the token sources are the
    safe ones (web localStorage via /token; VSCode SecretStorage — never
    settings.json).
    """

    TS_EXTENSION = ROOT / "vscode-extension" / "src" / "extension.ts"
    TS_PACKAGE = ROOT / "vscode-extension" / "package.json"
    WEB_API = ROOT / "ppxai" / "web" / "shared" / "api-client.js"
    WEB_DISPATCH = ROOT / "ppxai" / "web" / "shared" / "command-dispatcher.js"

    def test_web_api_client_has_scoped_bearer_seam(self):
        src = _read(self.WEB_API)
        assert "setApiToken" in src
        assert "headersFor" in src
        assert "startsWith('/v1/')" in src, "bearer must be scoped to /v1/*"

    def test_web_event_tail_uses_the_seam(self):
        src = _read(WEB_BASE)
        assert "api.headersFor" in src, (
            "_tailEvents must use headersFor — a raw getHeaders() 401s the "
            "live tail on auth-enforcing hosts"
        )

    def test_web_token_command_never_takes_inline_secret_silently(self):
        src = _read(self.WEB_DISPATCH)
        assert "_handleTokenCommand" in src
        assert "window.prompt" in src, "token entry must go through prompt()"
        assert "ppxai-api-token" in src  # the localStorage key

    def test_vscode_client_has_scoped_bearer_seam(self):
        src = _read(TS_HTTP_CLIENT)
        assert "setApiToken" in src
        assert "v1Headers" in src

    def test_every_vscode_agent_call_site_uses_v1_headers(self):
        src = _read(TS_HTTP_CLIENT)
        start = src.index("// === Agent run registry")
        # The registry slice ends where the /v1/tokens section begins —
        # the mint there is the one documented BARE call (loopback
        # bootstrap; a stale bearer would be validated and rejected).
        end = src.index("// === /v1/tokens (Item 40)")
        agent_slice = src[start:end]
        assert "this.getHeaders(" not in agent_slice, (
            "an agent-slice call site regressed to plain getHeaders() — "
            "it would 401 on auth-enforcing hosts"
        )
        # All 9 endpoints: task, run-create (U3), runs, run, events, cancel,
        # respond, ack, resume.
        assert agent_slice.count("this.v1Headers(") == 9

    def test_vscode_token_comes_from_secret_storage(self):
        src = _read(self.TS_EXTENSION)
        assert "context.secrets.get('ppxai.apiToken')" in src
        assert "registerCommand('ppxai.setApiToken'" in src
        assert "password: true" in src, "input box must mask the token"
        pkg = _read(self.TS_PACKAGE)
        assert '"ppxai.setApiToken"' in pkg, "command missing from package.json"
        # Never a settings-based token: settings sync + dotfiles leak secrets.
        assert '"ppxai.apiToken"' not in pkg


class TestTokenCommandParity:
    """Item 40 follow-up (2026-07-12): `/token` is an in-chat command in
    BOTH clients — the VSCode trial showed a palette-only VSCode flow is
    undiscoverable (autocomplete offered /token, dispatch answered
    "Unknown command", and the /task 401 never named the fix).
    """

    WEB_DISPATCH = ROOT / "ppxai" / "web" / "shared" / "command-dispatcher.js"

    def test_token_routed_before_factory_dispatch_in_vscode(self):
        src = _read(TS_CHAT_PANEL)
        token_pos = src.find("command === 'token'")
        factory_pos = src.find("await this.dispatchFactoryCommand(command, argsText)")
        assert token_pos != -1, "chatPanel does not route /token"
        assert token_pos < factory_pos, (
            "/token must be intercepted BEFORE factory dispatch — the "
            "CommandFactory has no /token handler and would 404 it"
        )

    def test_both_clients_implement_the_same_verb_set(self):
        for src in (_read(self.WEB_DISPATCH), _read(TS_CHAT_PANEL)):
            for verb in ("status", "set", "mint", "clear"):
                assert f"case '{verb}':" in src, f"/token {verb} missing"

    def test_vscode_mint_is_deliberately_bare(self):
        # The loopback bootstrap mint must NOT attach a (possibly stale)
        # bearer — server/auth.py validates any presented bearer even on
        # exempt routes. Web nulls its token first; VSCode's mint method
        # builds bare headers.
        src = _read(TS_HTTP_CLIENT)
        start = src.index("// === /v1/tokens (Item 40)")
        end = src.index("// === Agent Mode (v1.11.8) ===")
        token_slice = src[start:end]
        assert "'/v1/tokens'" in token_slice.replace('`', "'") or \
            "/v1/tokens" in token_slice
        assert "this.getHeaders(true)" in token_slice
        assert "this.v1Headers(" not in token_slice
        web = _read(self.WEB_DISPATCH)
        assert "api.setApiToken(null)" in web, (
            "web mint must null the stored token before POSTing"
        )

    def test_vscode_token_command_shares_the_palette_secret_key(self):
        # /token and the "ppxai: Set API Token" palette entry must read and
        # write the SAME SecretStorage key, or the two flows desync.
        src = _read(TS_CHAT_PANEL)
        assert "secrets.store('ppxai.apiToken'" in src
        assert "secrets.delete('ppxai.apiToken'" in src
        # Bare `/token set` defers to the palette's masked input box —
        # the webview transcript must never see the raw value.
        assert "executeCommand('ppxai.setApiToken')" in src

    def test_workdir_flag_and_threading_parity(self):
        # v1.19.x workdir-alignment: both clients must parse --work-dir AND
        # thread the session working dir as the fallback per-run intent —
        # one client threading and the other not would silently re-diverge
        # the "summarize README.md" semantics the feature exists to align.
        web, ts = _read(WEB_TASK), _read(TS_CONTROLLER)
        for src, name in ((web, "web"), (ts, "vscode")):
            assert "'--work-dir'" in src, f"{name} parser lacks --work-dir"
            assert "body.workdir = workdir" in src, (
                f"{name} launch does not thread workdir"
            )
        assert "this.app.state.workingDir" in web
        assert "defaults.workingDir" in ts
        # Sealed-host warning: same message, gated on the response flag.
        for src, name in ((web, "web"), (ts, "vscode")):
            assert "workdir_ignored" in src, f"{name} ignores the seal flag"
            assert "sandbox seal active" in src, f"{name} lacks the seal warning"

    def test_401_hint_parity(self):
        # Both task controllers must point a 401 at the in-chat fix.
        hint = "/token mint"
        assert hint in _read(TS_CONTROLLER), "VSCode 401 hint missing"
        assert hint in _read(WEB_BASE), "web 401 hint missing"
        for src, name in ((_read(TS_CONTROLLER), "vscode"),
                          (_read(WEB_BASE), "web")):
            assert re.search(r"status === 401", src), (
                f"{name} hint must gate on e.status === 401, not string-match"
            )
