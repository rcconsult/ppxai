"""R16 regression test — ppxaide event dispatcher must cover every EventType.

The Textual TUI used to log "Unknown event type: EventType.X" warnings when
the engine emitted an event the dispatcher didn't know about. The dispatcher
is now split into two explicit sets:

    EVENT_MAP    — routes to an event-bus signal for UI rendering
    NOOP_EVENTS  — intentionally ignored (documented no-op)

Every EventType member must belong to exactly one of these. This test is a
drift detector: adding a new EventType without touching stream_handler.py
will fail it.
"""

import pytest

from ppxai.engine.types import EventType


def test_every_event_type_is_covered():
    """Each EventType member must be in EVENT_MAP xor NOOP_EVENTS."""
    pytest.importorskip("textual")
    from ppxai.tui.stream_handler import EVENT_MAP, NOOP_EVENTS

    covered = set(EVENT_MAP) | NOOP_EVENTS
    all_types = set(EventType)

    missing = all_types - covered
    assert not missing, (
        f"EventType members without a dispatcher entry: {missing}. "
        f"Add each to EVENT_MAP (with a UI bus signal) or NOOP_EVENTS "
        f"(with a comment explaining why it's ignored)."
    )

    overlap = set(EVENT_MAP) & NOOP_EVENTS
    assert not overlap, (
        f"EventType members in both EVENT_MAP and NOOP_EVENTS: {overlap}. "
        f"An event can be routed or ignored — not both."
    )


def test_noop_events_are_intentional():
    """NOOP_EVENTS contains only the types we've reviewed and chosen to skip."""
    pytest.importorskip("textual")
    from ppxai.tui.stream_handler import NOOP_EVENTS

    expected_noop = {
        EventType.STATE_SYNC,           # handled via AppState observers
        EventType.AGENT_ITERATION,      # Rich-only agent UI
        EventType.AGENT_COMPLETE,
        EventType.AGENT_MAX_ITERATIONS,
        EventType.STATUS,               # surfaced via INFO
        # P0 (v1.18.0) — Stage 1 parks these until Stage 5 wires
        # dedicated bus signals + ppxaide rendering. Stage 2 only adds
        # emission; no client surface yet.
        EventType.AGENT_BEAT,
        EventType.AGENT_RUN_START,
        EventType.AGENT_RUN_ERROR,
        EventType.AGENT_ZOMBIE,
    }

    assert NOOP_EVENTS == expected_noop, (
        f"NOOP_EVENTS changed — {NOOP_EVENTS ^ expected_noop} differs. "
        f"If you're adding a NOOP entry, update this test and document why "
        f"the type is intentionally skipped."
    )
