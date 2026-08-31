"""Factory for instantiating Wrappers from JSON config entries (v1.18.5).

Resolution rule: `entry["type"]` selects the class. Two types ship today:

- `"probe"` → `ProbeWrapper` (rtk and anything with a dry-run command)
- `"always"` → `AlwaysWrapper` (time, nice, profilers, sandboxers)

There are no privileged "built-in" classes — rtk is just a config entry
with `type: "probe"` that ships in `DEFAULT_SHELL_WRAPPERS`. Adding a new
wrapper that fits one of the two types requires zero Python.

If a wrapper genuinely needs custom Python (rare — example: an IPC
wrapper with a non-stdout protocol), drop it in
`ppxai/engine/tools/wrappers/<name>.py` as a `Wrapper` subclass and
register the type in `_TYPE_REGISTRY`.
"""

from __future__ import annotations

import importlib.resources
import logging
import os
from pathlib import Path
from typing import Any

from .base import AlwaysWrapper, ProbeWrapper, Wrapper

logger = logging.getLogger(__name__)


_TYPE_REGISTRY: dict[str, type[Wrapper]] = {
    "probe": ProbeWrapper,
    "always": AlwaysWrapper,
}


class WrapperConfigError(ValueError):
    """Raised on a malformed wrapper config entry."""


def make_wrapper(entry: dict[str, Any]) -> Wrapper:
    """Instantiate a Wrapper from a JSON config dict.

    Required keys (all wrappers): `name`, `type`, `binary`.
    Required keys (probe): `probe_args`.
    Required keys (always): `prefix`.

    Optional keys (all): `enabled` (auto/always/never), `transparent_for_safety`,
    `prompt_block_path`, `failure_markers`, `retry_raw_on_failure`.
    Optional keys (probe): `no_rewrite_marker`, `probe_timeout_seconds`.

    The factory resolves `prompt_block_path` to its content at construction
    time so the framework can compose prompt blocks without re-doing IO.
    """
    name = entry.get("name")
    if not name:
        raise WrapperConfigError(f"Wrapper entry missing required 'name': {entry!r}")

    wrapper_type = entry.get("type")
    if wrapper_type not in _TYPE_REGISTRY:
        raise WrapperConfigError(
            f"Wrapper {name!r}: 'type' must be one of {list(_TYPE_REGISTRY)}, "
            f"got {wrapper_type!r}"
        )

    binary = entry.get("binary")
    if not binary:
        raise WrapperConfigError(f"Wrapper {name!r}: missing required 'binary'")

    common_kwargs = dict(
        name=name,
        binary=binary,
        enabled=entry.get("enabled", "auto"),
        transparent_for_safety=bool(entry.get("transparent_for_safety", True)),
        prompt_block=_load_prompt_block(name, entry.get("prompt_block_path")),
        failure_markers=list(entry.get("failure_markers") or ()),
        retry_raw_on_failure=bool(entry.get("retry_raw_on_failure", False)),
    )

    cls = _TYPE_REGISTRY[wrapper_type]

    if wrapper_type == "probe":
        probe_args = entry.get("probe_args")
        if not probe_args:
            raise WrapperConfigError(f"Wrapper {name!r} (probe): missing required 'probe_args'")
        return cls(
            probe_args=list(probe_args),
            no_rewrite_marker=entry.get("no_rewrite_marker", ""),
            probe_timeout_seconds=float(entry.get("probe_timeout_seconds", 5.0)),
            **common_kwargs,
        )

    # type == "always"
    prefix = entry.get("prefix")
    if not prefix:
        raise WrapperConfigError(f"Wrapper {name!r} (always): missing required 'prefix'")
    return cls(prefix=prefix, **common_kwargs)


def _load_prompt_block(wrapper_name: str, path: str | None) -> str | None:
    """Resolve a `prompt_block_path` to its markdown content.

    Search order:
    1. Absolute path → read directly.
    2. `~/.ppxai/wrappers/<path>` → user-declared wrappers ship hint files there.
    3. `ppxai/engine/tools/wrappers/<path>` (via `importlib.resources`) — the
       package's bundled hint files (e.g. RTK.md). Works under PyInstaller.

    Returns None if `path` is empty or the file is unreadable; the framework
    omits the prompt section for that wrapper. We log at INFO on failure
    so a missing hint file is visible without crashing the engine.
    """
    if not path:
        return None

    if os.path.isabs(path):
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError as e:
            logger.info("Wrapper %s: prompt block at %s unreadable: %s", wrapper_name, path, e)
            return None

    user_path = Path.home() / ".ppxai" / "wrappers" / path
    try:
        if user_path.is_file():
            return user_path.read_text(encoding="utf-8")
    except OSError:
        pass

    try:
        package_root = importlib.resources.files("ppxai.engine.tools.wrappers")
        resource = package_root.joinpath(path)
        if resource.is_file():
            return resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, ModuleNotFoundError) as e:
        logger.info("Wrapper %s: prompt block %r not found in package: %s", wrapper_name, path, e)

    logger.info("Wrapper %s: prompt block %r not found in any search location", wrapper_name, path)
    return None
