"""Third-client parity: the TUI must implement what web and VSCode do.

`test_vscode_task_controller.py` pins web ↔ VSCode: the same `/v1/agent/*`
endpoints, the same collect semantics, the same refusal hints. It is a good
harness and it caught real drift — but it knows about **two** clients.

T8b added a third. Every defect found in the 2026-08-09 live trial was the
same shape: a capability the other two clients have and the TUI silently
lacks. None of them failed a test, because no test knew the TUI was supposed
to have them.

  * `collect` finalized the run but never merged the result into the session,
    so TUI sessions stayed message-less and session restore had nothing to
    restore. Web (`agent-run-controller.js:121`) and VSCode
    (`taskController.ts:596`) both merge.
  * The in-process registry got no `on_change` hook, so
    `AppState.background_agents` was never written — while `tui/app.py:254`
    subscribes to it and renders a badge that could never light.
  * The in-process registry got no `sweep_orphans()`, so a run orphaned by a
    TUI exit stays `running` forever and `/task ls` lies after a restart.

These are source-level assertions, deliberately, matching the existing
harness's idiom: they must fail for a client that has not implemented the
behaviour, without needing that client booted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

TUI_COMMAND = ROOT / "ppxai" / "commands" / "task.py"
TUI_BACKEND = ROOT / "ppxai" / "engine" / "task_backend.py"
TUI_APP = ROOT / "ppxai" / "tui" / "app.py"
SERVER_STATE = ROOT / "ppxai" / "server" / "state.py"
WEB_BASE = ROOT / "ppxai" / "web" / "shared" / "agent-run-controller.js"


def _read(path: Path) -> str:
    assert path.exists(), f"missing source: {path}"
    return path.read_text(encoding="utf-8")


# ── collect semantics: the third column of the existing sentinel ────────────

class TestCollectParity:
    """U4 (ADR 0011) collect must mean the same thing in all three clients.

    The other two are pinned by
    `test_vscode_task_controller.py::test_collect_semantics_parity`. The TUI
    is in-process, so it cannot call `/sessions/merge-run-result` over HTTP —
    it must do what that route does: append the pair to the session.
    """

    def test_tui_consults_the_collect_mode(self):
        """`execution.collect` decides whether results merge at all."""
        src = _read(TUI_BACKEND) + _read(TUI_COMMAND)
        assert "get_execution_collect" in src, (
            "the TUI never reads execution.collect — web fetches "
            "/config/execution and VSCode mirrors it"
        )

    def test_tui_refuses_collect_when_disabled(self):
        """`execution.collect="no"` must produce the same visible refusal.

        Both other clients carry the literal hint; a user who disabled collect
        deserves to be told that, not to watch a result vanish.
        """
        src = _read(TUI_BACKEND) + _read(TUI_COMMAND)
        assert "Collect is disabled" in src, (
            'the TUI lacks the "Collect is disabled" refusal that web and '
            "VSCode both surface"
        )

    def test_tui_merges_the_run_result_into_the_session(self):
        """THE defect that made session restore useless.

        `sessions.py::merge_run_result` appends user(task) → assistant(result).
        The TUI must do the same, or its runs never enter the conversation and
        every session it saves is message-less.
        """
        src = _read(TUI_BACKEND) + _read(TUI_COMMAND)
        assert "add_message" in src, (
            "collect finalizes the run but never merges its result into the "
            "session — web and VSCode both POST /sessions/merge-run-result"
        )

    def test_tui_merges_a_PAIR_not_a_lone_message(self):
        """The pair shape is load-bearing, not cosmetic.

        `validate_and_fix_alternation` drops a lone message of either role, so
        a half-merge silently vanishes from the next provider request — caught
        live in the U4 trial, where the model answered "no passphrase
        appeared" while the merge sat dropped.
        """
        src = _read(TUI_BACKEND) + _read(TUI_COMMAND)
        assert src.count("add_message") >= 2, (
            "only one add_message call — the merge must be a user→assistant "
            "PAIR or the alternation fixer can drop it"
        )
        assert 'role="user"' in src and 'role="assistant"' in src, (
            "the merged pair must carry both roles explicitly"
        )


# ── composition root: what server/state.py layers on the bare registry ──────

class TestRegistryCompositionParity:
    """`default_run_registry()` is deliberately bare.

    Its docstring says the sweep and the change hooks are "lifecycle concerns
    of whoever owns the process". `server/state.py` owns one and layers them
    on. T8b made the TUI own one too — and layered nothing.

    Anyone adding a fourth composition root should be told, not left to find
    out from a badge that never lights.
    """

    def _composition_roots(self) -> list[Path]:
        """Every module that builds its own registry."""
        roots = []
        for path in (ROOT / "ppxai").rglob("*.py"):
            if "default_run_registry(" in path.read_text(encoding="utf-8"):
                if path.name != "task_runner.py":  # the definition itself
                    roots.append(path)
        return roots

    def test_the_expected_roots_are_found(self):
        """Guard against the scan silently matching nothing."""
        names = {p.name for p in self._composition_roots()}
        assert {"state.py", "task_backend.py"} <= names, (
            f"expected the server and TUI composition roots, found {names}"
        )

    @pytest.mark.parametrize("attr", ["sweep_orphans", "on_change"])
    def test_every_composition_root_layers_the_lifecycle(self, attr):
        missing = [
            p.name for p in self._composition_roots()
            if attr not in p.read_text(encoding="utf-8")
        ]
        assert not missing, (
            f"{missing} build a run registry without {attr}(). "
            f"server/state.py does both: sweep_orphans() reconciles runs "
            f"orphaned by a dead process, and on_change() is what writes "
            f"AppState.background_agents."
        )


# ── AppState: a subscribed key needs a writer this process can reach ────────

class TestAppStateBackgroundAgents:
    """`tui/app.py:254` subscribes to `background_agents` and renders a badge.

    Its own comment says "The server mirrors the active /v1/agent/* run set
    into AppState.background_agents" — true over HTTP, and false in-process,
    where there is no server. A reader with no reachable writer is a feature
    that cannot work.
    """

    def test_the_tui_still_subscribes(self):
        """If this stops being true, the rest of this class is moot."""
        assert 'state.on(\n                "background_agents"' in _read(TUI_APP) \
            or '"background_agents"' in _read(TUI_APP), (
            "the TUI no longer subscribes to background_agents — delete this "
            "class rather than weakening it"
        )

    def test_something_in_process_writes_background_agents(self):
        """The server writes it via broadcast_background_agents.

        In-process there must be an equivalent writer, or the badge is dead
        code in every TUI session.
        """
        writers = []
        for path in (ROOT / "ppxai").rglob("*.py"):
            if path.name in {"session_manager.py", "app_state.py"}:
                continue  # the server's writer and the store itself
            src = path.read_text(encoding="utf-8")
            if re.search(r'set\(\s*["\']background_agents["\']', src) or \
               "broadcast_background_agents" in src:
                writers.append(path.name)
        assert writers, (
            "nothing outside the server writes AppState.background_agents, so "
            "the TUI badge can never light in an in-process session"
        )
