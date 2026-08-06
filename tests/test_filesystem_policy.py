"""Tests for the T2 filesystem seal — FilesystemPolicy + the ScopedToolManager
path chokepoint (tools.agent.sandbox, enforcement="in_process").

The jail is a path-prefix confinement: read-class tools may reach only the
configured read roots; write-class tools only the per-run workdir. Deny-wins,
fail-closed, boundary-anchored (no sibling over-match), and symlink-escape safe.
"""

from __future__ import annotations

import os

import pytest

from ppxai.config.execution import _normalize_sandbox
from ppxai.engine.agent_scoped_tools import ScopedToolManager
from ppxai.engine.tools.filesystem_policy import (
    Allow,
    Deny,
    FilesystemPolicy,
    build_filesystem_policy,
    is_path_tool,
)


@pytest.fixture
def dirs(tmp_path):
    allowed = tmp_path / "allowed"
    workdir = tmp_path / "run" / "work"
    outside = tmp_path / "outside"
    for d in (allowed, workdir, outside):
        d.mkdir(parents=True)
    return {"allowed": allowed, "workdir": workdir, "outside": outside, "root": tmp_path}


def _pol(dirs, **kw):
    return FilesystemPolicy(
        read_roots=[str(dirs["allowed"])],
        workdir=str(dirs["workdir"]),
        base=str(dirs["workdir"]),
        **kw,
    )


def _require_symlinks(tmp_path):
    """Skip when the host can't create symlinks.

    Windows needs Developer Mode or an elevated process (`os.symlink` raises
    WinError 1314, "A required privilege is not held by the client"). Same
    convention as `TestSessionSymlinkBehavior` in test_session_persistence.py
    — the seal's symlink-escape rule is host-independent, but exercising it
    requires a privilege the CI/dev Windows host may not grant.
    """
    probe = tmp_path / "_symlink_probe"
    try:
        os.symlink(str(tmp_path), str(probe))
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("host cannot create symlinks (Windows needs Developer Mode)")
    else:
        probe.unlink()


# ── read scope ────────────────────────────────────────────────────────────────

class TestReadScope:
    def test_read_within_allow(self, dirs):
        assert isinstance(_pol(dirs).check("read", str(dirs["allowed"] / "x.txt")), Allow)

    def test_read_exact_root(self, dirs):
        assert isinstance(_pol(dirs).check("read", str(dirs["allowed"])), Allow)

    def test_read_outside_denied(self, dirs):
        assert isinstance(_pol(dirs).check("read", "/etc/hosts"), Deny)

    def test_sibling_prefix_not_over_matched(self, dirs):
        # "<root>/allowedX" shares the string prefix of "<root>/allowed" but is
        # NOT within it — must be denied (the boundary bug the jail must avoid).
        sibling = str(dirs["allowed"]) + "X"
        assert isinstance(_pol(dirs).check("read", sibling), Deny)

    def test_workdir_is_readable(self, dirs):
        # a run can read what it writes
        assert isinstance(_pol(dirs).check("read", str(dirs["workdir"] / "o.txt")), Allow)

    def test_dotdot_escape_denied(self, dirs):
        # <allowed>/../outside/secret resolves OUTSIDE the allowed root
        escape = str(dirs["allowed"] / ".." / "outside" / "secret")
        assert isinstance(_pol(dirs).check("read", escape), Deny)


# ── write scope ───────────────────────────────────────────────────────────────

class TestWriteScope:
    def test_write_in_workdir(self, dirs):
        assert isinstance(_pol(dirs).check("write", str(dirs["workdir"] / "out.py")), Allow)

    def test_write_outside_workdir_denied(self, dirs):
        # even inside the READ-allowed dir, writing is refused
        assert isinstance(_pol(dirs).check("write", str(dirs["allowed"] / "x")), Deny)

    def test_write_with_no_workdir_denied(self, dirs):
        pol = FilesystemPolicy(read_roots=[str(dirs["allowed"])], workdir=None)
        assert isinstance(pol.check("write", str(dirs["allowed"] / "x")), Deny)


# ── deny-wins + symlinks ──────────────────────────────────────────────────────

class TestDenyAndSymlinks:
    def test_deny_glob_overrides_allow(self, dirs):
        pol = _pol(dirs, deny=("**/.env",))
        env = dirs["allowed"] / ".env"
        env.write_text("SECRET=1")
        assert isinstance(pol.check("read", str(env)), Deny)

    def test_deny_dir_glob(self, dirs):
        pol = _pol(dirs, deny=("**/secrets",))
        secret = dirs["allowed"] / "secrets" / "key"
        secret.parent.mkdir()
        secret.write_text("k")
        assert isinstance(pol.check("read", str(secret)), Deny)

    def test_bare_name_deny_matches_anywhere(self, dirs):
        # Review fix: a SEPARATOR-FREE pattern like ".env" must deny that file
        # anywhere — not only when written as "**/.env". Previously bare ".env"
        # silently matched nothing (fnmatch compared the whole absolute path).
        pol = _pol(dirs, deny=(".env",))
        top = dirs["allowed"] / ".env"
        nested = dirs["allowed"] / "sub" / ".env"
        nested.parent.mkdir()
        for f in (top, nested):
            f.write_text("SECRET=1")
        assert isinstance(pol.check("read", str(top)), Deny)
        assert isinstance(pol.check("read", str(nested)), Deny)
        # a file that merely CONTAINS the name isn't denied
        ok = dirs["allowed"] / "environment.txt"
        ok.write_text("x")
        assert isinstance(pol.check("read", str(ok)), Allow)

    def test_bare_name_deny_matches_dir_subtree(self, dirs):
        # ".git" / "secrets" as a bare name blocks anything under a dir of that
        # name (component match), not just the dir entry itself.
        pol = _pol(dirs, deny=("secrets",))
        f = dirs["allowed"] / "secrets" / "key"
        f.parent.mkdir()
        f.write_text("k")
        assert isinstance(pol.check("read", str(f)), Deny)              # under the dir
        assert isinstance(pol.check("read", str(dirs["allowed"] / "secrets")), Deny)  # the dir

    def test_symlink_inside_root_pointing_out_is_denied(self, dirs):
        # default follow_symlinks=False → the REAL target is checked, so a link
        # inside the allowed root that points outside is refused.
        _require_symlinks(dirs["root"])
        target = dirs["outside"] / "secret.txt"
        target.write_text("s")
        link = dirs["allowed"] / "link"
        os.symlink(str(target), str(link))
        assert isinstance(_pol(dirs).check("read", str(link)), Deny)

    def test_follow_symlinks_true_allows_logical_path(self, dirs):
        # documents the less-safe mode: the logical path within allow is accepted
        _require_symlinks(dirs["root"])
        target = dirs["outside"] / "secret.txt"
        target.write_text("s")
        link = dirs["allowed"] / "link2"
        os.symlink(str(target), str(link))
        pol = _pol(dirs, follow_symlinks=True)
        assert isinstance(pol.check("read", str(link)), Allow)


# ── relative resolution + authorize() ─────────────────────────────────────────

class TestAuthorize:
    def test_relative_read_resolves_against_workdir_base(self, dirs):
        # a bare "file.txt" resolves under the workdir (base) → readable
        d = _pol(dirs).authorize("read_file", {"filepath": "file.txt"})
        assert d.allowed and d.target == str(dirs["workdir"] / "file.txt")

    def test_read_file_absolute_outside_denied(self, dirs):
        d = _pol(dirs).authorize("read_file", {"filepath": "/etc/passwd"})
        assert not d.allowed and d.mode == "read"

    def test_write_file_outside_workdir_denied(self, dirs):
        d = _pol(dirs).authorize("write_file", {"file_path": str(dirs["allowed"] / "x")})
        assert not d.allowed and d.mode == "write"

    def test_list_directory_default_dot_is_workdir(self, dirs):
        # omitted path → "." → the workdir → allowed
        d = _pol(dirs).authorize("list_directory", {})
        assert d.allowed

    def test_non_path_tool_passes(self, dirs):
        d = _pol(dirs).authorize("web_search", {"query": "x"})
        assert d.allowed and d.mode == ""

    def test_required_path_tool_missing_canonical_is_denied(self, dirs):
        # Fail-closed hardening: a required-path tool whose canonical kwarg is
        # absent (omitted, or a path passed under an unrecognized alias like
        # read_file(path=…)) is denied at the jail, not defaulted to ".".
        pol = _pol(dirs)
        assert not pol.authorize("read_file", {}).allowed
        assert not pol.authorize("read_file", {"path": "/etc/passwd"}).allowed
        assert not pol.authorize("write_file", {}).allowed

    def test_optional_path_tool_missing_defaults_to_workdir(self, dirs):
        # list_directory / search_files legitimately default to the workdir.
        assert _pol(dirs).authorize("list_directory", {}).allowed
        assert _pol(dirs).authorize("search_files", {"pattern": "*.py"}).allowed

    def test_is_path_tool(self):
        assert is_path_tool("read_file") and is_path_tool("apply_patch")
        assert not is_path_tool("web_search")


# ── build_filesystem_policy + config ──────────────────────────────────────────

class TestBuildAndConfig:
    def test_build_includes_skills_and_specs_dirs(self, dirs):
        sandbox = _normalize_sandbox({
            "enforcement": "in_process",
            "read_paths": {"allow": [str(dirs["allowed"])]},
            "skills_dir": str(dirs["root"] / "skills"),
            "specs_dir": str(dirs["root"] / "specs"),
        })
        pol = build_filesystem_policy(sandbox, str(dirs["workdir"]))
        (dirs["root"] / "skills").mkdir()
        assert isinstance(pol.check("read", str(dirs["root"] / "skills" / "s.md")), Allow)
        assert isinstance(pol.check("read", str(dirs["root"] / "specs")), Allow)

    def test_extra_read_paths_mounts_skill_scope(self, dirs):
        # T4: a --skill dir is mounted per-run via extra_read_paths. The skill's
        # references/ becomes readable; a SIBLING outside the mounted dir stays
        # denied (the T4 acceptance signal — scoped mount, not a hole).
        skill = dirs["root"] / "ci-triage"
        (skill / "references").mkdir(parents=True)
        sibling = dirs["root"] / "other-secret"
        sibling.mkdir()
        sandbox = _normalize_sandbox({
            "enforcement": "in_process",
            "read_paths": {"allow": []},   # NO blanket allow — only the mount
        })
        pol = build_filesystem_policy(
            sandbox, str(dirs["workdir"]), extra_read_paths=[str(skill)]
        )
        # inside the mounted skill dir → allowed
        assert isinstance(pol.check("read", str(skill / "references" / "checklist.md")), Allow)
        assert isinstance(pol.check("read", str(skill / "SKILL.md")), Allow)
        # a sibling OUTSIDE the skill dir → denied
        assert isinstance(pol.check("read", str(sibling / "leak.txt")), Deny)

    def test_extra_read_paths_none_is_noop(self, dirs):
        sandbox = _normalize_sandbox({
            "enforcement": "in_process",
            "read_paths": {"allow": [str(dirs["allowed"])]},
        })
        pol = build_filesystem_policy(sandbox, str(dirs["workdir"]), extra_read_paths=None)
        assert isinstance(pol.check("read", str(dirs["allowed"] / "x")), Allow)

    def test_normalize_defaults(self):
        sb = _normalize_sandbox({})
        assert sb["enforcement"] == "off"          # non-breaking default
        assert sb["workdir"]["root"] == "~/.ppxai/runs"
        assert sb["read_paths"]["allow"] == []
        assert sb["read_paths"]["follow_symlinks"] is False
        assert sb["allow_skill_scripts"] is False
        assert sb["container"] == {}


# ── ScopedToolManager integration ─────────────────────────────────────────────

class _FakeBase:
    def __init__(self):
        self.calls = []

    async def execute_tool(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return "ran"


class TestScopedManagerPathChokepoint:
    @pytest.mark.asyncio
    async def test_offscope_read_blocked_and_event_emitted(self, dirs):
        base = _FakeBase()
        events = []
        mgr = ScopedToolManager(
            base, ["read_file"],
            filesystem_policy=_pol(dirs),
            on_path=lambda ok, p: events.append((ok, p)),
        )
        out = await mgr.execute_tool("read_file", filepath="/etc/hosts")
        assert "denied" in out.lower()
        assert base.calls == []                     # the tool NEVER ran
        assert events and events[0][0] is False
        assert events[0][1]["tool"] == "read_file" and events[0][1]["mode"] == "read"

    @pytest.mark.asyncio
    async def test_inscope_read_passes_through(self, dirs):
        base = _FakeBase()
        events = []
        mgr = ScopedToolManager(
            base, ["read_file"],
            filesystem_policy=_pol(dirs),
            on_path=lambda ok, p: events.append((ok, p)),
        )
        out = await mgr.execute_tool("read_file", filepath=str(dirs["allowed"] / "x"))
        assert out == "ran"
        assert base.calls == [("read_file", {"filepath": str(dirs["allowed"] / "x")})]
        assert events == []                         # allowed reads are silent

    @pytest.mark.asyncio
    async def test_no_policy_means_no_confinement(self, dirs):
        # default (unconfigured) — a path tool runs unconfined
        base = _FakeBase()
        mgr = ScopedToolManager(base, ["read_file"])  # no filesystem_policy
        out = await mgr.execute_tool("read_file", filepath="/etc/hosts")
        assert out == "ran" and base.calls


class _AliasBase:
    """Base manager that reuses the REAL ToolManager alias normalization, to
    prove the jail resolves an aliased path arg (Codex sandbox-escape fix)."""
    from ppxai.engine.tools.manager import ToolManager as _TM
    PARAM_ALIAS_GROUPS = _TM.PARAM_ALIAS_GROUPS
    _normalize_params = _TM._normalize_params

    def __init__(self):
        self.calls = []

    def get_tool(self, name):
        from types import SimpleNamespace
        schema = {
            "read_file": {"filepath": {}, "offset": {}},
            "search_files": {"pattern": {}, "directory": {}},
        }.get(name, {})
        return SimpleNamespace(parameters={"properties": schema})

    async def execute_tool(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return "ran"


class TestAliasBypassClosed:
    """The seal must resolve a path passed under an ARGUMENT ALIAS. read_file's
    canonical kwarg is 'filepath'; a model calling read_file(file=…) or
    search_files(path=…) must NOT slip past the jail (which used to check only
    the canonical kwarg, default to '.', and allow — before the base manager
    normalized the alias to the real target)."""

    @pytest.mark.asyncio
    async def test_read_file_alias_to_offscope_is_denied(self, dirs):
        base = _AliasBase()
        mgr = ScopedToolManager(base, ["read_file"], filesystem_policy=_pol(dirs))
        out = await mgr.execute_tool("read_file", file="/etc/passwd")  # 'file' alias
        assert "denied" in out.lower()
        assert base.calls == []            # tool never ran

    @pytest.mark.asyncio
    async def test_search_files_path_alias_to_offscope_is_denied(self, dirs):
        base = _AliasBase()
        mgr = ScopedToolManager(base, ["search_files"], filesystem_policy=_pol(dirs))
        out = await mgr.execute_tool("search_files", path="/etc")  # 'path'→'directory'
        assert "denied" in out.lower()
        assert base.calls == []

    @pytest.mark.asyncio
    async def test_in_scope_alias_read_passes(self, dirs):
        base = _AliasBase()
        mgr = ScopedToolManager(base, ["read_file"], filesystem_policy=_pol(dirs))
        out = await mgr.execute_tool("read_file", file=str(dirs["allowed"] / "x"))
        assert out == "ran"
        # normalized to the canonical kwarg before reaching the tool
        assert base.calls and base.calls[0][1].get("filepath") == str(dirs["allowed"] / "x")

    @pytest.mark.asyncio
    async def test_unrecognized_alias_denied_at_jail_not_base(self, dirs):
        # read_file(path=…): 'path' isn't a read_file arg, so it's NOT a leak
        # (the tool would error on the missing 'filepath') — but the jail must
        # DENY it rather than let it reach the base (fail-closed hardening).
        base = _AliasBase()
        mgr = ScopedToolManager(base, ["read_file"], filesystem_policy=_pol(dirs))
        out = await mgr.execute_tool("read_file", path="/etc/passwd")
        assert "denied" in out.lower()
        assert base.calls == []
