"""ADR 0018 fence: runs know their conversation; a result merges once.

The `tai` terminal client builds on exactly this surface, so a failure here
means a DELIBERATE CONTRACT BREAK for the tai client — not a test to quietly
update. `/v1/agent/*` stays officially unsealed; ONLY the fields and shapes
pinned below are promised:

- `session_id` (the CONVERSATION name, never the `X-Session-Id` slot) and
  `merged_at` on `RunMetaResponse`;
- `GET /v1/agent/runs?session=<name>` and `?status=<status>` (unknown → 400);
- `POST /sessions/merge-run-result` 409s with structured details:
  `{code: "session_mismatch", message, run_session_id}` and
  `{code: "already_merged", message, merged_at}`.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ppxai.server.state as state
from ppxai.config import execution as exec_cfg
from ppxai.engine import task_authorizer as authz
from ppxai.engine import task_backend
from ppxai.engine.agent_runs import (
    RUN_STATUSES,
    AgentRunRegistry,
    FilesystemAgentRunStore,
    RunMeta,
)
from ppxai.engine.task_authorizer import AuthorizedTask
from ppxai.engine.task_backend import InProcessTaskBackend
from ppxai.server.routes import agent_v1
from ppxai.server.routes import sessions as sessions_route
from ppxai.server.routes.agent_v1 import RunMetaResponse

CONVO_A = "session_20261102_100000"
CONVO_B = "session_20261102_110000"


class _Convo:
    def __init__(self, name):
        self.session_name = name
        self.messages = []

    def add_message(self, m):
        self.messages.append(m)


@pytest.fixture
def reg(tmp_path, monkeypatch):
    r = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(state, "_agent_run_registry", r)
    monkeypatch.setattr(exec_cfg, "get_execution_collect", lambda: "yes")
    return r


@pytest.fixture
def merge_client(reg):
    """Merge + runs routes with a fixed active conversation (CONVO_A)."""
    convo = _Convo(CONVO_A)
    engine = SimpleNamespace(session=convo, drain_events=lambda: [])
    app = FastAPI()
    app.include_router(sessions_route.router)
    app.include_router(agent_v1.router)
    app.dependency_overrides[sessions_route.get_session] = (
        lambda: SimpleNamespace(engine=engine)
    )
    return TestClient(app), convo


def _done(reg, session_id=None, result="the answer"):
    m = reg.start_run("t", provider="p", model="m", session_id=session_id)
    return reg.finish_run(m, status="completed", result=result)


# ── the promised surface ────────────────────────────────────────────────────


def test_response_exposes_session_id_and_merged_at():
    assert "session_id" in RunMetaResponse.model_fields
    assert "merged_at" in RunMetaResponse.model_fields
    m = RunMeta(run_id="run_x", task="t", session_id=CONVO_A, merged_at=12.5)
    out = RunMetaResponse.from_meta(m)
    assert out.session_id == CONVO_A and out.merged_at == 12.5


def test_merge_409_shapes_are_pinned(reg, merge_client):
    c, _convo = merge_client
    other = _done(reg, session_id=CONVO_B)
    r = c.post("/sessions/merge-run-result", json={"run_id": other.run_id})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert set(d) == {"code", "message", "run_session_id"}
    assert d["code"] == "session_mismatch" and d["run_session_id"] == CONVO_B
    assert CONVO_B in d["message"]

    mine = _done(reg, session_id=CONVO_A)
    ok = c.post("/sessions/merge-run-result", json={"run_id": mine.run_id})
    assert ok.status_code == 200
    r = c.post("/sessions/merge-run-result", json={"run_id": mine.run_id})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert set(d) == {"code", "message", "merged_at"}
    assert d["code"] == "already_merged" and isinstance(d["merged_at"], float)


def test_filters_session_status_and_unknown_status_400(reg, merge_client):
    c, _convo = merge_client
    a = _done(reg, session_id=CONVO_A)
    b = _done(reg, session_id=CONVO_B)
    pending = reg.start_run("t2", session_id=CONVO_A)

    def ids(q):
        r = c.get(f"/v1/agent/runs{q}")
        assert r.status_code == 200, r.text
        return {x["run_id"] for x in r.json()["runs"]}

    assert ids(f"?session={CONVO_A}") == {a.run_id, pending.run_id}
    assert ids(f"?session={CONVO_B}") == {b.run_id}
    assert ids("?status=pending") == {pending.run_id}
    assert ids("?status=completed") == {a.run_id, b.run_id}
    assert ids(f"?session={CONVO_A}&status=completed&kind=task") == {a.run_id}
    assert c.get("/v1/agent/runs?status=bogus").status_code == 400
    for s in RUN_STATUSES:
        assert c.get(f"/v1/agent/runs?status={s}").status_code == 200


# ── stamping ────────────────────────────────────────────────────────────────


def test_http_launch_stamps_the_conversation_not_the_slot(reg, monkeypatch):
    real_cfg = exec_cfg.get_execution_task_config
    monkeypatch.setattr(authz, "validate_provider_or_error", lambda name: None)
    monkeypatch.setattr(
        exec_cfg, "get_execution_task_config",
        lambda: {**real_cfg(), "enabled": True},
    )

    def stub(registry, **kw):
        async def _r(m):
            return "done"
        return _r

    monkeypatch.setattr(agent_v1, "build_task_runner", stub)
    seen = []

    async def fake_find(sid):
        seen.append(sid)
        if sid != "slot-1":
            return None  # unknown slot: the lookup never creates one
        return SimpleNamespace(session=_Convo(CONVO_A))

    monkeypatch.setattr(agent_v1, "find_session_engine", fake_find)
    app = FastAPI()
    app.include_router(agent_v1.router)
    c = TestClient(app)
    body = {"task": "do", "tools": ["read_file"], "provider": "p", "model": "m"}
    r = c.post("/v1/agent/task", json=body, headers={"X-Session-Id": "slot-1"})
    assert r.status_code == 200, r.text
    meta = reg.get_run(r.json()["run_id"])
    assert meta.session_id == CONVO_A and meta.session_id != "slot-1"
    # A raw /v1 call with no conversation context gets None.
    r = c.post("/v1/agent/task", json=body)
    assert reg.get_run(r.json()["run_id"]).session_id is None
    # An unknown slot id is None too, not a freshly created engine's name.
    r = c.post("/v1/agent/task", json=body, headers={"X-Session-Id": "nope"})
    assert r.status_code == 200, r.text
    assert reg.get_run(r.json()["run_id"]).session_id is None
    assert seen == ["slot-1", "nope"]


def test_there_is_no_client_supplied_body_field():
    for model in (agent_v1.AgentRunRequest, agent_v1.AgentTaskRequest):
        assert "session_id" not in model.model_fields


async def _noop(_meta):
    return "ok"


@pytest.mark.asyncio
async def test_in_process_launch_stamps_the_active_conversation(reg, monkeypatch):
    convo = _Convo(CONVO_A)
    monkeypatch.setattr(task_backend, "build_task_runner", lambda *a, **k: _noop)
    auth = AuthorizedTask(
        task="x", tools=[], provider="p", model="m", system=None, budget={},
        network=[], read_roots=[], workdir=None, workdir_ignored=False,
        enrichment=False, enrichment_layer=None, tools_layer=None, stripped=[],
    )
    b = InProcessTaskBackend(reg, session_provider=lambda: convo)
    assert b.launch(auth).session_id == CONVO_A
    assert InProcessTaskBackend(reg).launch(auth).session_id is None


def test_sub_agents_inherit_the_parents_conversation(reg):
    parent = reg.start_run("p", session_id=CONVO_A)
    child = reg.start_run("c", parent_run_id=parent.run_id)
    assert child.session_id == CONVO_A
    assert reg.start_run("c", parent_run_id="run_missing").session_id is None


def test_old_metas_without_the_fields_still_load(tmp_path):
    store = FilesystemAgentRunStore(tmp_path / "runs")
    slot = tmp_path / "runs" / "run_old" / "agent-0"
    slot.mkdir(parents=True)
    (slot / "meta.json").write_text(
        json.dumps({"run_id": "run_old", "task": "t", "status": "completed"})
    )
    m = store.load_meta("run_old")
    assert m.session_id is None and m.merged_at is None


# ── merge guard: HTTP ───────────────────────────────────────────────────────


def test_mismatch_refuses_and_appends_nothing(reg, merge_client):
    c, convo = merge_client
    m = _done(reg, session_id=CONVO_B)
    r = c.post("/sessions/merge-run-result", json={"run_id": m.run_id})
    assert r.status_code == 409
    assert convo.messages == []
    assert reg.get_run(m.run_id).merged_at is None


def test_double_merge_refused_and_appended_once(reg, merge_client):
    c, convo = merge_client
    m = _done(reg, session_id=CONVO_A)
    assert c.post("/sessions/merge-run-result", json={"run_id": m.run_id}).status_code == 200
    assert reg.get_run(m.run_id).merged_at is not None
    assert c.post("/sessions/merge-run-result", json={"run_id": m.run_id}).status_code == 409
    assert len(convo.messages) == 2


def test_run_without_a_conversation_merges_into_active_once(reg, merge_client):
    c, convo = merge_client
    m = _done(reg, session_id=None)
    assert c.post("/sessions/merge-run-result", json={"run_id": m.run_id}).status_code == 200
    assert len(convo.messages) == 2
    r = c.post("/sessions/merge-run-result", json={"run_id": m.run_id})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_merged"


def test_existing_409_stays_a_plain_string(reg, merge_client):
    c, _convo = merge_client
    m = reg.start_run("t")  # no result yet
    r = c.post("/sessions/merge-run-result", json={"run_id": m.run_id})
    assert r.status_code == 409 and isinstance(r.json()["detail"], str)


# ── merge guard: in-process (TUI) path ──────────────────────────────────────


@pytest.fixture
def tui_backend(reg):
    convo = _Convo(CONVO_A)
    return InProcessTaskBackend(reg, session_provider=lambda: convo), convo


def test_tui_mismatch_names_the_conversation(reg, tui_backend):
    b, convo = tui_backend
    m = _done(reg, session_id=CONVO_B)
    ok, msg = b.merge_result(m.run_id)
    assert ok is False and CONVO_B in msg
    assert convo.messages == []


def test_tui_second_merge_is_refused(reg, tui_backend):
    b, convo = tui_backend
    m = _done(reg, session_id=CONVO_A)
    assert b.merge_result(m.run_id)[0] is True
    ok, msg = b.merge_result(m.run_id)
    assert ok is False and "already" in msg
    assert len(convo.messages) == 2


def test_tui_collect_reports_the_refusal_without_losing_the_collect(reg, tui_backend):
    b, convo = tui_backend
    m = reg.start_run("t", session_id=CONVO_B, hold_result=True)
    reg.finish_run(m, status="completed_pending_ack", result="r")
    ok, msg = b.collect(m.run_id)
    assert ok is True and "not merged" in msg and CONVO_B in msg
    assert convo.messages == []
