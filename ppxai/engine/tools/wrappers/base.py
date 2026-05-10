"""Wrapper base class + generic implementations (v1.18.5).

A "wrapper" is a transparent CLI proxy that ppxai applies to commands
the shell tool is about to spawn. Examples: rtk (token-savings filter),
time (timing), nice (priority), perf (profiling). The wrapper
framework lets ppxai integrate any such tool through JSON config
alone — no per-wrapper Python code is required for the common cases.

Two concrete generic classes cover most wrappers:

- `ProbeWrapper` — has its own dry-run command (e.g. `rtk hook check`)
  that decides whether a given command should be wrapped. ppxai calls
  the dry-run, parses the result, and applies the rewrite.
- `AlwaysWrapper` — has no dry-run; user opted in, so wrap every
  command. Suitable for `time`, `nice`, sandboxers, profilers.

Bespoke wrappers can subclass `Wrapper` directly and add a
`type: "custom"` + `class: "module.path.Cls"` config entry — but for
v1.18.5 every shipped wrapper (rtk) and every realistic addition
(time, nice, perf) fits one of the two generic classes.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import threading
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class Wrapper(ABC):
    """Abstract shell-command wrapper.

    Subclasses encode the decision strategy (probe / always / custom).
    Per-wrapper config (failure markers, prompt hints, transparency for
    safety classification) is held on the instance and consumed by the
    framework.
    """

    name: str
    binary: str
    enabled: str  # "auto" | "always" | "never"
    transparent_for_safety: bool
    prompt_block: Optional[str]
    failure_markers: Tuple[str, ...]
    retry_raw_on_failure: bool

    def __init__(
        self,
        *,
        name: str,
        binary: str,
        enabled: str = "auto",
        transparent_for_safety: bool = True,
        prompt_block: Optional[str] = None,
        failure_markers: Optional[List[str]] = None,
        retry_raw_on_failure: bool = False,
    ):
        self.name = name
        self.binary = binary
        self.enabled = enabled
        self.transparent_for_safety = transparent_for_safety
        self.prompt_block = prompt_block
        self.failure_markers = tuple(failure_markers or ())
        self.retry_raw_on_failure = retry_raw_on_failure
        self._available_cache: Optional[bool] = None
        # Thread-safety: protects the lazy-init of `_available_cache`. Asyncio
        # alone doesn't need this (sync function, no await), but multiple
        # OS threads — e.g. future sub-agent workers — could race here.
        self._cache_lock = threading.Lock()

    def is_available(self) -> bool:
        """Return True if the wrapper binary resolves on PATH. Cached.

        Thread-safe lazy init: the lock costs one uncontended acquire on
        the cold path; the hot path is a plain attribute read after the
        cache is populated.
        """
        # Fast path: cache populated, no lock needed.
        cached = self._available_cache
        if cached is not None:
            return cached
        with self._cache_lock:
            if self._available_cache is None:
                self._available_cache = shutil.which(self.binary) is not None
            return self._available_cache

    def is_active(self) -> bool:
        """Should this wrapper participate in the current decision?

        `enabled=auto` → active iff binary is on PATH.
        `enabled=always` → active (caller is responsible for surfacing
        the error if the binary is missing).
        `enabled=never` → inactive.
        """
        if self.enabled == "never":
            return False
        if self.enabled == "always":
            return True
        return self.is_available()

    def reset_cache(self) -> None:
        """Test hook: clear the PATH-resolution cache."""
        with self._cache_lock:
            self._available_cache = None

    @abstractmethod
    async def maybe_rewrite(self, command: str) -> Optional[str]:
        """Return the wrapped form of `command`, or None to skip.

        Implementations must NOT raise on subprocess failure or timeout —
        return None and let the framework fall back to the raw command.
        """
        ...

    def is_wrapper_side_failure(self, stderr_text: str, return_code: int) -> bool:
        """Heuristic: did THIS wrapper itself fail (vs the wrapped tool)?

        Used by the graceful-fallback path. Trusts the wrapped tool's
        own non-zero exit codes (e.g. `git status` returning 1 in a
        non-repo) — only flags failures whose stderr matches one of the
        wrapper's declared `failure_markers`.
        """
        if return_code == 0 or not stderr_text or not self.failure_markers:
            return False
        return any(marker in stderr_text for marker in self.failure_markers)


class ProbeWrapper(Wrapper):
    """Wrapper with an external dry-run probe.

    Calls `<binary> <probe_args> <command>` and inspects the result:
    - exit 0 + stdout that does NOT start with `no_rewrite_marker` →
      stdout IS the rewritten command.
    - exit non-zero, OR stdout starts with `no_rewrite_marker`, OR
      timeout, OR spawn failure → return None (run raw).
    """

    def __init__(
        self,
        *,
        probe_args: List[str],
        no_rewrite_marker: str = "",
        probe_timeout_seconds: float = 5.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.probe_args = tuple(probe_args)
        self.no_rewrite_marker = no_rewrite_marker
        self.probe_timeout_seconds = probe_timeout_seconds

    async def maybe_rewrite(self, command: str) -> Optional[str]:
        if not self.is_available():
            return None

        binary_path = shutil.which(self.binary)
        if binary_path is None:
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                binary_path, *self.probe_args, command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as e:
            logger.debug("%s probe spawn failed: %s", self.name, e)
            return None

        try:
            stdout_b, _stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=self.probe_timeout_seconds
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass
            logger.debug("%s probe timed out for: %s", self.name, command)
            return None

        rewritten = stdout_b.decode("utf-8", errors="replace").strip() if stdout_b else ""

        if proc.returncode != 0:
            return None
        if not rewritten:
            return None
        if self.no_rewrite_marker and rewritten.startswith(self.no_rewrite_marker):
            return None
        return rewritten


class AlwaysWrapper(Wrapper):
    """Wrapper that prefixes every command unconditionally.

    Suitable for tools with no native dry-run: `time`, `nice`, perf
    profilers, sandboxers. The user opts in by enabling the wrapper;
    once enabled, every command is wrapped via `<prefix> <command>`.
    """

    def __init__(self, *, prefix: str, **kwargs):
        super().__init__(**kwargs)
        if not prefix.strip():
            raise ValueError(f"AlwaysWrapper {kwargs.get('name')!r} requires a non-empty prefix")
        self.prefix = prefix.strip()

    async def maybe_rewrite(self, command: str) -> Optional[str]:
        if not self.is_available():
            return None
        return f"{self.prefix} {command}"
