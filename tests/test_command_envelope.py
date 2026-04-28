"""POST /command/<name> envelope contract tests (v1.18.1).

The envelope is the wire format for the unified command dispatcher:

    {
      "ok": bool,
      "result": { ... CommandResult.to_dict() ... },
      "side_effects": [ {"kind": str, ...payload} ],
      "version": 1
    }

Goal of this file: pin the envelope's shape AND the side-effect
contract so future changes to handlers can't silently drift either.
The split-brain command implementation (v1.17.4 → v1.18.0) hid in
production for six releases because no tests exercised the path —
this is the missing fence.

Tests do NOT depend on a real LLM provider. Side-effect emission is
verified by calling handlers directly through the factory, then
re-checked through the HTTP route to confirm the route promotes
them into the envelope.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import (
    CommandResult,
    NotificationResult,
    ResultStatus,
    SideEffect,
    SideEffectKind,
    TableResult,
)


# ---------------------------------------------------------------------------
# SideEffectKind taxonomy sentinel
# ---------------------------------------------------------------------------

class TestSideEffectKindTaxonomy:
    """Pin the v1.18.1 kind taxonomy.

    The constants in `SideEffectKind` and the docstring on `SideEffect`
    list the same set of kinds. If they drift, this test fails loudly
    so handler authors don't reach for an undocumented kind (or a
    documented-but-not-constant one).

    Web and VSCode renderers honor the documented kinds. Adding a new
    kind: add the constant in SideEffectKind AND list it in the
    SideEffect docstring AND extend this test's expected set.
    """

    # The canonical v1.18.1 kind set — kept here so a sentinel diff is
    # the audit trail for every taxonomy change.
    EXPECTED_KINDS_V1 = frozenset({
        "open_editor",
        "open_viewer",
        "show_image",
        "show_pdf",
        "reveal_in_explorer",
        "open_terminal",
        "run_shell",
        "open_html_preview",
        "refresh_file_tree",
        "set_theme",
        "copy_to_clipboard",
        "attach_file",
        "prompt_quick_pick",
        "notify",
        "vscode_delegate",
    })

    def test_sideeffect_kind_constants_match_expected(self):
        """SideEffectKind exposes exactly the v1.18.1 kind set."""
        actual = frozenset(SideEffectKind.all_kinds())
        missing = self.EXPECTED_KINDS_V1 - actual
        extra = actual - self.EXPECTED_KINDS_V1
        assert not missing, f"SideEffectKind missing kinds: {missing}"
        assert not extra, (
            f"SideEffectKind has unexpected kinds: {extra}. "
            f"Update EXPECTED_KINDS_V1 if intentional."
        )

    def test_docstring_lists_all_kinds(self):
        """SideEffect docstring documents every constant in SideEffectKind."""
        from ppxai.commands.results import SideEffect
        doc = SideEffect.__doc__ or ""
        for kind in SideEffectKind.all_kinds():
            quoted = f'"{kind}"'
            assert quoted in doc, (
                f"SideEffect docstring missing kind {quoted}. "
                f"Add it to the 'Known kinds' block."
            )

    def test_no_uppercase_constant_collisions(self):
        """No two SideEffectKind constants alias the same kind value."""
        kinds = list(SideEffectKind.all_kinds())
        assert len(kinds) == len(set(kinds)), (
            f"Duplicate kind values: {kinds}"
        )


# ---------------------------------------------------------------------------
# SideEffect dataclass shape
# ---------------------------------------------------------------------------

class TestSideEffectDataclass:
    def test_defaults(self):
        se = SideEffect(kind="notify")
        assert se.kind == "notify"
        assert se.payload == {}

    def test_to_dict_flattens_payload(self):
        se = SideEffect(kind="open_html_preview", payload={"url": "x", "filepath": "/a"})
        assert se.to_dict() == {"kind": "open_html_preview", "url": "x", "filepath": "/a"}

    def test_to_dict_no_payload(self):
        assert SideEffect(kind="refresh").to_dict() == {"kind": "refresh"}


class TestCommandResultSideEffects:
    def test_default_empty(self):
        r = NotificationResult(status=ResultStatus.SUCCESS, message="ok")
        assert r.side_effects == []

    def test_add_side_effect_helper(self):
        r = NotificationResult(status=ResultStatus.SUCCESS, message="ok")
        r.add_side_effect("notify", level="info", message="hi")
        assert len(r.side_effects) == 1
        assert r.side_effects[0].kind == "notify"
        assert r.side_effects[0].payload == {"level": "info", "message": "hi"}

    def test_to_dict_excludes_side_effects(self):
        """Side-effects live in the envelope, NOT in the result payload."""
        r = NotificationResult(status=ResultStatus.SUCCESS, message="ok")
        r.add_side_effect("notify", level="info", message="hi")
        d = r.to_dict()
        assert "side_effects" not in d
        assert d["type"] == "NotificationResult"

    def test_multiple_side_effects_preserve_order(self):
        r = TableResult(status=ResultStatus.SUCCESS, message="rows")
        r.add_side_effect("notify", message="first")
        r.add_side_effect("refresh_file_tree", cwd="/x")
        kinds = [se.kind for se in r.side_effects]
        assert kinds == ["notify", "refresh_file_tree"]


# ---------------------------------------------------------------------------
# HTTP envelope
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_command():
    """Register a temporary command emitting two side-effects.

    Yields the command name; unregisters in teardown.
    """
    name = "_envelope_probe"

    def handler(ctx, args):
        r = NotificationResult(status=ResultStatus.SUCCESS, message=f"args={args}")
        r.add_side_effect("notify", level="info", message="hello")
        r.add_side_effect("refresh_file_tree", cwd="/probe")
        return r

    from ppxai.commands.factory import CommandSpec
    spec = CommandSpec(
        name=name,
        usage=f"/{name}",
        description="envelope test probe",
        handler=handler,
    )
    CommandFactory.register(spec)
    yield name
    CommandFactory.unregister(name)


@pytest.fixture
def http_client():
    """TestClient against the FastAPI app — no session manager mocking."""
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


class TestEnvelopeShape:
    def test_envelope_has_all_top_level_fields(self, http_client, stub_command):
        resp = http_client.post(f"/command/{stub_command}", json={"args": "hi"})
        assert resp.status_code == 200
        body = resp.json()
        # v1.18.1 Phase B: envelope gained `events[]` for drained
        # engine side-channel events alongside the existing keys.
        assert set(body.keys()) == {
            "ok", "result", "side_effects", "events", "version"
        }

    def test_version_is_one(self, http_client, stub_command):
        body = http_client.post(f"/command/{stub_command}", json={"args": ""}).json()
        assert body["version"] == 1

    def test_ok_mirrors_success(self, http_client, stub_command):
        body = http_client.post(f"/command/{stub_command}", json={"args": ""}).json()
        assert body["ok"] is True
        assert body["result"]["status"] == "success"

    def test_result_is_command_result_dict(self, http_client, stub_command):
        body = http_client.post(f"/command/{stub_command}", json={"args": "x"}).json()
        result = body["result"]
        assert result["type"] == "NotificationResult"
        assert result["status"] == "success"
        assert "args=x" in result["message"]
        # side_effects MUST NOT leak into the result dict
        assert "side_effects" not in result

    def test_side_effects_promoted_to_envelope(self, http_client, stub_command):
        body = http_client.post(f"/command/{stub_command}", json={"args": ""}).json()
        side_effects = body["side_effects"]
        assert isinstance(side_effects, list)
        assert len(side_effects) == 2

        notify, refresh = side_effects
        assert notify == {"kind": "notify", "level": "info", "message": "hello"}
        assert refresh == {"kind": "refresh_file_tree", "cwd": "/probe"}

    def test_side_effects_empty_when_handler_emits_none(self, http_client):
        """A factory command that emits no side-effects returns []."""
        body = http_client.post("/command/help", json={"args": ""}).json()
        assert body["side_effects"] == []

    def test_unknown_command_returns_404(self, http_client):
        resp = http_client.post("/command/__no_such_command__", json={"args": ""})
        assert resp.status_code == 404


class TestHandlerSideEffectEmission:
    """Real factory handlers must emit the right side-effect kinds.

    These tests guard against regressions where a handler stops
    emitting its side-effect and the web/VSCode UI silently loses
    the panel-open / tree-refresh / theme-switch behavior.
    """

    def test_cd_emits_refresh_file_tree(self, http_client, tmp_path):
        body = http_client.post(
            "/command/cd", json={"args": str(tmp_path)}
        ).json()
        kinds = [se["kind"] for se in body["side_effects"]]
        assert "refresh_file_tree" in kinds, body
        refresh = next(se for se in body["side_effects"] if se["kind"] == "refresh_file_tree")
        assert "cwd" in refresh

    def test_theme_emits_set_theme(self, http_client):
        body = http_client.post("/command/theme", json={"args": "dracula"}).json()
        kinds = [se["kind"] for se in body["side_effects"]]
        # Theme switch may fail if theme name unknown — we still want
        # set_theme emitted on success path.
        if body["ok"]:
            assert "set_theme" in kinds, body

    def test_terminal_emits_open_terminal(self, http_client):
        body = http_client.post("/command/terminal", json={"args": ""}).json()
        kinds = [se["kind"] for se in body["side_effects"]]
        assert "open_terminal" in kinds, body


class TestEnvelopeBackwardCompat:
    """Existing callers reading `envelope["result"]` get the same dict
    they used to get from the route. This test catches accidental
    schema renames in `CommandResult.to_dict()`."""

    def test_result_dict_has_legacy_keys(self, http_client, stub_command):
        body = http_client.post(f"/command/{stub_command}", json={"args": ""}).json()
        result = body["result"]
        for key in ("type", "status", "message", "metadata"):
            assert key in result, f"Missing legacy key: {key}"


class TestRouteLogging:
    """v1.18.2 Item 7: every POST /command/<name> emits an info-level
    log line so the unified dispatch path is visible in server-debug.log.

    Pre-fix, the route was silent — the v1.18.1 unification could
    silently revert to bespoke endpoints (the exact failure mode it was
    built to prevent) and we'd never see it in production logs. The
    2026-04-27 webapp session showed only client-echo lines for 8
    slash commands across 21 minutes; nothing on the server side.

    Note: the `ppxai.common.Logger` wrapper is a no-op until enabled
    (via env var or `/debug-log on`). These tests force-enable the
    "server" logger for the duration of each test so caplog can see
    the records — mirroring the production scenario where debug-log
    is toggled on before investigating an issue.
    """

    @pytest.fixture(autouse=True)
    def _enable_server_logger(self, tmp_path, monkeypatch):
        """Force the existing server Logger singleton on with file output
        redirected to tmp_path. Must NOT replace the singleton — module-
        level `logger = get_logger("server")` references in route files
        captured the original instance at import time; popping it here
        would leave those references pointing at the orphaned disabled
        Logger.
        """
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        from ppxai.common.logger import get_logger
        log = get_logger("server")
        was_enabled = log.enabled
        if not was_enabled:
            log.enable()
        yield
        if not was_enabled and hasattr(log, "disable"):
            log.disable()

    def test_route_logs_request(self, http_client, stub_command, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="ppxai.server"):
            http_client.post(f"/command/{stub_command}", json={"args": "abc"})
        matches = [r for r in caplog.records if "/command/" in r.getMessage()]
        assert matches, "expected an info log line containing '/command/'"
        msg = matches[0].getMessage()
        assert stub_command in msg
        assert "session=" in msg
        assert "abc" in msg, "args preview should be in the log line"

    def test_unknown_command_logs_warning(self, http_client, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="ppxai.server"):
            http_client.post("/command/__definitely_not_a_command__", json={"args": ""})
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("Unknown command" in r.getMessage() for r in warnings)

    def test_long_args_truncated_to_120_chars(self, http_client, stub_command, caplog):
        import logging
        long_args = "x" * 500
        with caplog.at_level(logging.INFO, logger="ppxai.server"):
            http_client.post(f"/command/{stub_command}", json={"args": long_args})
        # Find the route log line (not the handler's own logs).
        route_lines = [
            r.getMessage() for r in caplog.records
            if "POST /command/" in r.getMessage()
        ]
        assert route_lines
        # 'x' * 120 should fit; 'x' * 500 must NOT — truncation guard
        # exists to keep log lines bounded for noisy /agent prompts.
        assert "x" * 120 in route_lines[0]
        assert "x" * 500 not in route_lines[0]
