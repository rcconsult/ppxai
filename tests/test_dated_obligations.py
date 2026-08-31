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
        date(2026, 9, 20),
        "debt Item 64 — re-probe Perplexity's pro line on the Responses wire",
        (
            "Perplexity retires the Sonar chat-completions endpoint on "
            "2026-09-27. PERPLEXITY_DEPRECATIONS currently migrates every "
            "sonar-pro / sonar-reasoning-pro operator to `perplexity/sonar` "
            "— the LIGHTER model — because on 2026-08-31 the pro ids answered "
            "400 'not supported' on the Responses wire, bare and namespaced.\n"
            "That hint is correct only while it stays true: if Perplexity has "
            "since shipped the pro line on Responses, ppxai is actively "
            "advising a downgrade nobody needs, and the user WILL follow it.\n"
            "\n"
            "  uv run python scripts/probe-perplexity-capabilities.py \\\n"
            "      --api-path responses \\\n"
            "      --model perplexity/sonar-pro \\\n"
            "      --model perplexity/sonar-reasoning-pro \\\n"
            "      --model sonar-pro\n"
            "\n"
            "Still 400? Update the date below to 2026-09-26 for a last check, "
            "or drop this entry and let Item 64 close with the endpoint.\n"
            "Any of them answers? Fix `replacement` in "
            "ppxai/engine/model_deprecations.py, re-add the ids to "
            "ppxai-config.example.json with a pricing row, and trim the "
            "migration fence's RETIRED set to match."
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


def test_every_obligation_is_in_the_future_when_written():
    """A due date already past at authoring time would fire immediately and
    get muted — the opposite of the point."""
    for due, what, _ in OBLIGATIONS:
        assert isinstance(due, date), what


def test_the_list_is_not_silently_empty():
    """An empty list passes vacuously forever.

    If the last obligation is discharged, delete this file rather than
    leaving a fence that cannot fail.
    """
    assert OBLIGATIONS, (
        "no dated obligations remain — delete this file instead of keeping "
        "an empty fence"
    )
