"""The test suite cannot reach the developer's real `~/.ppxai`.

Debt Item 78, and the fourth incident of the class recorded in
`docs/lessons/module-level-home-paths-leak-into-user-state.md`.

**What was happening, measured 2026-09-21:**
`~/.ppxai/sessions/checkpoints/` held ~14,900 entries, all but two EMPTY
`session_<YYYYMMDD_HHMMSS>` directories, grouped on the days the suite ran.
A full run added ~100. `~/.ppxai/.preview-cache/` gained directories with
real PNG content. `runs/`, `sessions/` and `logs/` grew too.

**Why no teardown could have fixed it.** The checkpoint directory is not a
fixture's to clean: `FileCheckpointBackend.__init__` (`ppxai/checkpoint.py`)
does `Path(SESSIONS_DIR) / "checkpoints" / session_id` followed by an eager
`mkdir`, so it is a CONSTRUCTOR side effect of ordinary session creation.
Nothing registered it, nothing owned it, and deleting from a developer's live
data directory as a test side effect would be the wrong repair anyway. The
only correct fix is that the suite never reaches the real home.

**The two halves of the hazard, and why one guard covers both.**

  * *Import-time constants* — `PPXAI_HOME`/`SESSIONS_DIR`
    (`config/loader.py:32-36`), `SESSION_STATE_FILE`
    (`engine/session.py:153`), `_PREVIEW_CACHE_ROOT`
    (`server/routes/files.py:48`), `HINT_TEMPLATES_FILE`,
    `_DEFAULT_STAGING_DIR`, `PREVIEW_LOGS_DIR` — plus every module that
    imported one BY NAME and holds its own binding (`ppxai/checkpoint.py:25`
    does `from .config import SESSIONS_DIR`), so patching the defining module
    alone leaves the importer aimed at the real home.
  * *Call-time `Path.home()`* — `SessionManager.__init__`'s default
    `sessions_dir`/`exports_dir` (`engine/session.py:315-317`), the logger's
    `~/.ppxai/logs` (`common/logger.py:135`), `usage.py`, `usage_events.py`,
    `server/routes/static.py`, `engine/bootstrap.py:708`. Nothing is bound,
    so no amount of attribute patching sees these.

`tests/conftest.py::_redirect_home_to_tmp` moves `HOME` itself, in
`pytest_configure`, BEFORE the first ppxai import — which is the one moment at
which moving `HOME` works (CLAUDE.md's "monkeypatch HOME does NOT work" note
is about doing it *after* a constant has already been resolved). This file is
what makes that guard loud, the way `tests/test_config_source_is_pinned.py`
does for Item 69: without it the redirect is itself unverified state that a
refactor could silently drop, and the leak would resume with nothing to say so.

**Mutation-verified.** Removing the redirect — i.e. leaving `HOME` alone —
fails `test_no_loaded_ppxai_module_points_into_the_real_home` with
`ppxai.checkpoint.SESSIONS_DIR` and its siblings named, and
`test_a_server_session_aims_its_checkpoints_at_the_throwaway_home` with the
real directory the backend was aimed at. Evidence is in the Item 78 report.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import ppxai.checkpoint as checkpoint_module
import ppxai.config.loader as loader
import ppxai.engine.session as session_module
from tests.conftest import (
    FAKE_HOME,
    REAL_HOME,
    REAL_PPXAI_HOME,
    ppxai_paths_still_in_the_real_ppxai_home,
)

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import ppxai.server.http as http_module  # noqa: E402

#: Module attributes allowed to keep pointing into the developer's REAL home.
#:
#: Empty ON PURPOSE. A row here is a claim that the path is READ-ONLY in every
#: code path a test can reach, which is a hard claim to keep true — the
#: checkpoint directory looked read-only too until someone read the
#: constructor. `test_no_stale_exemptions` deletes the escape hatch for a row
#: whose attribute no longer points into the real home, so the list cannot rot
#: into a list of things nobody checks any more.
REAL_HOME_EXEMPTIONS: dict[str, str] = {}

#: The constants the Item 78 measurement actually caught writing. Named
#: explicitly as well as swept, so a reader sees WHAT leaked, and so a
#: rename that removes one from the sweep's reach fails here rather than
#: quietly shrinking the swept set to nothing.
#:
#: `ppxai.checkpoint.SESSIONS_DIR` is on the list because it is a SEPARATE
#: binding: `ppxai/checkpoint.py:25` does `from .config import SESSIONS_DIR`,
#: so patching the defining module alone would leave this one aimed at the
#: real home — the by-name-importer half of the lesson.
NAMED_CONSTANTS = (
    (loader, "PPXAI_HOME"),
    (loader, "SESSIONS_DIR"),
    (loader, "EXPORTS_DIR"),
    (loader, "USAGE_FILE"),
    (checkpoint_module, "SESSIONS_DIR"),
)

#: Constants an autouse fixture deliberately aims at pytest's own tmp tree
#: rather than at the throwaway home. They must still be out of the real
#: `~/.ppxai` — that is what `test_named_constant_is_out_of_the_real_ppxai_home`
#: checks — but "inside FAKE_HOME" is the wrong assertion for them.
ELSEWHERE_IN_TMP = ((session_module, "SESSION_STATE_FILE"),)

ALL_NAMED = NAMED_CONSTANTS + ELSEWHERE_IN_TMP


def checkpoint_names(sessions_dir: Path) -> set[str]:
    """Entry names directly under `<sessions_dir>/checkpoints`, or empty."""
    root = Path(sessions_dir) / "checkpoints"
    if not root.is_dir():
        return set()
    return {entry.name for entry in root.iterdir()}


class TestTheRedirectIsInstalled:
    def test_home_is_not_the_developers_home(self):
        assert FAKE_HOME is not None, "conftest never redirected HOME"
        assert Path.home() != REAL_HOME
        assert Path.home() == FAKE_HOME
        assert os.environ["HOME"] == str(FAKE_HOME)

    def test_home_resolves_to_itself(self):
        """`Path.home()` and `Path.home().resolve()` must be the same string.

        On macOS `tempfile` hands back `/var/folders/…`, whose real path is
        `/private/var/folders/…`. Tests that compare a production value
        against `Path.home().resolve()` (tests/test_tui.py:472) would fail on
        the symlink alone, which would look like a bug in the code under test.
        """
        assert Path.home().resolve() == Path.home()

    def test_no_ppxai_module_was_imported_before_the_redirect(self, pytestconfig):
        """The ordering premise the whole mechanism rests on.

        `_redirect_home_to_tmp()` only reaches the import-time constants
        because nothing under `ppxai.` had been imported when it ran. A future
        plugin or a top-level `import ppxai` in a conftest would break that
        silently — the redirect would half-apply and the leak would come back.
        """
        preimported = getattr(pytestconfig, "_ppxai_preimported", None)
        assert preimported == [], (
            "ppxai module(s) were imported BEFORE tests/conftest.py redirected "
            "HOME, so their module-level Path.home() constants still name the "
            "developer's real home: " + ", ".join(preimported or []) + "\n"
            "Move the offending import out of collection-time code (a plugin, "
            "or a top-level `import ppxai` in a conftest)."
        )

    def test_nothing_had_to_be_rebound_after_the_fact(self, pytestconfig):
        """`rebind_home_derived_paths()` is the belt, not the braces.

        It exists so a stray real-home binding is corrected rather than
        written through, but it should never have work to do. If it does, the
        redirect above is no longer doing its job and the correction is
        racing whatever imported the module.
        """
        rebound = getattr(pytestconfig, "_ppxai_rebound", None)
        assert rebound == [], (
            "the HOME redirect missed these and they had to be rebound after "
            "the fact: " + ", ".join(rebound or [])
        )


class TestNoLoadedModulePointsIntoTheRealHome:
    def test_no_loaded_ppxai_module_points_into_the_real_home(self):
        offenders = {
            name: path
            for name, path in ppxai_paths_still_in_the_real_ppxai_home().items()
            if name not in REAL_HOME_EXEMPTIONS
        }
        assert not offenders, (
            "these loaded ppxai module attributes still name a path inside the "
            "developer's real home, so a test that writes through one mutates "
            "their data directory (Debt Item 78):\n"
            + "\n".join(f"  {name} -> {path}" for name, path in sorted(offenders.items()))
            + "\n\nFix: the constant must resolve from Path.home() (or an "
            "explicitly injected root), not from a captured literal — "
            "tests/conftest.py moves HOME before the first ppxai import, so "
            "anything resolved the normal way lands in the throwaway home."
        )

    def test_no_stale_exemptions(self):
        live = ppxai_paths_still_in_the_real_ppxai_home()
        stale = sorted(set(REAL_HOME_EXEMPTIONS) - set(live))
        assert not stale, (
            "REAL_HOME_EXEMPTIONS names attribute(s) that no longer point into "
            "the real home — delete the row(s): " + ", ".join(stale)
        )

    @pytest.mark.parametrize(
        "module,attr",
        ALL_NAMED,
        ids=[f"{m.__name__}.{a}" for m, a in ALL_NAMED],
    )
    def test_named_constant_is_out_of_the_real_ppxai_home(self, module, attr):
        value = getattr(module, attr)
        assert isinstance(value, Path), f"{module.__name__}.{attr} is not a Path"
        assert REAL_PPXAI_HOME not in value.parents and value != REAL_PPXAI_HOME, (
            f"{module.__name__}.{attr} = {value}, inside the developer's real "
            f"{REAL_PPXAI_HOME}"
        )

    @pytest.mark.parametrize(
        "module,attr",
        NAMED_CONSTANTS,
        ids=[f"{m.__name__}.{a}" for m, a in NAMED_CONSTANTS],
    )
    def test_named_constant_lives_in_the_throwaway_home(self, module, attr):
        value = getattr(module, attr)
        assert FAKE_HOME in value.parents or value == FAKE_HOME, (
            f"{module.__name__}.{attr} = {value}, which is not inside the "
            f"throwaway home {FAKE_HOME}"
        )

    def test_the_scanner_is_not_vacuous(self):
        """POSITIVE CONTROL: plant a real-home Path and see the sweep find it.

        Without this, an empty result is indistinguishable from a scanner that
        walks the wrong namespace and finds nothing anywhere — the exact shape
        of a tripwire that passes while the bug is live.
        """
        planted = REAL_PPXAI_HOME / "planted-by-test-home-hermeticity"
        sentinel = "_item78_planted_sentinel"
        setattr(loader, sentinel, planted)
        try:
            found = ppxai_paths_still_in_the_real_ppxai_home()
        finally:
            delattr(loader, sentinel)
        assert found.get(f"ppxai.config.loader.{sentinel}") == planted, (
            "the real-home scanner did not see a Path planted directly on "
            "ppxai.config.loader — it is not measuring what it claims to"
        )
        assert sentinel not in vars(loader), "positive control leaked its sentinel"


class TestOrdinarySessionCreationStaysOutOfTheRealHome:
    """The behavioural half: the leak as it actually happened.

    `tests/test_command_roster_endpoint.py` added **9** checkpoint directories
    to the real home per run, and it never mentions checkpoints — a server
    session is created the ordinary way and, before the Item 78 fix,
    `FileCheckpointBackend.__init__` mkdir'd on construction.

    Both halves are asserted here because either alone can pass while the bug
    is live: "the real directory did not grow" is also true if nothing ran at
    all, and "the backend was pointed at tmp" is also true if it was never
    constructed. So the test spies on the constructor, requires it to have
    been reached, requires every instance to be aimed at the throwaway home,
    and then drives a real snapshot through one so the directory that USED to
    appear in `~/.ppxai` is observed appearing in tmp instead.
    """

    def test_a_server_session_aims_its_checkpoints_at_the_throwaway_home(
        self, monkeypatch
    ):
        real_before = checkpoint_names(REAL_PPXAI_HOME / "sessions")
        built: list[checkpoint_module.FileCheckpointBackend] = []
        original_init = checkpoint_module.FileCheckpointBackend.__init__

        def spy(self, working_dir, session_id):
            original_init(self, working_dir, session_id)
            built.append(self)

        monkeypatch.setattr(
            checkpoint_module.FileCheckpointBackend, "__init__", spy
        )

        with TestClient(http_module.app, raise_server_exceptions=False) as client:
            response = client.get("/commands")
            assert response.status_code == 200, response.text

        assert built, (
            "no FileCheckpointBackend was constructed, so this test no longer "
            "exercises the path that leaked — find what changed in server "
            "session creation and drive it again"
        )
        for backend in built:
            assert FAKE_HOME in backend.checkpoint_dir.parents, (
                f"a server session aimed its checkpoint directory at "
                f"{backend.checkpoint_dir}, outside the throwaway home "
                f"{FAKE_HOME}"
            )
            assert not backend.checkpoint_dir.exists(), (
                f"constructing the backend created {backend.checkpoint_dir} — "
                "the eager mkdir is back (Item 78, lazy-mkdir half)"
            )

        # Deliberately NOT a count comparison on the real directory: a real
        # ppxai app running on this host may legitimately create one while the
        # suite runs. The claim is narrower and exact — no name this test
        # produced appeared over there.
        real_after = checkpoint_names(REAL_PPXAI_HOME / "sessions")
        ours = {backend.checkpoint_dir.name for backend in built}
        collided = ours & (real_after - real_before)
        assert not collided, (
            "checkpoint director(ies) for session(s) created by this test "
            "appeared in the developer's real "
            f"{REAL_PPXAI_HOME / 'sessions' / 'checkpoints'}: "
            + ", ".join(sorted(collided))
        )

    def test_a_real_snapshot_materialises_in_the_throwaway_home(self, tmp_path):
        """And the redirected location does receive the directory when used."""
        real_before = checkpoint_names(REAL_PPXAI_HOME / "sessions")

        working_dir = tmp_path / "project"          # no .git -> file backend
        working_dir.mkdir()
        session_id = "item78-hermeticity-probe"
        manager = checkpoint_module.CheckpointManager(
            str(working_dir), session_id=session_id
        )
        assert manager.get_backend_name() == "file", (
            "expected the file backend; a .git appeared inside the tmp working "
            "directory and the git backend took over"
        )

        edited = working_dir / "edited.txt"
        edited.write_text("before\n", encoding="utf-8")
        manager.register_file(edited)
        checkpoint_id = manager.create_checkpoint("item 78 probe")
        assert checkpoint_id

        landed = loader.SESSIONS_DIR / "checkpoints" / session_id
        assert FAKE_HOME in landed.parents
        assert (landed / checkpoint_id / "edited.txt").is_file()

        real_after = checkpoint_names(REAL_PPXAI_HOME / "sessions")
        assert session_id not in (real_after - real_before), (
            f"the snapshot for {session_id} was written into the developer's "
            f"real {REAL_PPXAI_HOME / 'sessions' / 'checkpoints'}"
        )
