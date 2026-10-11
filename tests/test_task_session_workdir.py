"""`/task` in the TUIs sends the session's folder as the run's workdir.

Debt Item 46 (2026-10-11): the filesystem seal is on by default and confines a
run to its workdir, so a `/task` with no `--work-dir` must carry the session's
folder (as the web and VSCode controllers already do), or it would be jailed in
an empty scratch folder instead of the project.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ppxai.commands import task as task_cmd
from ppxai.engine.task_authorizer import TaskAuthorizationError


class _Engine:
    def __init__(self, wd):
        self._wd = wd

    def get_working_dir(self):
        return self._wd


def _launch(monkeypatch, context, args):
    seen = {}

    def fake_authorize(req, **_kw):
        seen["workdir"] = req.workdir
        raise TaskAuthorizationError(400, "stop here")

    monkeypatch.setattr(task_cmd, "authorize", fake_authorize)
    monkeypatch.setattr(task_cmd, "_has_running_loop", lambda: True)
    task_cmd.handle_task(context, args)
    return seen["workdir"]


def test_no_work_dir_sends_the_session_folder(monkeypatch, tmp_path):
    ctx = SimpleNamespace(engine_client=_Engine(str(tmp_path)))
    assert _launch(monkeypatch, ctx, '"fix the tests" --tools read_file') == str(tmp_path)


def test_explicit_work_dir_wins(monkeypatch, tmp_path):
    ctx = SimpleNamespace(engine_client=_Engine("/somewhere/else"))
    args = f'"fix the tests" --tools read_file --work-dir {tmp_path}'
    assert _launch(monkeypatch, ctx, args) == str(tmp_path)


@pytest.mark.parametrize("ctx", [
    SimpleNamespace(),
    SimpleNamespace(engine_client=None),
    SimpleNamespace(engine_client=_Engine(None)),
])
def test_a_context_without_a_folder_sends_none(monkeypatch, ctx):
    assert _launch(monkeypatch, ctx, '"t" --tools read_file') is None
