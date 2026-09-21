"""`/checkpoint` over real HTTP, after the last legacy intercept went.

VSCode handled `/checkpoint` client-side until 2026-09-21 — the last row
of `commandRouter.ts`'s `LEGACY_INTERCEPTS`, hitting bespoke REST
endpoints through `handlers/commands.ts`. Those files are deleted and the
command routes through `POST /command/checkpoint` like every other
server command, so what that client renders is now whatever the ENVELOPE
carries. These tests drive the real FastAPI app with `TestClient` and
assert each subcommand still produces a usable envelope.

Why over HTTP rather than by calling the handler: the envelope is the
contract the migrated client reads (`{ok, result, side_effects, events,
version}`), and a handler that returns a fine `CommandResult` can still
serialize badly — `ConfirmationResult.details` has done exactly that
before (`_jsonsafe` exists because of it).

The bespoke endpoints under `/checkpoint/*` are deliberately NOT asserted
gone: they serve non-command UI (the webview's Undo button reaches
`undoCheckpoint()`), which command-envelope.md rule 1 explicitly allows.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

import ppxai.server.http as http_module
from ppxai.commands.results import SideEffectKind
from ppxai.engine.client import EngineClient


@pytest.fixture
def file_backend(monkeypatch):
    """Pin the ENGINE's checkpoint state, host-independently.

    Without this the `clear` branch depends on whatever backend the
    machine running the suite happens to have, and the interesting
    assertions degrade into a skip — the "green because it doesn't look"
    failure mode. Patching the three `EngineClient` methods the handler
    calls makes the destructive path deterministic AND keeps it off
    disk: `clear_file_checkpoints` is replaced, so nothing under
    `~/.ppxai/sessions/checkpoints/` is ever touched.
    """
    cleared: list[int] = []
    monkeypatch.setattr(EngineClient, "get_checkpoint_status",
                        lambda self: {"backend": "file"})
    monkeypatch.setattr(
        EngineClient, "list_checkpoints",
        lambda self, limit=10: [
            {"id": f"cp{i}", "description": "d", "timestamp": "2026-09-21"}
            for i in range(3)
        ])
    monkeypatch.setattr(
        EngineClient, "clear_file_checkpoints",
        lambda self, keep_last=0: (cleared.append(keep_last), 3)[1])
    return cleared


@pytest.fixture
def http_client():
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


def _post(client, args: str):
    resp = client.post("/command/checkpoint",
                       json={"args": args, "client": "vscode"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _kinds(envelope) -> list[str]:
    return [se["kind"] for se in envelope["side_effects"]]


class TestEnvelopeShapePerSubcommand:
    """Every subcommand VSCode used to render locally must come back in
    a well-formed envelope. The status/list/info branches depend on the
    host's checkpoint state, so these assert the SHAPE, not the text."""

    @pytest.mark.parametrize("args", [
        "", "status", "list", "backend", "info", "info deadbeef", "undo",
        "clear", "clear --yes", "clear --no",
    ])
    def test_the_envelope_is_well_formed(self, http_client, args):
        body = _post(http_client, args)
        assert set(body) >= {"ok", "result", "side_effects", "events", "version"}
        # `ok` mirrors the RESULT's success, and several branches
        # legitimately fail on a host with no checkpoints (`list` ->
        # "No checkpoints found"), so the invariant is that a subcommand
        # RENDERS — never that it succeeds.
        assert isinstance(body["ok"], bool)
        assert isinstance(body["result"], dict)
        assert body["result"]["message"]
        assert body["result"]["status"] in (
            "success", "error", "warning", "info")
        assert isinstance(body["side_effects"], list)

    @pytest.mark.parametrize("args", ["backend nonsense", "wat"])
    def test_a_bad_argument_is_a_rendered_error_not_a_500(self, http_client, args):
        body = _post(http_client, args)
        assert body["result"]["status"] == "error"

    def test_backend_without_a_value_reports_rather_than_sets(self, http_client):
        body = _post(http_client, "backend")
        assert body["result"]["status"] != "error"

    def test_the_result_is_json_round_trippable(self, http_client):
        """`ConfirmationResult.details` is free-form; `_jsonsafe` exists
        because a handler once put engine objects in it."""
        json.dumps(_post(http_client, "status"))


class TestClearConfirmationOnTheWire:
    """The reason `/checkpoint` could migrate at all."""

    def test_unflagged_clear_never_returns_a_bare_success(self, http_client):
        """Whatever the host's backend is, an unflagged `clear` must
        either refuse (non-file backend), report nothing to do, or ASK —
        it must never come back as a completed destructive action."""
        body = _post(http_client, "clear")
        result = body["result"]
        asked = SideEffectKind.PROMPT_QUICK_PICK in _kinds(body)
        refused = result["status"] == "error"
        nothing_to_do = "No file checkpoints" in result["message"]
        assert asked or refused or nothing_to_do, (
            "`/checkpoint clear` came back as a plain success with no "
            f"confirmation: {body}")

    def test_it_asks_and_cancel_is_first(self, http_client, file_backend):
        body = _post(http_client, "clear")
        assert SideEffectKind.PROMPT_QUICK_PICK in _kinds(body), body
        se = next(s for s in body["side_effects"]
                  if s["kind"] == SideEffectKind.PROMPT_QUICK_PICK)
        assert se["command_to_resume"] == "checkpoint"
        assert se["items"][0]["value"] == "clear --no"
        assert se["items"][1]["value"] == "clear --yes"

    def test_the_asking_pass_deletes_nothing_over_http(self, http_client,
                                                       file_backend):
        """The negative assertion, end to end: a client POSTing an
        unflagged `clear` must not reach `clear_file_checkpoints`."""
        _post(http_client, "clear")
        assert file_backend == [], (
            "the engine cleared checkpoints on the ASKING pass")

    def test_the_yes_pass_deletes_over_http(self, http_client, file_backend):
        body = _post(http_client, "clear --yes")
        assert file_backend == [0], "the --yes resume did not reach the engine"
        assert "3" in body["result"]["message"]

    def test_the_no_pass_deletes_nothing_over_http(self, http_client,
                                                   file_backend):
        body = _post(http_client, "clear --no")
        assert file_backend == []
        assert "Cancelled" in body["result"]["message"]

    def test_the_resume_args_survive_the_wire(self, http_client):
        """The picked value is `clear --yes` — a string with a space and
        a flag. It travels as the POST body's `args`, and both JS clients
        rebuild it as `/<command_to_resume> <value>`."""
        for args in ("clear --yes", "clear --no"):
            body = _post(http_client, args)
            # Whatever the host backend, the flag PARSED — an args string
            # mangled in transit would land in the unknown-flag branch.
            assert "Unknown flag" not in body["result"]["message"], body

    def test_a_genuinely_unknown_flag_still_reports_one(self, http_client):
        """Positive control for the assertion above: the unknown-flag
        branch exists and is reachable over the wire, so its ABSENCE
        means something."""
        body = _post(http_client, "clear --force")
        message = body["result"]["message"]
        assert "Unknown flag" in message or body["result"]["status"] == "error", body
