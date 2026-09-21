"""Static structural tests for VSCode Step 5b.2 dispatcher rewrite (v1.18.1).

5b.2 turns the 35-case `handleSlashCommand` switch into a thin shell
over `dispatchFactoryCommand`, and deletes the bespoke handlers whose
logic now lives server-side in the factory.

Pinning what 5b.2 must keep stable so that 5c (Phase B + D wiring)
and Step 6 (end-to-end tests) can build on it without surprises.

**Retargeted 2026-09-21 by ADR 0007 step 3b.** 5b.2's intercept chain
(twelve hardcoded `command === '…'` branches) and its `CHAT_SHAPED_TASKS`
Map are GONE: routing is now the fetched roster's `dispatch` field, and
the `client_action` → implementation registry lives in
`src/commandRouter.ts`. The five 5b.2 behaviours below survive
unchanged — they are just asserted against the registry instead of
against a branch order:
  - Six chat-shaped commands stay client-side via _backend.codingTask
    (now the shared `coding.stream` action). VSCode's editor-context
    advantage (active file's language + filename) is the reason — the
    factory handlers don't have access.
  - /auto loop stays client-side per
    docs/TODO-v1.18.2-agent-loop-unification.md. Server-side
    validation (5b.1) gates short tasks before the loop runs, so the
    duplicate min-words check is gone.
  - /preview keeps its own previewPanel.ts WebviewPanel.
  - /help stays client-side because it appends VSCode-specific
    keyboard shortcuts (`help.augment` — and since step 3b it really
    does wrap the factory; see chatPanel.ts::showHelp).
  - Everything else routes via dispatchFactoryCommand, which uses
    CommandRenderer + SideEffectsHandler from 5a.

Bespoke handlers that 5b.2 deletes — these must NOT regress:
  - handleSpecCommand (factory now has rich templates per 5b.1)
  - handleShowCommand (factory emits OPEN_VIEWER + PROMPT_QUICK_PICK)
  - handleEditCommand (factory emits OPEN_EDITOR with line/column)
  - handleCdCommand, handlePwdCommand
  - handleUsageCommand + renderCommandResult (CommandRenderer covers it)
"""

from __future__ import annotations

import re
from pathlib import Path

import ppxai.commands.handler  # noqa: F401  (populates CommandFactory)
from ppxai.commands.factory import CommandFactory

EXT_SRC = Path(__file__).resolve().parents[1] / "vscode-extension" / "src"


def _read(rel: str) -> str:
    return (EXT_SRC / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The six chat-shaped commands — now ONE declared action, not a Map
# ---------------------------------------------------------------------------

def _client_actions_body(src: str) -> str:
    m = re.search(
        r"export const CLIENT_ACTIONS: Record<string, OpsAction> = \{([\s\S]*?)\n\};",
        src,
    )
    assert m, "CLIENT_ACTIONS registry not found in commandRouter.ts"
    return m.group(1)


class TestChatShapedTasksAction:
    """ADR 0007 step 3b replaced `CHAT_SHAPED_TASKS` with a declaration.

    The Map did two jobs. ROUTING moved to Python (`coding.stream`,
    declared for all six in `ppxai/commands/coding.py`) and the
    name→task_type MAPPING turned out to be the identity, so the
    implementation passes the roster-resolved canonical name straight
    through. Behaviour is pinned end-to-end in
    tests/test_vscode_command_roster_behavior.py; these are the
    structural fences.
    """

    def test_the_map_is_gone(self):
        src = _read("chatPanel.ts")
        assert "CHAT_SHAPED_TASKS" not in src or "deleted `CHAT_SHAPED_TASKS`" in src, (
            "CHAT_SHAPED_TASKS is back — the six chat-shaped commands are "
            "routed by the roster's coding.stream action now, and a local map "
            "would be a second source of truth for routing"
        )
        assert "new Map<string, string>([" not in src, (
            "a name→task_type Map came back in chatPanel.ts"
        )

    def test_python_declares_one_action_for_all_six(self):
        """The registry side of the same fact, read off Python."""
        infos = {i.canonical: i for i in CommandFactory.iter_completion_specs()}
        for cmd in ("generate", "explain", "test", "docs", "debug", "implement"):
            info = infos.get(cmd)
            assert info is not None, f"/{cmd} is not registered"
            assert info.client_action == "coding.stream", (
                f"/{cmd} declares {info.client_action!r}, not the shared "
                "coding.stream action"
            )
            assert info.client_action_clients is not None
            assert "vscode" in info.client_action_clients

    def test_registry_passes_the_resolved_name_as_task_type(self):
        body = _client_actions_body(_read("commandRouter.ts"))
        assert re.search(
            r"'coding\.stream':\s*\(ops, ctx\) =>\s*ops\.handleCodingTask\("
            r"ctx\.name,\s*ctx\.args\)",
            body,
        ), (
            "coding.stream must hand the CANONICAL command name the roster "
            "resolved to handleCodingTask as the task_type — that is what "
            "replaced CHAT_SHAPED_TASKS' mapping half"
        )

    def test_convert_keeps_its_own_action(self):
        """`/convert` is chat-shaped but has `<src> <dst> <code>` arg
        parsing, so it declares `coding.convert`, not `coding.stream`."""
        info = {i.canonical: i for i in CommandFactory.iter_completion_specs()}["convert"]
        assert info.client_action == "coding.convert"
        body = _client_actions_body(_read("commandRouter.ts"))
        assert "'coding.convert'" in body
        assert "handleConvert(ctx.argv)" in body

    def test_auto_is_not_chat_shaped(self):
        """`/auto <task>` runs the iteration loop client-side (loop
        unification still deferred), under its own action."""
        info = {i.canonical: i for i in CommandFactory.iter_completion_specs()}["auto"]
        assert info.client_action == "auto.loop"
        body = _client_actions_body(_read("commandRouter.ts"))
        assert "handleCodingTask" not in body.split("'auto.loop'")[1].split("\n")[0]


# ---------------------------------------------------------------------------
# handleSlashCommand — thin dispatcher shape
# ---------------------------------------------------------------------------

def _ops_body(src: str) -> str:
    """Extract the `PanelCommandOps` object literal `getCommandRouter`
    builds — the wiring that replaced the intercept chain."""
    m = re.search(
        r"const ops: PanelCommandOps = \{([\s\S]*?)\n\s{12}\};",
        src,
    )
    assert m, "the PanelCommandOps literal was not found in chatPanel.ts"
    return m.group(1)


class TestHandleSlashCommandShape:
    """After step 3b `handleSlashCommand` is three lines: route, catch.

    The 5b.2 invariant it used to carry (no 35-case switch, fallthrough
    to the factory) is now structural — there are no branches left to
    get wrong — so what these pin is that every implementation the old
    chain reached is still WIRED, and that routing itself is data.
    """

    def test_no_giant_switch(self):
        body = _read("chatPanel.ts")
        m = re.search(
            r"private\s+async\s+handleSlashCommand\s*\([^)]*\)\s*\{"
            r"([\s\S]*?)\n\s{4}\}",
            body,
        )
        assert m, "handleSlashCommand not found"
        inner = m.group(1)
        assert "switch (command)" not in inner
        assert not re.search(r"case\s+'/?\w+'\s*:", inner)
        assert "getCommandRouter().route(input)" in inner, (
            "handleSlashCommand must delegate to the roster-driven router"
        )

    def test_no_hardcoded_command_branches_remain(self):
        """The twelve `command === '…'` intercepts are the deletion that
        proves step 3b happened."""
        src = _read("chatPanel.ts")
        # `grep -v subcommand` in regex form: `subcommand === 'clear'`
        # inside handleContextCommand is a different thing entirely.
        found = sorted(set(re.findall(
            r"(?:^|[^A-Za-z])command === '([a-z?-]+)'", src, re.M)))
        assert found == [], (
            f"hardcoded per-command branches are back in chatPanel.ts: {found}. "
            "Routing must come from the roster."
        )

    def test_dispatches_to_factory_by_default(self):
        assert "dispatchToFactory: (name, args) => this.dispatchFactoryCommand(" \
            in _read("chatPanel.ts"), (
                "the router's default path must still reach dispatchFactoryCommand"
            )

    def test_chat_shaped_still_uses_coding_task(self):
        ops = _ops_body(_read("chatPanel.ts"))
        assert "handleCodingTask:" in ops and "handleCodingTaskCommand(" in ops, (
            "coding.stream must still reach handleCodingTaskCommand "
            "(preserves _backend.codingTask path with editor context)"
        )

    def test_keeps_agent_loop(self):
        ops = _ops_body(_read("chatPanel.ts"))
        assert "handleAgentCommand(" in ops, (
            "/auto must still reach handleAgentCommand "
            "(loop unification deferred to v1.18.2)"
        )

    def test_keeps_preview_webview(self):
        ops = _ops_body(_read("chatPanel.ts"))
        assert "handlePreviewCommand(" in ops, (
            "/preview owns its own webview panel — must stay client-side"
        )

    def test_keeps_help_for_keyboard_shortcuts(self):
        ops = _ops_body(_read("chatPanel.ts"))
        assert "showHelp:" in ops, (
            "/help must reach showHelp() to append VSCode-specific "
            "keyboard shortcuts to the factory output"
        )

    def test_help_now_actually_calls_the_factory(self):
        """The reconciliation ADR 0007's contract item 3 asked for.

        Before step 3b `showHelp` called `generateHelpText()` — the
        hand-written `shared/commands.ts` catalog — and never touched the
        factory, despite every comment saying "factory output + shortcuts".
        """
        src = _read("chatPanel.ts")
        assert "private async showHelp(" in src, "showHelp not found"
        assert "executeCommand('help', args, VSCODE_CLIENT_ID)" in src, (
            "showHelp must render the SERVER's /help (with client:\"vscode\"), "
            "not a client-side catalog"
        )
        # The name survives only in the tombstone comment on showHelp.
        assert "generateHelpText()" not in src.replace(
            "called `generateHelpText()`", ""), (
            "generateHelpText is deleted with shared/commands.ts"
        )
        assert "from './shared/commands'" not in src, (
            "chatPanel must not import the deleted catalog"
        )
        assert "helpText += '\\n**Agent platform (client-side, experimental):**" \
            not in src, (
            "the hardcoded experimental-help block must go with it — /run and "
            "/task have been factory-registered since T8b"
        )


# ---------------------------------------------------------------------------
# dispatchFactoryCommand — envelope unwrap
# ---------------------------------------------------------------------------

class TestDispatchFactoryCommand:
    def test_method_exists(self):
        src = _read("chatPanel.ts")
        assert "private async dispatchFactoryCommand" in src

    def test_calls_executeCommand(self):
        src = _read("chatPanel.ts")
        m = re.search(
            r"private\s+async\s+dispatchFactoryCommand[\s\S]*?\n\s{4}\}",
            src,
        )
        assert m
        body = m.group(0)
        assert "_backend.executeCommand" in body, (
            "dispatcher must call _backend.executeCommand to get the "
            "v1 envelope"
        )

    def test_renders_result_and_applies_side_effects(self):
        src = _read("chatPanel.ts")
        m = re.search(
            r"private\s+async\s+dispatchFactoryCommand[\s\S]*?\n\s{4}\}",
            src,
        )
        assert m
        body = m.group(0)
        assert "getCommandRenderer" in body and ".render(" in body, (
            "dispatcher must render envelope.result via CommandRenderer"
        )
        assert "getSideEffectsHandler" in body and ".apply(" in body, (
            "dispatcher must apply envelope.side_effects via "
            "SideEffectsHandler"
        )

    def test_unknown_command_friendly_error(self):
        """A 404 from the server should show 'Unknown command: /foo'
        with a /help hint, matching the pre-v1.18.1 default branch."""
        src = _read("chatPanel.ts")
        m = re.search(
            r"private\s+async\s+dispatchFactoryCommand[\s\S]*?\n\s{4}\}",
            src,
        )
        assert m
        body = m.group(0)
        assert "Unknown command" in body, (
            "Friendly fallback for 404 (unknown command) is missing"
        )


# ---------------------------------------------------------------------------
# Wiring — CommandRenderer + SideEffectsHandler are reachable
# ---------------------------------------------------------------------------

class TestRendererWiring:
    def test_command_renderer_lazy_getter(self):
        src = _read("chatPanel.ts")
        assert "private getCommandRenderer(): CommandRenderer" in src

    def test_side_effects_handler_lazy_getter(self):
        src = _read("chatPanel.ts")
        assert "private getSideEffectsHandler(): SideEffectsHandler" in src

    def test_dispatch_resume_for_quick_pick(self):
        """SideEffectHost.dispatchCommandFromSideEffect re-issues a
        command with the picked value as args — per ADR Q3 (b)."""
        src = _read("chatPanel.ts")
        m = re.search(
            r"dispatchCommandFromSideEffect:[\s\S]*?\}",
            src,
        )
        assert m
        body = m.group(0)
        assert "dispatchFactoryCommand" in body, (
            "PROMPT_QUICK_PICK resume must re-enter the factory "
            "dispatcher with the picked args"
        )

    def test_working_dir_hint_from_appstate(self):
        """SideEffectHost.getWorkingDirHint reads from AppState — the
        canonical mirror — not from a private field."""
        src = _read("chatPanel.ts")
        assert "_appState.get('workingDir')" in src, (
            "getWorkingDirHint should source from AppState (the "
            "engine-canonical mirror), not a private field"
        )


# ---------------------------------------------------------------------------
# Removed bespoke handlers — must NOT come back
# ---------------------------------------------------------------------------

class TestRemovedHandlers:
    """Each of these methods was inlining factory logic client-side.
    5b.1 ported the rich templates; 5b.2 removes the duplicates."""

    def _src(self) -> str:
        return _read("chatPanel.ts")

    def test_no_handleSpecCommand(self):
        # The method declaration is gone; tombstone comment may
        # mention it. Match only on the declaration form.
        assert "private async handleSpecCommand" not in self._src(), (
            "handleSpecCommand must be deleted — factory's handle_spec "
            "(ppxai/commands/system.py) ships the rich templates now"
        )

    def test_no_handleShowCommand(self):
        assert "private async handleShowCommand" not in self._src(), (
            "handleShowCommand must be deleted — factory's handle_show "
            "emits OPEN_VIEWER side-effects"
        )

    def test_no_handleEditCommand(self):
        assert "private async handleEditCommand" not in self._src(), (
            "handleEditCommand must be deleted — factory's handle_edit "
            "emits OPEN_EDITOR with line/column"
        )

    def test_no_handleCdCommand(self):
        assert "private async handleCdCommand" not in self._src(), (
            "handleCdCommand must be deleted — factory's handle_cd "
            "emits REFRESH_FILE_TREE; cwd updates flow via state_sync"
        )

    def test_no_handlePwdCommand(self):
        assert "private async handlePwdCommand" not in self._src(), (
            "handlePwdCommand must be deleted — factory's handle_pwd "
            "returns a NotificationResult"
        )

    def test_no_handleUsageCommand_or_renderCommandResult(self):
        src = self._src()
        assert "private async handleUsageCommand" not in src, (
            "handleUsageCommand must be deleted — /usage flows through "
            "dispatchFactoryCommand"
        )
        assert "private renderCommandResult" not in src, (
            "renderCommandResult must be deleted — CommandRenderer "
            "handles the full result taxonomy"
        )

    def test_no_duplicate_min_words_check(self):
        """The agent-task validation moved server-side in 5b.1. The
        client-side duplicate at chatPanel.ts:1118-1135 is gone."""
        src = self._src()
        # The pre-v1.18.1 message had this exact phrase
        assert "Task too vague:" not in src, (
            "Duplicate client-side min-words check must be gone — "
            "validate_agent_task on the server is the single source"
        )
        # Sanity: factory rejection hits via /chat or factory route
        # We just check the client doesn't replicate the threshold
        assert "words.length < minWords" not in src, (
            "Client-side min-words comparison must be gone (was the "
            "duplicate validation)"
        )


# ---------------------------------------------------------------------------
# Net size — sanity check that 5b.2 actually shrunk the file
# ---------------------------------------------------------------------------

class TestSizeReduction:
    def test_chatpanel_smaller_than_3000_lines(self):
        """Pre-5b.2 chatPanel.ts was ~3055 LoC. After 5b.2 (the dead
        handlers + 35-case switch are gone) it should be well under
        3000. Loose floor — guard against accidental regressions.

        Threshold history: 3000 (5b.2). ADR 0007 step 3b removed the
        twelve-branch intercept chain and `CHAT_SHAPED_TASKS` and added
        the router wiring + a real factory-backed `showHelp`; the
        threshold was DELIBERATELY NOT raised — the `client_action`
        registry and the legacy table live in `src/commandRouter.ts`,
        which is where a parity fence needs to read them anyway."""
        src = _read("chatPanel.ts")
        line_count = src.count("\n") + 1
        assert line_count < 3000, (
            f"chatPanel.ts is {line_count} lines — 5b.2 was meant to "
            f"drop several hundred LoC. Has handler logic crept back?"
        )
