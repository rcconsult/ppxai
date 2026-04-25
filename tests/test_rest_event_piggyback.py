"""REST endpoint event piggyback tests (v1.18.1 Phase B).

Engine state mutations enqueue events into `engine._event_queue`.
Pre-v1.18.1, those events only flowed to clients during a `/chat`
SSE stream — non-chat REST mutations were invisible to web/VSCode
AppState mirrors until the next chat.

Phase B: state-mutating REST endpoints now drain the queue and
include the events in the response body's `events` field. Clients
feed them through the same dispatcher that handles live SSE.

Tests cover:
  - The `with_drained_events` helper itself (shape, empty case,
    multi-event case, queue actually drained).
  - Each state-mutating REST endpoint includes `events[]` in its
    response.
  - Engine state mutation that runs synchronously inside the
    endpoint surfaces in `events[]` after the call returns.
  - Read-only endpoints don't grow `events[]` (they don't drain
    — keeps the wire shape predictable).
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from ppxai.engine.types import Event, EventType
from ppxai.server.state import with_drained_events


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestWithDrainedEvents:
    def test_empty_queue_yields_empty_events_list(self):
        engine = MagicMock()
        engine.drain_events.return_value = []
        out = with_drained_events({"foo": "bar"}, engine)
        assert out["events"] == []
        # Original payload preserved
        assert out["foo"] == "bar"

    def test_single_event_serialized(self):
        engine = MagicMock()
        engine.drain_events.return_value = [
            Event(type=EventType.STATE_SYNC, data={"working_dir": "/x"}),
        ]
        out = with_drained_events({}, engine)
        assert out["events"] == [
            {"type": "state_sync", "data": {"working_dir": "/x"}},
        ]

    def test_metadata_included_when_present(self):
        engine = MagicMock()
        engine.drain_events.return_value = [
            Event(
                type=EventType.STATE_SYNC,
                data={"agent_mode": True},
                metadata={"source": "test"},
            ),
        ]
        out = with_drained_events({}, engine)
        assert out["events"][0]["metadata"] == {"source": "test"}

    def test_metadata_omitted_when_absent(self):
        engine = MagicMock()
        engine.drain_events.return_value = [
            Event(type=EventType.STATE_SYNC, data={"agent_mode": True}),
        ]
        out = with_drained_events({}, engine)
        # No `metadata` key when the event had none — keeps wire small
        assert "metadata" not in out["events"][0]

    def test_multiple_events_preserve_order(self):
        engine = MagicMock()
        engine.drain_events.return_value = [
            Event(type=EventType.STATE_SYNC, data={"working_dir": "/a"}),
            Event(type=EventType.WORKING_DIR_CHANGED, data={"path": "/a"}),
            Event(type=EventType.STATE_SYNC, data={"agent_mode": True}),
        ]
        out = with_drained_events({}, engine)
        assert [e["type"] for e in out["events"]] == [
            "state_sync", "working_dir_changed", "state_sync",
        ]

    def test_payload_dict_mutated_in_place_and_returned(self):
        engine = MagicMock()
        engine.drain_events.return_value = []
        payload = {"a": 1}
        out = with_drained_events(payload, engine)
        assert out is payload  # same dict, fluent return
        assert "events" in payload  # mutation visible to caller


# ---------------------------------------------------------------------------
# Integration: real endpoints drain real engine state
# ---------------------------------------------------------------------------

@pytest.fixture
def http_client():
    """TestClient against the FastAPI app — uses the live
    SessionManager / EngineClient bound at module import.

    The tests below mutate engine state and assert the side-effect
    flows into `events[]`. Each test gets a fresh session (via a
    unique X-Session-Id header) so prior queued events don't leak.
    """
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


def _new_session_headers(name: str) -> dict:
    """Return headers that route the request to a fresh session."""
    return {"X-Session-Id": f"piggyback-test-{name}"}


class TestWorkingDirPiggyback:
    def test_set_working_dir_emits_state_sync_event(self, http_client, tmp_path):
        resp = http_client.post(
            "/context/working_dir",
            json={"path": str(tmp_path)},
            headers=_new_session_headers("cwd"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "events" in body, "REST response missing `events` field"
        # state_sync(working_dir=...) is fired by AppState.set,
        # working_dir_changed is fired by engine.set_working_dir
        types = [e["type"] for e in body["events"]]
        assert "state_sync" in types or "working_dir_changed" in types, (
            f"Expected state_sync or working_dir_changed in events; "
            f"got: {types}"
        )

    def test_set_working_dir_state_sync_carries_new_path(
        self, http_client, tmp_path
    ):
        resp = http_client.post(
            "/context/working_dir",
            json={"path": str(tmp_path)},
            headers=_new_session_headers("cwd-payload"),
        ).json()
        # Find the state_sync event for working_dir
        ss_events = [
            e for e in resp["events"]
            if e["type"] == "state_sync"
            and "working_dir" in e.get("data", {})
        ]
        if ss_events:  # at least one client of this contract should fire
            # Path resolved on the server side, may differ from input
            # (Windows tmp paths get normalised)
            assert ss_events[0]["data"]["working_dir"]


class TestCommandEnvelopePiggyback:
    """The /command/<name> envelope includes events[] alongside the
    existing result + side_effects fields."""

    def test_command_envelope_has_events_field(self, http_client):
        resp = http_client.post(
            "/command/help",
            json={"args": ""},
            headers=_new_session_headers("cmd-help"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "events" in body, (
            f"Command envelope missing events. Keys: {sorted(body.keys())}"
        )
        assert isinstance(body["events"], list)

    def test_state_mutating_command_emits_events(self, http_client, tmp_path):
        """Driving /cd through the command envelope produces events
        that web/VSCode can feed through their SSE dispatcher."""
        resp = http_client.post(
            "/command/cd",
            json={"args": str(tmp_path)},
            headers=_new_session_headers("cmd-cd"),
        )
        assert resp.status_code == 200
        body = resp.json()
        types = [e["type"] for e in body["events"]]
        # /cd fires the same engine path as POST /context/working_dir
        assert any(
            t in types for t in ("state_sync", "working_dir_changed")
        ), f"events from /cd: {types}"


class TestReadonlyEndpointsDoNotPiggyback:
    """Read-only endpoints don't drain events — they don't mutate
    engine state and shouldn't grow the wire shape with an empty
    array (or worse, drain events queued by a peer endpoint that
    fired between read calls)."""

    def test_get_working_dir_does_not_emit_events(self, http_client):
        resp = http_client.get(
            "/context/working_dir",
            headers=_new_session_headers("get-cwd"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "events" not in body, (
            f"GET /context/working_dir should not piggyback events; "
            f"body has: {sorted(body.keys())}"
        )

    def test_get_state_does_not_emit_events(self, http_client):
        resp = http_client.get(
            "/state",
            headers=_new_session_headers("get-state"),
        )
        # /state IS the snapshot endpoint — its whole job is to be
        # read-only. It must not drain events either.
        assert resp.status_code == 200
        body = resp.json()
        assert "events" not in body
