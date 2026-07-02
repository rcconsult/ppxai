"""Per-run filesystem confinement (ADR 0003 §9 sandbox seal) — build plan T2.

The in-process realization of `tools.agent.sandbox`: read-class tools
(`read_file`, `list_directory`, `search_files`) may reach ONLY the configured
read roots; write-class tools (`write_file`, `apply_patch`, and the other
editors) may write ONLY the per-run workdir. An off-scope path is refused with a
model-readable denial + a `path_denied` event, mirroring the AC-1 `tool_denied`
and AC-2 `network_policy_denied` chokepoints already in `ScopedToolManager`.

This is a path-prefix jail — best-effort under threat model A (trusted
operator), NOT an OS boundary. `enforcement:"container"` (tier-d) is the hard
boundary; the config schema anticipates it, this module realizes the soft tier.

Resolution matches the filesystem tools exactly (`builtin/filesystem.py`,
`builtin/editor.py`): a relative path resolves against the run's working dir
(the workdir), `~` expands, and — unless `follow_symlinks` is set — the real
(symlink-resolved) target is checked, so a symlink INSIDE a permitted root that
points OUT is caught.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

# tool name -> (mode, path-kwarg). mode "read" checks the read scope; "write"
# checks the per-run workdir. Keys are the exact builtin tool names + their
# path parameter (verified against builtin/filesystem.py + builtin/editor.py).
# tool name -> (mode, path-kwarg, path_required). `path_required` is False only
# for the tools whose path legitimately DEFAULTS to the working dir (".") when
# omitted; for every other tool an absent canonical path kwarg means the call is
# malformed (or the path was passed under an alias the tool doesn't accept), and
# the jail fails CLOSED rather than checking the "." default (which would let the
# call slip through to the base — Codex/coder review, alias completeness).
_PATH_TOOLS: dict = {
    "read_file":             ("read",  "filepath",  True),
    "list_directory":        ("read",  "path",      False),
    "search_files":          ("read",  "directory", False),
    "set_working_directory": ("read",  "path",      True),
    "write_file":            ("write", "file_path", True),
    "apply_patch":           ("write", "file_path", True),
    "replace_block":         ("write", "file_path", True),
    "insert_text":           ("write", "file_path", True),
    "delete_lines":          ("write", "file_path", True),
}

# Default path when a read tool's path kwarg is omitted — the tools default to
# "." (the working dir), so the jail must check that same default.
_DEFAULT_READ_PATH = "."


def is_path_tool(name: str) -> bool:
    """True if this tool takes a filesystem path the jail must confine."""
    return name in _PATH_TOOLS


@dataclass(frozen=True)
class Allow:
    root: str


@dataclass(frozen=True)
class Deny:
    reason: str


Decision = Union[Allow, Deny]


@dataclass(frozen=True)
class PathDecision:
    """Chokepoint verdict + the audit fields the `path_denied` event carries."""
    allowed: bool
    mode: str          # "read" | "write" | "" (non-path tool)
    target: str        # the resolved absolute path that was checked
    reason: str        # empty on allow
    root: Optional[str] = None  # the read root that matched (allow only)


def _norm(p: str) -> str:
    """Canonical absolute path with symlinks + ~ resolved (for roots)."""
    return os.path.realpath(os.path.expanduser(str(p)))


def _within(target: str, root: str) -> bool:
    """True if `target` is `root` or lives under it (both absolute)."""
    try:
        return os.path.commonpath([target, root]) == root
    except ValueError:
        return False  # different drives / mixed abs+rel → not within


class FilesystemPolicy:
    """Per-run read/write path confinement. Deny-by-default, deny-wins.

    Args:
        read_roots: dirs the run may READ from (read_file/list_directory/
            search_files). The workdir is added automatically (a run can read
            what it writes).
        workdir: the ONLY dir the run may WRITE to (write_file/apply_patch/…).
            None = writes are refused entirely.
        deny: glob patterns that override any allow (e.g. ``**/.env``).
        follow_symlinks: when False (default) the symlink-resolved real target
            is checked, so a link inside a root pointing out is refused.
        base: dir that relative paths resolve against — the run working dir.
            Defaults to the process cwd (matches the tools' own fallback).
    """

    def __init__(
        self,
        *,
        read_roots: Optional[List[str]] = None,
        workdir: Optional[str] = None,
        deny: Tuple[str, ...] = (),
        follow_symlinks: bool = False,
        base: Optional[str] = None,
    ) -> None:
        self._workdir = _norm(workdir) if workdir else None
        roots = [r for r in (read_roots or []) if r]
        if workdir:
            roots.append(workdir)  # readable-what-you-write
        self._read_roots = [_norm(r) for r in roots]
        self._deny = [os.path.expanduser(d) for d in (deny or [])]
        self._follow = bool(follow_symlinks)
        self._base = _norm(base) if base else None

    def _resolve(self, raw: str) -> str:
        """Resolve a tool path arg the way the filesystem tools do."""
        p = Path(os.path.expanduser(str(raw)))
        if not p.is_absolute():
            base = self._base or os.getcwd()
            p = Path(base) / p
        if self._follow:
            return os.path.normpath(str(p))
        return os.path.realpath(str(p))

    def _denied_by_glob(self, target: str) -> Optional[str]:
        # A deny pattern is matched three ways so the intuitive forms work:
        #   1. Against the full absolute path — for anchored globs
        #      (`/abs/path`, `**/.env`, `**/secrets/**`).
        #   2. Against `<pattern>/*` — so a dir pattern also denies its contents.
        #   3. For a SEPARATOR-FREE pattern (a bare name like `.env`, `.git`,
        #      `secrets`, `node_modules`) — against EVERY path COMPONENT, so it
        #      denies that file anywhere AND anything under a dir of that name.
        # Without (3), a bare `.env` silently matched nothing (fnmatch compares
        # the whole path), so only `**/.env` worked — an easy config footgun.
        # Over-denying is the fail-safe direction (deny wins), so component
        # matching a bare name broadly is the correct bias.
        parts = [p for p in target.split(os.sep) if p]
        for d in self._deny:
            if fnmatch.fnmatch(target, d) or fnmatch.fnmatch(target, d.rstrip("/") + "/*"):
                return d
            if "/" not in d and os.sep not in d and any(fnmatch.fnmatch(p, d) for p in parts):
                return d
        return None

    def check(self, mode: str, raw: str) -> Decision:
        """Allow/Deny a single (mode, path). Deny-wins, fail-closed."""
        target = self._resolve(raw)
        hit = self._denied_by_glob(target)
        if hit is not None:
            return Deny(f"path matches deny rule {hit!r}")
        if mode == "write":
            if self._workdir and _within(target, self._workdir):
                return Allow(self._workdir)
            return Deny("writes are confined to the run workdir")
        # read
        for root in self._read_roots:
            if _within(target, root):
                return Allow(root)
        return Deny("path is outside the run read scope")

    def authorize(self, name: str, kwargs: dict) -> PathDecision:
        """Chokepoint entry: resolve + check the path tool's target."""
        spec = _PATH_TOOLS.get(name)
        if spec is None:
            return PathDecision(True, "", "", "")
        mode, kw, required = spec
        raw = kwargs.get(kw)
        if not isinstance(raw, str) or not raw.strip():
            if mode == "read" and not required:
                raw = _DEFAULT_READ_PATH   # list_directory/search_files default to "."
            else:
                # A required-path tool (or any write) with no confinable path:
                # the canonical kwarg is absent — either omitted, or the path was
                # passed under an alias the tool doesn't consume. Fail CLOSED
                # (deny at the jail) rather than checking the "." default and
                # letting the call reach the base.
                return PathDecision(False, mode, "", "no confinable path argument")
        target = self._resolve(raw)
        decision = self.check(mode, raw)
        if isinstance(decision, Allow):
            return PathDecision(True, mode, target, "", decision.root)
        return PathDecision(False, mode, target, decision.reason)


def build_filesystem_policy(sandbox: dict, workdir: str) -> FilesystemPolicy:
    """Construct a per-run FilesystemPolicy from the `tools.agent.sandbox` block.

    The read scope is `read_paths.allow` + the configured `skills_dir`/`specs_dir`
    (so a run can always read its skill/spec roots — T4 resolves `--skill` there)
    + the workdir (added by FilesystemPolicy). Relative paths resolve against the
    workdir.
    """
    rp = sandbox.get("read_paths", {}) or {}
    read_roots = list(rp.get("allow", []) or [])
    for key in ("skills_dir", "specs_dir"):
        root = sandbox.get(key)
        if root:
            read_roots.append(root)
    return FilesystemPolicy(
        read_roots=read_roots,
        workdir=workdir,
        deny=tuple(rp.get("deny", []) or []),
        follow_symlinks=bool(rp.get("follow_symlinks", False)),
        base=workdir,
    )
