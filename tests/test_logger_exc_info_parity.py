"""`common.logger.Logger` accepts `exc_info` at every level, like stdlib.

This codebase runs TWO logger populations side by side: 54 modules use the
custom `Logger` via `get_logger()`, and 17 use `logging.getLogger()` directly.
At a call site they are indistinguishable — both are `logger.debug(...)`.

Until v1.19.1 only `error()` accepted `exc_info`, so the two APIs diverged in
a way that only showed up at runtime. That matters because the divergence
fires in the worst place: these calls live inside `except` blocks, so passing
`exc_info` to `debug` raised `TypeError` and converted a HANDLED error into an
escaping one — a crash at the moment the code was being careful.

Not hypothetical in either direction: `engine/tools/builtin/__init__.py`
already logs `warning(..., exc_info=True)` on a stdlib logger (`:83`, `:95`,
`:109`), inside `except` blocks guarding optional tool registration. Had that
module ever switched to `get_logger`, an optional dependency being absent
would have broken tool registration outright.

These tests pin the parity so the populations cannot drift apart again.
"""

from __future__ import annotations

import inspect
import logging

import pytest

from ppxai.common.logger import get_logger

LEVELS = ("debug", "info", "warning", "error")


@pytest.fixture
def logger():
    return get_logger("test-exc-info")


@pytest.mark.parametrize("level", LEVELS)
def test_every_level_accepts_exc_info(logger, level):
    """The regression itself — and it must hold inside an except block."""
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        getattr(logger, level)("handled", exc_info=True)  # must not raise


@pytest.mark.parametrize("level", LEVELS)
def test_every_level_still_works_without_exc_info(logger, level):
    """The parameter is optional; existing single-argument callers are the
    overwhelming majority and must be untouched."""
    getattr(logger, level)("plain message")


@pytest.mark.parametrize("level", LEVELS)
def test_signature_matches_the_stdlib_call_shape(level):
    """Sentinel: the custom logger must keep accepting what stdlib accepts.

    Compares the accepted keyword against the real `logging.Logger`, so this
    tracks stdlib rather than restating a hardcoded expectation. If someone
    adds a level method without `exc_info`, this fails before the runtime
    TypeError finds a user.
    """
    custom = inspect.signature(getattr(get_logger("sig-probe"), level))
    assert "exc_info" in custom.parameters, (
        f"Logger.{level}() dropped exc_info — call sites moving between the "
        f"custom and stdlib logger populations will break inside except blocks"
    )

    # Stdlib's counterpart is `(msg, *args, **kwargs)`, so `exc_info` never
    # appears in `signature().parameters` — it arrives through **kwargs.
    # Comparing signatures structurally therefore proves nothing about
    # stdlib; the parity that matters is that the CALL is accepted.
    getattr(logging.getLogger("stdlib-probe"), level)("probe", exc_info=False)


def test_disabled_logger_still_accepts_exc_info():
    """A disabled logger swallows output; it must not swallow the signature.

    `disable()` swaps in a no-op logger, so this is the path most likely to
    be missed by a change that only fixes the enabled case.
    """
    lg = get_logger("test-exc-info-disabled")
    lg.disable()
    try:
        try:
            raise ValueError("x")
        except ValueError:
            for level in LEVELS:
                getattr(lg, level)("while disabled", exc_info=True)
    finally:
        lg.enable()
