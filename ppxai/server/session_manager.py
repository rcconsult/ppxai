"""
Session Manager for ppxai HTTP Server.

Centralizes all session state management to prevent race conditions
and improve testability. Replaces scattered global variables.

v1.13.10: Initial implementation (refactored from http.py globals)
          Thread-safe singleton with proper locking
"""

import asyncio
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Awaitable

from ..common.logger import get_logger
from ..config import get_available_providers, get_server_config
from ..engine import EngineClient

logger = get_logger("session_manager")


def get_default_working_dir() -> str:
    """The server-wide default working directory.

    `server.working_dir` from config when set and existing, else the user's
    home. Used for every new session engine AND (v1.19.x) as the fallback
    working dir of an unsealed /v1/agent/task run — so a run's relative
    tool paths never silently depend on where the server process happened
    to be launched from.
    """
    configured = get_server_config().get("working_dir")
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir():
            return str(path)
        logger.warning(
            f"Configured working_dir '{configured}' does not exist, "
            f"falling back to home"
        )
    return str(Path.home())


@dataclass
class Session:
    """Individual session data."""
    engine: EngineClient
    created_at: float
    last_used: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        """Update last_used timestamp."""
        self.last_used = time.time()


class SessionManager:
    """
    Centralized session state management.

    Thread-safe management of:
    - Session storage and lifecycle
    - Default engine for backward compatibility
    - Consent request tracking
    - Activity tracking for idle shutdown

    Thread Safety:
    - Singleton creation uses threading.Lock (safe across threads/workers)
    - Session operations use asyncio.Lock (safe for concurrent coroutines)
    - Activity tracking uses atomic operations

    Usage:
        manager = SessionManager.get_instance()
        await manager.initialize()
        session_id, engine, lock = await manager.get_or_create_session(session_id)
    """

    # Class-level singleton with thread-safe creation
    _instance: Optional['SessionManager'] = None
    _creation_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> 'SessionManager':
        """Thread-safe singleton pattern."""
        # Double-checked locking for thread safety
        if cls._instance is None:
            with cls._creation_lock:
                # Check again after acquiring lock
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize session manager (only runs once due to singleton)."""
        if self._initialized:
            return

        # Session storage (keyed by session_id)
        self._sessions: dict[str, Session] = {}
        self._sessions_lock = asyncio.Lock()

        # Default engine for backward compatibility
        self._default_engine: Optional['EngineClient'] = None
        self._default_lock: Optional[asyncio.Lock] = None

        # Consent request tracking (keyed by (session_id, identifier))
        self._pending_consent: dict[tuple[str, str], asyncio.Future] = {}
        self._pending_shell_consent: dict[tuple[str, str], asyncio.Future] = {}
        self._consent_lock = asyncio.Lock()

        # Activity tracking
        self._last_activity: float = 0.0
        self._shutdown_requested: bool = False
        self._shutdown_reason: str = "unknown"

        # Idle shutdown task
        self._idle_task: Optional[asyncio.Task] = None

        # Configuration
        self._session_timeout: int = 3600  # 1 hour default

        self._initialized = True
        logger.info("SessionManager initialized")

    @staticmethod
    def _get_default_working_dir() -> str:
        """Get the default working directory from config or fall back to home."""
        return get_default_working_dir()

    @classmethod
    def get_instance(cls) -> 'SessionManager':
        """Get the singleton instance (thread-safe)."""
        # Uses __new__ which has proper locking
        return cls()

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for testing purposes (thread-safe)."""
        with cls._creation_lock:
            if cls._instance is not None:
                cls._instance._initialized = False
            cls._instance = None

    # =========================================================================
    # Initialization and Shutdown
    # =========================================================================

    async def initialize(
        self,
        consent_callback: Optional[Callable[[str], Awaitable[tuple[bool, str]]]] = None,
        shell_consent_callback: Optional[Callable[[str, str, str], Awaitable[tuple[bool, str]]]] = None,
    ) -> None:
        """
        Initialize the session manager with default engine.

        Args:
            consent_callback: Callback for file edit consent (default engine)
            shell_consent_callback: Callback for shell command consent (default engine)
        """
        # Create default engine
        self._default_engine = EngineClient(
            consent_callback=consent_callback,
            shell_consent_callback=shell_consent_callback
        )
        self._default_lock = asyncio.Lock()

        # Default working dir from config (server.working_dir) or home directory.
        # When server starts from a binary, CWD may be the install dir.
        self._default_engine.set_working_dir(self._get_default_working_dir())

        # Set default provider
        providers = get_available_providers()
        if providers:
            self._default_engine.set_provider(providers[0])

        # Initialize activity tracking
        self._last_activity = time.time()

        logger.info(f"SessionManager initialized with provider: {self._default_engine.provider_name}")

    async def start_idle_monitor(self, idle_timeout: int, shutdown_callback: Callable[[], None] = None) -> None:
        """Start the idle shutdown monitor task.

        Args:
            idle_timeout: Seconds of inactivity before shutdown
            shutdown_callback: Optional callback to trigger graceful shutdown
        """
        if idle_timeout <= 0:
            logger.info("Idle auto-shutdown disabled (timeout <= 0)")
            return

        self._idle_task = asyncio.create_task(
            self._idle_shutdown_loop(idle_timeout, shutdown_callback)
        )
        logger.info(f"Idle shutdown monitor started (timeout: {idle_timeout}s)")

    async def shutdown(self) -> None:
        """Gracefully shutdown the session manager.

        v1.14.1: Now also calls save_dirty() to save session with alternation fix.
        """
        self._shutdown_requested = True

        # Cancel idle monitor
        if self._idle_task:
            self._idle_task.cancel()
            try:
                await self._idle_task
            except asyncio.CancelledError:
                pass

        # Save default engine session and usage
        if self._default_engine and self._default_engine.session:
            try:
                self._default_engine.session.save_usage_to_persistent_storage()
                # v1.14.1: Also save session with alternation validation
                if self._default_engine.session.messages:
                    self._default_engine.session.save_dirty()
                    self._default_engine.session.mark_clean()
                logger.info("Default session saved")
            except Exception as e:
                logger.warning(f"Failed to save default session: {e}")

        # Save all session usage and data
        async with self._sessions_lock:
            for sid, session in self._sessions.items():
                try:
                    session.engine.session.save_usage_to_persistent_storage()
                    # v1.14.1: Also save session with alternation validation
                    if session.engine.session.messages:
                        session.engine.session.save_dirty()
                        session.engine.session.mark_clean()
                    logger.info(f"Session {sid} saved")
                except Exception as e:
                    logger.warning(f"Failed to save session {sid}: {e}")

        logger.info("SessionManager shutdown complete")

    # =========================================================================
    # Session Management
    # =========================================================================

    async def get_or_create_session(
        self,
        session_id: Optional[str]
    ) -> tuple[str, 'EngineClient', asyncio.Lock]:
        """
        Get existing session or create new one.

        Args:
            session_id: Session ID from X-Session-Id header, or None for default

        Returns:
            tuple: (session_id, engine, lock)

        Raises:
            RuntimeError: If manager not initialized
        """
        # No session ID = use default engine (backward compatibility)
        if not session_id:
            if self._default_engine is None:
                raise RuntimeError("SessionManager not initialized")
            return ("default", self._default_engine, self._default_lock)

        async with self._sessions_lock:
            # Check for existing session
            if session_id in self._sessions:
                session = self._sessions[session_id]
                session.touch()
                return (session_id, session.engine, session.lock)

            # Create new session
            logger.info(f"Creating new session: {session_id}")
            session = await self._create_session(session_id)
            self._sessions[session_id] = session

            return (session_id, session.engine, session.lock)

    async def _create_session(self, session_id: str) -> Session:
        """Create a new session with its own engine."""
        # Create engine with session-specific consent handlers
        engine = EngineClient(
            consent_callback=lambda fp: self._handle_consent(session_id, fp),
            shell_consent_callback=lambda cmd, wd, rl: self._handle_shell_consent(session_id, cmd, wd, rl)
        )

        # Default working dir from config (server.working_dir) or home directory
        engine.set_working_dir(self._get_default_working_dir())

        # Set default provider
        providers = get_available_providers()
        if providers:
            engine.set_provider(providers[0])

        return Session(
            engine=engine,
            created_at=time.time(),
            last_used=time.time(),
        )

    async def cleanup_expired_sessions(self) -> int:
        """
        Remove sessions that haven't been used recently.

        Returns:
            Number of sessions cleaned up
        """
        now = time.time()
        expired_ids = []

        async with self._sessions_lock:
            for sid, session in self._sessions.items():
                if now - session.last_used > self._session_timeout:
                    expired_ids.append(sid)

            for sid in expired_ids:
                logger.info(f"Cleaning up expired session: {sid}")
                session = self._sessions.pop(sid)
                # Save usage before cleanup
                try:
                    session.engine.session.save_usage_to_persistent_storage()
                except Exception as e:
                    logger.warning(f"Failed to save usage for session {sid}: {e}")

        return len(expired_ids)

    def broadcast_background_agents(self, summary: list) -> None:
        """Push the active-agent-run summary into every engine's AppState
        (Inc 9). Called from the agent-run registry's on_change hook; the
        per-engine `state_sync` machinery then fans `background_agents` out to
        connected clients, and GET /state serves the same field on reconnect.

        Deliberately lock-free + best-effort: it runs on the event-loop thread
        from a registry callback, AppState.set is thread-safe, and a badge is
        not worth blocking run execution on the sessions lock. A session that
        appears/disappears mid-broadcast just gets the next update."""
        engines = []
        if self._default_engine is not None:
            engines.append(self._default_engine)
        for session in list(self._sessions.values()):
            engines.append(session.engine)
        for engine in engines:
            try:
                engine.state.set("background_agents", list(summary))
            except Exception:
                logger.warning(
                    "failed to push background_agents to an engine", exc_info=True
                )

    async def list_sessions(self) -> list[dict]:
        """List all active sessions with their metadata."""
        await self.cleanup_expired_sessions()

        session_list = []
        async with self._sessions_lock:
            for sid, session in self._sessions.items():
                session_list.append({
                    "session_id": sid,
                    "created_at": session.created_at,
                    "last_used": session.last_used,
                    "provider": session.engine.provider_name,
                    "model": session.engine.model,
                    "message_count": len(session.engine.session.messages),
                    "working_dir": session.engine.get_working_dir(),
                })

        return session_list

    # =========================================================================
    # Activity Tracking
    # =========================================================================

    def update_activity(self) -> None:
        """Update last activity timestamp."""
        self._last_activity = time.time()

    @property
    def last_activity(self) -> float:
        """Get last activity timestamp."""
        return self._last_activity

    @property
    def shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested

    @property
    def shutdown_reason(self) -> str:
        """Get the reason for shutdown."""
        return self._shutdown_reason

    def request_shutdown(self, reason: str = "user_request") -> None:
        """Request graceful shutdown with reason.

        Args:
            reason: Reason for shutdown (e.g., 'user_request', 'idle_timeout', 'api_request')
        """
        self._shutdown_requested = True
        self._shutdown_reason = reason
        logger.info(f"Shutdown requested (reason: {reason})")

    async def _idle_shutdown_loop(self, idle_timeout: int, shutdown_callback: Callable[[], None] = None) -> None:
        """Background task to check for idle shutdown.

        Args:
            idle_timeout: Seconds of inactivity before shutdown
            shutdown_callback: Optional callback to trigger graceful shutdown
        """
        while not self._shutdown_requested:
            await asyncio.sleep(30)  # Check every 30 seconds

            if self._shutdown_requested:
                break

            idle_time = time.time() - self._last_activity
            if idle_time > idle_timeout:
                logger.info(f"Server idle for {idle_time:.0f}s (>{idle_timeout}s), initiating shutdown")
                print(f"\nAuto-shutdown: No activity for {idle_timeout // 60} minutes")
                self.request_shutdown("idle_timeout")
                # Use callback for graceful shutdown if provided, else fallback to os._exit
                if shutdown_callback:
                    shutdown_callback()
                else:
                    os._exit(0)

    # =========================================================================
    # Consent Management
    # =========================================================================

    async def _handle_consent(self, session_id: str, file_path: str) -> tuple[bool, str]:
        """Handle file edit consent request for a specific session."""
        key = (session_id, file_path)
        logger.debug(f"Consent: _handle_consent called for key={key}")

        async with self._consent_lock:
            future: asyncio.Future[tuple[bool, str]] = asyncio.Future()
            self._pending_consent[key] = future
            logger.debug(f"Consent: Future created, pending keys={list(self._pending_consent.keys())}")

        try:
            approved, response = await asyncio.wait_for(future, timeout=300.0)
            logger.debug(f"Consent: Future resolved approved={approved} response={response}")
            return (approved, response)
        except asyncio.TimeoutError:
            logger.debug(f"Consent: Future TIMED OUT for key={key}")
            return (False, 'n')
        except asyncio.CancelledError:
            logger.debug(f"Consent: Future CANCELLED for key={key}")
            return (False, 'n')
        except Exception as e:
            logger.debug(f"Consent: Future EXCEPTION for key={key}: {e}")
            return (False, 'n')
        finally:
            async with self._consent_lock:
                self._pending_consent.pop(key, None)

    async def _handle_shell_consent(
        self,
        session_id: str,
        command: str,
        working_dir: str,
        risk_level: str
    ) -> tuple[bool, str]:
        """Handle shell command consent request for a specific session."""
        key = (session_id, command)

        async with self._consent_lock:
            future: asyncio.Future[tuple[bool, str]] = asyncio.Future()
            self._pending_shell_consent[key] = future

        try:
            approved, response = await asyncio.wait_for(future, timeout=60.0)
            return (approved, response)
        except asyncio.TimeoutError:
            return (False, 'n')
        finally:
            async with self._consent_lock:
                self._pending_shell_consent.pop(key, None)

    async def resolve_consent(
        self,
        session_id: str,
        file_path: str,
        response: str
    ) -> bool:
        """
        Resolve a pending consent request.

        Args:
            session_id: Session ID
            file_path: File path being consented
            response: User response ('y', 'n', 'always', 'never')

        Returns:
            True if request was found and resolved, False otherwise
        """
        key = (session_id, file_path)
        logger.debug(f"Consent: resolve_consent called key={key} response={response}")
        logger.debug(f"Consent: pending keys={list(self._pending_consent.keys())}")

        async with self._consent_lock:
            if key not in self._pending_consent:
                logger.debug(f"Consent: key NOT FOUND in pending_consent!")
                return False

            future = self._pending_consent[key]
            if future.done():
                logger.debug(f"Consent: Future already done!")
                return False

            approved = response in ['y', 'always']
            future.set_result((approved, response))
            logger.debug(f"Consent: Future SET approved={approved}")
            return True

    async def resolve_shell_consent(
        self,
        session_id: str,
        command: str,
        response: str
    ) -> bool:
        """
        Resolve a pending shell consent request.

        Args:
            session_id: Session ID
            command: Command being consented
            response: User response ('y', 'n', 'always', 'never')

        Returns:
            True if request was found and resolved, False otherwise
        """
        key = (session_id, command)

        async with self._consent_lock:
            if key not in self._pending_shell_consent:
                return False

            future = self._pending_shell_consent[key]
            if future.done():
                return False

            approved = response in ['y', 'always']
            future.set_result((approved, response))
            return True

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def default_engine(self) -> Optional['EngineClient']:
        """Get the default engine."""
        return self._default_engine

    @property
    def session_count(self) -> int:
        """Get the number of active sessions (excluding default)."""
        return len(self._sessions)

    @property
    def is_initialized(self) -> bool:
        """Check if the manager has been initialized."""
        return self._default_engine is not None
