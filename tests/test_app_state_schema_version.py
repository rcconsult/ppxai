"""Enforces the AppState schema versioning rule (Task 4, owner decision
2026-09-21: "maintain it").

Background
----------
`ppxai/engine/app_state_schema.json`'s `"version"` read `"1.0"`
unchanged from the file's creation through five later commits that
added or renamed fields (`git log -p --follow
ppxai/engine/app_state_schema.json | grep '"version"'` shows only the
one value). An unenforced rule is exactly how that happened, so this
module is the enforcement, not just the documentation — the rule
itself is written in `app_state_schema.json`'s `"description"` and in
`ppxai/engine/app_state.py`'s module docstring.

The rule
--------
`version` is `"MAJOR.MINOR"`. Bump MAJOR when a field is removed, or
its Python name or `client` name is renamed, or its `type` changes.
Bump MINOR when a field is added, or when only its `default` value
changes (a deliberate decision: `default` participates in the
fingerprint below, so a default-only edit is not free — it still
needs a MINOR bump and a new history row. This is stricter than
`schemaGuard.ts::compareSchemas`, which never looks at `default` when
deciding compatibility; that is fine, because a version bump is cheap
paperwork while a missed compatibility break is not — the two rules
are allowed to disagree on what is worth *recording*).

The history file
-----------------
`ppxai/engine/app_state_schema_history.json` is an append-only list of
`{"version": ..., "fields": [[python_name, client, type,
default_as_json], ...]}` rows, one per version that has ever been
recorded (starting at "1.1" — see the docstring in `app_state.py` for
why "1.0" is not reconstructable). A field-adder bumps the schema
version, adds a new row here, and pins that row's fingerprint hash in
`PINNED_FINGERPRINTS` below (see `TestRowsAreImmutable`) — that pairing
is what makes a prior row's later edit visible: the JSON file alone
cannot prove it was not silently rewritten, but the JSON file
disagreeing with a hash hardcoded in THIS test file can.

What this module checks, and why each check exists
----------------------------------------------------
1. `TestHistoryShapeAndOrdering` — versions are strictly increasing,
   no duplicates.
2. `TestCurrentSchemaMatchesLastRow` — the LIVE schema's version and
   field shape must equal the LAST history row exactly. This is what
   catches "the fingerprint changed but version did not" (edit the
   schema, forget the bump: the live fields stop matching the last
   recorded row) and "the version changed without a new row" (bump
   the version, forget the row: same mismatch, other direction).
3. `TestRowsAreImmutable` — a HARDCODED fingerprint per recorded
   version. Editing a past row's `fields` in the JSON changes its
   fingerprint, which no longer matches the literal pinned here —
   caught without needing git archaeology ("as far as a test can").
4. `TestBumpSizeIsSufficient` — for every adjacent pair of recorded
   rows, the bump between them must be at least as large as
   `required_bump()` says the field-shape change demands (a removal
   recorded across only a MINOR step fails).
5. `TestFingerprintGuards` / `TestRequiredBumpGuards` /
   `TestMutationEndToEnd` — the fingerprint and bump-classification
   functions proven correct on scratch data (order-insensitive,
   sensitive to each of name/client/type/default, positive control,
   and the exact mutation scenarios the task calls out: add a field
   without a bump, remove a field with only a MINOR bump, a correct
   bump passing). None of these touch the tracked schema or history
   files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "ppxai" / "engine" / "app_state_schema.json"
HISTORY_PATH = ROOT / "ppxai" / "engine" / "app_state_schema_history.json"


# ---------------------------------------------------------------------------
# Pure helpers — no I/O. Proven correct in isolation below before being
# trusted against the real tracked files.
# ---------------------------------------------------------------------------

def field_triples(fields: dict) -> list[tuple]:
    """`[(python_name, client, type, default_json), ...]`, sorted by
    python name for a stable, diffable file order. `default` is
    serialized via `json.dumps(..., sort_keys=True)` so it hashes and
    compares the same way regardless of dict-key insertion order."""
    out = [
        (name, spec["client"], spec["type"], json.dumps(spec["default"], sort_keys=True))
        for name, spec in fields.items()
    ]
    out.sort(key=lambda t: t[0])
    return out


def fingerprint(triples) -> str:
    """Order-insensitive, content-sensitive hash over a field-triple list."""
    ordered = sorted(tuple(t) for t in triples)
    blob = json.dumps(ordered, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def parse_version(v: str) -> tuple[int, int]:
    major_s, _, minor_s = v.partition(".")
    return int(major_s), int(minor_s)


def required_bump(prev_fields, cur_fields) -> str:
    """The SMALLEST bump the rule permits going from `prev_fields` to
    `cur_fields` (both field-triple lists, as `field_triples()` or a
    history row's `"fields"` produces). Returns 'major' | 'minor' | 'none'.

    Identity is the PYTHON name. A python-name rename is therefore
    structurally indistinguishable from a remove-and-add of two
    unrelated fields — that is fine, because the rule requires MAJOR
    for both, so they don't need to be told apart to be enforced
    correctly.
    """
    prev = {t[0]: tuple(t[1:]) for t in prev_fields}
    cur = {t[0]: tuple(t[1:]) for t in cur_fields}

    removed = set(prev) - set(cur)
    added = set(cur) - set(prev)
    both = set(prev) & set(cur)
    changed = {name for name in both if prev[name][:2] != cur[name][:2]}  # client or type
    default_only_changed = {
        name for name in (both - changed) if prev[name][2] != cur[name][2]
    }

    if removed or changed:
        return "major"
    if added or default_only_changed:
        return "minor"
    return "none"


def bump_class(prev_version: str, cur_version: str) -> str:
    """What bump ACTUALLY happened between two recorded version strings."""
    pmaj, pmin = parse_version(prev_version)
    cmaj, cmin = parse_version(cur_version)
    if cmaj > pmaj:
        return "major"
    if cmaj == pmaj and cmin > pmin:
        return "minor"
    return "none"


_BUMP_RANK = {"none": 0, "minor": 1, "major": 2}


def bump_is_sufficient(prev_row: dict, cur_row: dict) -> bool:
    need = required_bump(prev_row["fields"], cur_row["fields"])
    got = bump_class(prev_row["version"], cur_row["version"])
    return _BUMP_RANK[got] >= _BUMP_RANK[need]


# ---------------------------------------------------------------------------
# I/O helpers for the real tracked files.
# ---------------------------------------------------------------------------

def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_history() -> list[dict]:
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1 — history shape
# ---------------------------------------------------------------------------

class TestHistoryShapeAndOrdering:
    def test_history_is_nonempty(self):
        assert _load_history(), "app_state_schema_history.json has no rows"

    def test_versions_strictly_increase(self):
        history = _load_history()
        versions = [row["version"] for row in history]
        parsed = [parse_version(v) for v in versions]
        assert parsed == sorted(parsed), (
            f"history rows are not in strictly increasing version order: {versions}"
        )

    def test_no_duplicate_versions(self):
        versions = [row["version"] for row in _load_history()]
        assert len(set(versions)) == len(versions), (
            f"duplicate version rows in app_state_schema_history.json: {versions}"
        )


# ---------------------------------------------------------------------------
# 2 — the live schema must match the last recorded row
# ---------------------------------------------------------------------------

class TestCurrentSchemaMatchesLastRow:
    def test_schema_version_equals_last_history_row(self):
        schema = _load_schema()
        history = _load_history()
        assert schema["version"] == history[-1]["version"], (
            f"ppxai/engine/app_state_schema.json version "
            f"({schema['version']!r}) does not match the last row of "
            f"app_state_schema_history.json ({history[-1]['version']!r}). "
            "Either the version changed with no new row (add one), or a "
            "row was added/edited with a version the schema doesn't carry."
        )

    def test_schema_fields_match_the_last_row_exactly(self):
        """Catches 'the fingerprint changed but version did not': if the
        live schema's fields disagree with what the last row recorded,
        whoever edited the schema forgot to bump the version and record
        a new row for the new shape."""
        schema = _load_schema()
        history = _load_history()
        last_row = history[-1]
        actual = set(map(tuple, field_triples(schema["fields"])))
        recorded = set(map(tuple, last_row["fields"]))
        assert actual == recorded, (
            f"ppxai/engine/app_state_schema.json's fields do not match the "
            f"shape recorded for version {last_row['version']!r} in "
            "app_state_schema_history.json.\n"
            f"  in schema, not recorded: {sorted(actual - recorded)}\n"
            f"  recorded, not in schema: {sorted(recorded - actual)}\n"
            "Bump the version per the rule in app_state_schema.json's "
            "description (and app_state.py's docstring), add a NEW row to "
            "the history file, and pin its fingerprint in "
            "PINNED_FINGERPRINTS below. Never edit an existing row."
        )


# ---------------------------------------------------------------------------
# 3 — prior rows are immutable, pinned by a hardcoded hash per version
# ---------------------------------------------------------------------------

#: One entry per row in app_state_schema_history.json. Adding a history
#: row means adding its hash here in the SAME change — that pairing is
#: what makes editing the JSON alone insufficient to pass.
PINNED_FINGERPRINTS = {
    "1.1": "133a9c40400cf91881d2d6a7ea42e4ae8f7539e05678fbbfea67a73fb07aa3aa",
}


class TestRowsAreImmutable:
    def test_recorded_and_pinned_versions_match_exactly(self):
        recorded = {row["version"] for row in _load_history()}
        pinned = set(PINNED_FINGERPRINTS)
        assert recorded == pinned, (
            "app_state_schema_history.json rows and this test's "
            "PINNED_FINGERPRINTS must name exactly the same versions.\n"
            f"  recorded: {sorted(recorded)}\n"
            f"  pinned:   {sorted(pinned)}\n"
            "A new history row needs a new pinned hash added in the same "
            "change; a row that no longer exists needs its pin removed."
        )

    def test_every_row_fingerprint_matches_its_pin(self):
        for row in _load_history():
            expected = PINNED_FINGERPRINTS[row["version"]]
            actual = fingerprint(row["fields"])
            assert actual == expected, (
                f"version {row['version']!r}'s fields in "
                "app_state_schema_history.json no longer match the "
                "fingerprint pinned in this test file. A prior row must "
                "never be edited after being recorded — add a NEW row "
                "(with a version bump) instead of changing this one.\n"
                f"  pinned: {expected}\n  actual: {actual}"
            )


# ---------------------------------------------------------------------------
# 4 — every recorded transition bumped enough
# ---------------------------------------------------------------------------

class TestBumpSizeIsSufficient:
    def test_each_recorded_transition_bumped_enough(self):
        history = _load_history()
        for prev_row, cur_row in zip(history, history[1:]):
            need = required_bump(prev_row["fields"], cur_row["fields"])
            got = bump_class(prev_row["version"], cur_row["version"])
            assert _BUMP_RANK[got] >= _BUMP_RANK[need], (
                f"{prev_row['version']} -> {cur_row['version']} changed the "
                f"schema enough to require a {need.upper()} bump (per the "
                "rule in app_state_schema.json's description), but the "
                f"actual version change was only {got.upper() if got != 'none' else 'NO bump'}."
            )


# ---------------------------------------------------------------------------
# 5 — guards: the primitives, proven on scratch data
# ---------------------------------------------------------------------------

def _f(*pairs):
    """`pairs` of `(name, client, type, default)` -> a field-triple list."""
    return [(n, c, t, json.dumps(d, sort_keys=True)) for n, c, t, d in pairs]


class TestFingerprintGuards:
    def test_order_insensitive(self):
        a = _f(("x", "cx", "string", ""), ("y", "cy", "boolean", False))
        b = list(reversed(a))
        assert fingerprint(a) == fingerprint(b)

    def test_sensitive_to_name(self):
        assert fingerprint(_f(("x", "cx", "string", ""))) != fingerprint(
            _f(("z", "cx", "string", ""))
        )

    def test_sensitive_to_client(self):
        assert fingerprint(_f(("x", "cx", "string", ""))) != fingerprint(
            _f(("x", "cy", "string", ""))
        )

    def test_sensitive_to_type(self):
        assert fingerprint(_f(("x", "cx", "string", ""))) != fingerprint(
            _f(("x", "cx", "number", 0))
        )

    def test_sensitive_to_default(self):
        assert fingerprint(_f(("x", "cx", "string", "a"))) != fingerprint(
            _f(("x", "cx", "string", "b"))
        )

    def test_positive_control_same_content_same_hash(self):
        a = _f(("x", "cx", "string", "v"), ("y", "cy", "integer", 0))
        b = _f(("y", "cy", "integer", 0), ("x", "cx", "string", "v"))
        assert fingerprint(a) == fingerprint(b)


class TestRequiredBumpGuards:
    def test_add_field_requires_minor(self):
        prev = _f(("a", "ca", "string", ""))
        cur = _f(("a", "ca", "string", ""), ("b", "cb", "string", ""))
        assert required_bump(prev, cur) == "minor"

    def test_remove_field_requires_major(self):
        prev = _f(("a", "ca", "string", ""), ("b", "cb", "string", ""))
        cur = _f(("a", "ca", "string", ""))
        assert required_bump(prev, cur) == "major"

    def test_rename_python_name_requires_major(self):
        prev = _f(("old_name", "cx", "string", ""))
        cur = _f(("new_name", "cx", "string", ""))
        assert required_bump(prev, cur) == "major"

    def test_rename_client_name_requires_major(self):
        prev = _f(("a", "ca", "string", ""))
        cur = _f(("a", "cb", "string", ""))
        assert required_bump(prev, cur) == "major"

    def test_retype_requires_major(self):
        prev = _f(("a", "ca", "string", ""))
        cur = _f(("a", "ca", "number", 0))
        assert required_bump(prev, cur) == "major"

    def test_default_only_change_requires_minor(self):
        prev = _f(("a", "ca", "string", "x"))
        cur = _f(("a", "ca", "string", "y"))
        assert required_bump(prev, cur) == "minor"

    def test_no_change_requires_none(self):
        prev = _f(("a", "ca", "string", "x"))
        cur = list(prev)
        assert required_bump(prev, cur) == "none"

    def test_removal_beats_simultaneous_addition(self):
        """A field removed AND a field added in the same change is still
        MAJOR — an addition never downgrades a removal's requirement."""
        prev = _f(("a", "ca", "string", ""))
        cur = _f(("b", "cb", "string", ""))
        assert required_bump(prev, cur) == "major"


class TestMutationEndToEnd:
    """The exact mutation scenarios the task calls out, run through the
    FULL pipeline (`required_bump` + `bump_class` + the rank comparison),
    entirely on scratch rows — the tracked files are never touched."""

    @staticmethod
    def _row(version, *pairs):
        return {"version": version, "fields": _f(*pairs)}

    def test_add_field_without_bump_fails(self):
        prev = self._row("1.1", ("a", "ca", "string", ""))
        cur = self._row("1.1", ("a", "ca", "string", ""), ("b", "cb", "string", ""))
        assert bump_is_sufficient(prev, cur) is False

    def test_remove_field_with_only_minor_bump_fails(self):
        prev = self._row("1.1", ("a", "ca", "string", ""), ("b", "cb", "string", ""))
        cur = self._row("1.2", ("a", "ca", "string", ""))
        assert bump_is_sufficient(prev, cur) is False

    def test_correct_minor_bump_passes(self):
        prev = self._row("1.1", ("a", "ca", "string", ""))
        cur = self._row("1.2", ("a", "ca", "string", ""), ("b", "cb", "string", ""))
        assert bump_is_sufficient(prev, cur) is True

    def test_correct_major_bump_passes(self):
        prev = self._row("1.2", ("a", "ca", "string", ""), ("b", "cb", "string", ""))
        cur = self._row("2.0", ("a", "ca", "string", ""))
        assert bump_is_sufficient(prev, cur) is True

    def test_a_bigger_than_needed_bump_is_fine(self):
        """The rule sets a floor, not an exact match: MAJOR for an
        additive-only change is stricter than required, and that's ok."""
        prev = self._row("1.1", ("a", "ca", "string", ""))
        cur = self._row("2.0", ("a", "ca", "string", ""), ("b", "cb", "string", ""))
        assert bump_is_sufficient(prev, cur) is True

    def test_default_only_change_needs_at_least_minor(self):
        prev = self._row("1.1", ("a", "ca", "string", "x"))
        cur = self._row("1.1", ("a", "ca", "string", "y"))
        assert bump_is_sufficient(prev, cur) is False
        cur_ok = self._row("1.2", ("a", "ca", "string", "y"))
        assert bump_is_sufficient(prev, cur_ok) is True
