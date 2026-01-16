"""
Thread-safe and asyncio-safe configuration store.

Designed for:
- Multi-threaded TUI applications
- Async HTTP server (FastAPI)
- Containerized deployments with multiple workers

v1.13.10: Created as part of config.py package refactoring
"""

import threading
from typing import Any, Dict, Optional


class ConfigStore:
    """Singleton configuration store with thread-safe access.

    Thread Safety:
    - Uses threading.Lock for singleton creation
    - Config dict is immutable after load (replaced atomically on reload)
    - Read operations are lock-free (atomic dict reference)

    Asyncio Safety:
    - No async locks needed - all operations are synchronous and fast
    - Config loading happens once, reads are O(1) dict lookups
    - Safe to call from any coroutine

    Container Deployment:
    - Each worker process gets its own ConfigStore instance
    - Config reload is per-process (no shared state between containers)
    - Environment variables respected for container orchestration
    """

    _instance: Optional["ConfigStore"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "ConfigStore":
        """Thread-safe singleton creation using double-check locking."""
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._config: Optional[Dict[str, Any]] = None
                    instance._config_lock = threading.Lock()
                    instance._loaded = False
                    cls._instance = instance
        return cls._instance

    @classmethod
    def get_instance(cls) -> "ConfigStore":
        """Get the singleton instance."""
        return cls()

    @property
    def config(self) -> Dict[str, Any]:
        """Get configuration, loading lazily on first access.

        Thread-safe: Uses double-check locking for initialization.
        After first load, reads are lock-free (atomic dict reference).
        """
        if not self._loaded:
            with self._config_lock:
                if not self._loaded:
                    from .loader import load_config
                    self._config = load_config()
                    self._loaded = True
        return self._config

    def reload(self) -> Dict[str, Any]:
        """Reload configuration from disk.

        Thread-safe: Atomically replaces config reference.
        In-flight reads see either old or new config (both valid).
        """
        with self._config_lock:
            from .loader import load_config
            self._config = load_config()
            self._loaded = True
        return self._config

    def set_for_testing(self, config: Dict[str, Any]) -> None:
        """Replace config for testing purposes.

        Thread-safe but NOT intended for production use.
        Use only in test fixtures with proper cleanup.
        """
        with self._config_lock:
            self._config = config
            self._loaded = True

    def reset(self) -> None:
        """Reset to unloaded state (for testing)."""
        with self._config_lock:
            self._config = None
            self._loaded = False

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing only).

        WARNING: Not thread-safe. Only use in test setup/teardown
        when no other threads are accessing config.
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance._config = None
                cls._instance._loaded = False
            cls._instance = None


# Module-level convenience functions
def get_config() -> Dict[str, Any]:
    """Get the current configuration dict."""
    return ConfigStore.get_instance().config


def reload_config() -> Dict[str, Any]:
    """Reload configuration from disk."""
    return ConfigStore.get_instance().reload()
