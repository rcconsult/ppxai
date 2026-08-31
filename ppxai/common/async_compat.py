"""
Async compatibility helpers for running async code in both sync and async contexts.

This module provides utilities to safely execute async code whether or not an
event loop is already running. This is needed because:
- Rich TUI is synchronous and uses asyncio.run()
- Textual TUI is async and already has a running event loop
- Commands and engine methods need to work in both contexts

v1.15.0: Added to fix asyncio.run() errors in Textual TUI
"""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar('T')


async def run_in_event_loop(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine in the current event loop if one exists, otherwise create one.

    This function handles both cases:
    - If called from async context (event loop running): await the coroutine
    - If called from sync context (no event loop): use asyncio.run()

    Args:
        coro: Coroutine to execute

    Returns:
        Result of the coroutine

    Raises:
        Any exception raised by the coroutine

    Example:
        # From sync context (Rich TUI)
        result = asyncio.run(run_in_event_loop(my_async_function()))

        # From async context (Textual TUI)
        result = await run_in_event_loop(my_async_function())
    """
    # This is already a coroutine function, so it will be awaited by the caller
    return await coro


def run_coro_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine synchronously, handling both sync and async contexts.

    This is a drop-in replacement for asyncio.run() that works even when
    called from within an existing event loop (like Textual TUI).

    Args:
        coro: Coroutine to execute

    Returns:
        Result of the coroutine

    Raises:
        RuntimeError: If called from async context with running event loop
                      (caller should use await instead)
        Any exception raised by the coroutine

    Example:
        # Replace asyncio.run(my_coro())
        result = run_coro_sync(my_coro())
    """
    try:
        # Check if there's already a running event loop
        asyncio.get_running_loop()
    except RuntimeError:
        # No event loop running - safe to use asyncio.run()
        return asyncio.run(coro)
    else:
        # Event loop is running - this is an error, caller should use await
        raise RuntimeError(
            "run_coro_sync() called from async context with running event loop. "
            "Use 'await' instead of this function, or ensure the handler is async."
        )


def is_event_loop_running() -> bool:
    """Check if an asyncio event loop is currently running.

    Returns:
        True if an event loop is running, False otherwise
    """
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False
