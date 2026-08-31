"""WrapperRegistry — composes the per-call decisions across active wrappers.

This is the integration surface for the rest of ppxai:

- `find_first_rewrite(command)` — engine-side rewrite path. Iterates active
  wrappers in declaration order and returns the first non-None rewrite.
  First-match-wins; no pipelining.
- `compose_prompt_blocks()` — system-prompt path. Concatenates active
  wrappers' prompt blocks under a single header.
- `strip_transparent_prefixes(command)` — consent-classifier path.
  Removes leading wrapper tokens whose `transparent_for_safety=True` so
  the safety verdict is invariant under wrapping.
- `find_active_wrapper(rewritten_command)` — given a wrapped command,
  return the wrapper whose binary leads it (used by Phase-4 graceful
  fallback to ask "did THIS wrapper fail or did the inner tool fail?").
"""

from __future__ import annotations

import logging
import threading

from ....config import get_shell_config
from .base import Wrapper
from .factory import WrapperConfigError, make_wrapper

logger = logging.getLogger(__name__)


class WrapperRegistry:
    """Holds the active wrapper instances. Constructed once per engine session
    from the `tools.shell.wrappers` config list (defaults + user overrides).
    """

    def __init__(self, wrappers: list[Wrapper]):
        self._wrappers = list(wrappers)

    @property
    def all(self) -> list[Wrapper]:
        return list(self._wrappers)

    @property
    def active(self) -> list[Wrapper]:
        """Wrappers that are enabled AND have their binary on PATH (or
        enabled=always). Order is declaration order from the config.
        """
        return [w for w in self._wrappers if w.is_active()]

    async def find_first_rewrite(self, command: str) -> str | None:
        """Engine-side rewrite. Iterate active wrappers; return the first
        non-None rewrite. None means no wrapper applied — caller runs raw.
        """
        for wrapper in self.active:
            try:
                rewritten = await wrapper.maybe_rewrite(command)
            except Exception as e:
                # Per the Wrapper contract, maybe_rewrite shouldn't raise.
                # Log loudly if a wrapper violates that and skip it.
                logger.warning("Wrapper %s.maybe_rewrite raised %s: %s", wrapper.name, type(e).__name__, e)
                continue
            if rewritten and rewritten != command:
                logger.debug("Wrapper %s: %r -> %r", wrapper.name, command, rewritten)
                return rewritten
        return None

    def compose_prompt_blocks(self) -> str | None:
        """Concatenate prompt blocks from all active wrappers. Returns None
        if no active wrapper has a prompt block, so the caller can skip
        emitting the section header.
        """
        sections = []
        for wrapper in self.active:
            if wrapper.prompt_block:
                sections.append(f"### {wrapper.name}\n\n{wrapper.prompt_block.strip()}")
        if not sections:
            return None
        return "\n\n".join(sections)

    def strip_transparent_prefixes(self, command: str) -> str:
        """Remove leading wrapper tokens that are marked transparent for
        safety, so consent classification sees the inner command.

        Strips iteratively in case multiple transparent wrappers stack
        (e.g., `time rtk git status` → `rtk git status` → `git status`).
        Only strips if the wrapper is currently active — a transparent
        wrapper that isn't enabled doesn't license stripping.
        """
        # Build a name→wrapper map for active transparent wrappers, by binary.
        transparent_binaries = {
            w.binary: w for w in self.active if w.transparent_for_safety
        }

        peeled = command.lstrip()
        while True:
            # First whitespace-delimited token.
            head, sep, tail = peeled.partition(" ")
            if not sep:
                break
            if head in transparent_binaries:
                peeled = tail.lstrip()
                continue
            break
        return peeled

    def find_active_wrapper_by_prefix(self, command: str) -> Wrapper | None:
        """Return the wrapper whose binary token leads `command`, or None.

        Used by graceful-fallback to attribute a failure to the right
        wrapper before deciding whether to retry raw.
        """
        head, _sep, _tail = command.lstrip().partition(" ")
        for wrapper in self.active:
            if wrapper.binary == head:
                return wrapper
        return None

    def reset_caches(self) -> None:
        """Test hook: reset every wrapper's PATH-resolution cache."""
        for wrapper in self._wrappers:
            wrapper.reset_cache()


_REGISTRY_SINGLETON: WrapperRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> WrapperRegistry:
    """Return the engine-wide registry, building it on first access.

    The singleton reads `tools.shell.wrappers` config and instantiates
    via the factory. Reads happen once per process; restart picks up
    changes. Tests can override via `set_registry(...)`.

    Thread-safe lazy init: hot path is an unlocked read, cold path
    acquires the lock once per process. Asyncio doesn't need the
    lock (no await inside the build path), but multiple OS threads
    could race the check-then-create.
    """
    global _REGISTRY_SINGLETON
    cached = _REGISTRY_SINGLETON
    if cached is not None:
        return cached
    with _REGISTRY_LOCK:
        if _REGISTRY_SINGLETON is None:
            _REGISTRY_SINGLETON = _build_registry_from_config()
        return _REGISTRY_SINGLETON


def set_registry(registry: WrapperRegistry | None) -> None:
    """Test hook: install a registry, or pass None to force rebuild
    on the next `get_registry()`.
    """
    global _REGISTRY_SINGLETON
    with _REGISTRY_LOCK:
        _REGISTRY_SINGLETON = registry


def _build_registry_from_config() -> WrapperRegistry:
    """Internal: read config and assemble the registry. Lazy-imported to
    avoid circular dependencies between the wrappers package and the
    config layer.
    """

    try:
        shell_config = get_shell_config()
    except Exception as e:  # config not initialized in some test contexts
        logger.debug("Wrapper registry: config unavailable (%s); empty registry", e)
        return WrapperRegistry([])

    entries = shell_config.get("wrappers", [])
    wrappers: list[Wrapper] = []
    for entry in entries:
        try:
            wrappers.append(make_wrapper(entry))
        except WrapperConfigError as e:
            logger.warning("Skipping malformed wrapper entry %r: %s", entry, e)

    return WrapperRegistry(wrappers)
