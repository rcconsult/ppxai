"""Dated obligations fail the suite when they come due (debt Item 64).

A commitment with a date on it is only as good as someone remembering the
date. Item 64 — re-probe Perplexity's pro line on the Responses wire before
the chat-completions endpoint retires — was recorded in three places (a code
comment, an untracked audit-notes file, and the debt inventory) and *none* of
them fires. All three are read by someone who has already decided to look.

So the date lives here instead, as a test that goes red on the day the work
becomes due and names exactly what to do. That is the difference between a
reminder and a commitment.

**This test failing is not a bug — it is the alarm working.** The fix is to
do the probe and then move the date (or delete the entry, if the obligation
is discharged for good).
"""

from datetime import date

import pytest

#: (due, description, what to do). `due` is when the work must HAPPEN, which
#: is deliberately earlier than any external cutover it protects against —
#: late enough for the upstream change to have landed, early enough to still
#: ship a fix.
OBLIGATIONS = [
    (
        date(2026, 10, 10),
        "debt Item 54 — re-probe Gemini's Pro tier for a GA successor",
        (
            "Google sunsets the Gemini 2.5 line 2026-10-16 (earliest). "
            "GEMINI_DEPRECATIONS migrates `gemini-2.5-pro` to "
            "`gemini-3.1-pro-preview` — a PREVIEW, because a live ListModels "
            "probe on 2026-09-01 (52 models) found NO GA 3.x Pro at all: only "
            "`gemini-3.1-pro-preview` and `gemini-3.1-pro-preview-customtools`. "
            "The one GA-looking id, `gemini-pro-latest`, is an unpinned ALIAS "
            "with no version field, so it names no stable contract and is a "
            "worse migration target than a named preview.\n"
            "\n"
            "That advice is correct only while it stays true: if a GA 3.x Pro "
            "has since shipped, ppxai is steering operators onto a preview "
            "Google can withdraw without notice.\n"
            "\n"
            "  uv run python scripts/probe-gemini-pro-tier.py\n"
            "\n"
            "A GA 3.x Pro appeared? Update `replacement` for `gemini-2.5-pro` "
            "and `gemini-3-pro-preview` in "
            "ppxai/engine/model_deprecations.py, and drop the preview caveat "
            "from both reason strings.\n"
            "Still preview-only? Move this date past the sunset, or delete the "
            "entry — the 2.5 ids are in NO config we ship, so the only exposure "
            "is migration ADVICE to an operator who still has them."
        ),
    ),
]


@pytest.mark.parametrize(
    "due,what,todo", OBLIGATIONS, ids=[o[1].split("—")[0].strip() for o in OBLIGATIONS]
)
def test_a_dated_obligation_has_not_come_due(due, what, todo):
    today = date.today()
    assert today < due, (
        f"\n\nDATED OBLIGATION DUE: {what}\n"
        f"due {due.isoformat()}, today {today.isoformat()} "
        f"({(today - due).days} day(s) over)\n\n{todo}\n\n"
        f"This failure IS the reminder. Do the work, then update or remove "
        f"the entry in tests/test_dated_obligations.py.\n"
    )


#: The day this file was written. An obligation dated before it was already
#: overdue when authored, which means it fires on the first run and gets
#: muted — the opposite of the point.
AUTHORED = date(2026, 8, 31)


def test_every_obligation_was_in_the_future_when_written():
    """Asserts what the name says.

    The first version of this checked only `isinstance(due, date)` — a shape
    check wearing a semantics name, which would have passed for a date years
    in the past. Caught in review.
    """
    for due, what, _ in OBLIGATIONS:
        assert isinstance(due, date), f"{what}: due date must be a date"
        assert due > AUTHORED, (
            f"{what}: due {due.isoformat()} is not after the authoring date "
            f"{AUTHORED.isoformat()} — an obligation that is overdue on "
            f"arrival fires immediately and teaches the reader to ignore it"
        )


def test_the_list_is_not_silently_empty():
    """An empty list passes vacuously forever.

    If the last obligation is discharged, delete this file rather than
    leaving a fence that cannot fail.
    """
    assert OBLIGATIONS, (
        "no dated obligations remain — delete this file instead of keeping "
        "an empty fence"
    )
