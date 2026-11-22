"""Scope and nest a run listing (`/task ls`, `/run ls`).

Owner decision 2026-11-22: a listing shows only the active conversation's runs
unless `--all` is given (ADR 0018's `RunMeta.session_id`), optionally filtered
by `--status`, with sub-agents (`parent_run_id`) indented under their parent.

Pure data → data. The web and VSCode clients re-implement the same rules in
`task-controller.js` / `taskController.ts` (`scopeAndNest`), and
`tests/test_task_grammar_parity.py` holds the three to identical output.

A child whose parent is not in the listed set (filtered out by `--status`, out
of scope, or gone) is shown at top level rather than lost.
"""

from __future__ import annotations

from typing import Any


def scope_and_nest(
    runs: list[Any],
    *,
    session_id: str | None,
    all_sessions: bool,
    status: str | None = None,
) -> list[tuple[Any, int]]:
    """Return `(meta, depth)` rows: roots in input order, each followed by its
    children (depth 1). Default scope keeps runs whose `session_id` equals the
    active conversation; a run with no recorded conversation only passes with
    `all_sessions`."""
    kept = [
        r for r in runs
        if (all_sessions or (session_id is not None and r.session_id == session_id))
        and (status is None or r.status == status)
    ]
    ids = {r.run_id for r in kept}
    children: dict[str, list[Any]] = {}
    roots = []
    for r in kept:
        parent = getattr(r, "parent_run_id", None)
        if parent and parent in ids and parent != r.run_id:
            children.setdefault(parent, []).append(r)
        else:
            roots.append(r)
    rows: list[tuple[Any, int]] = []
    for root in roots:
        rows.append((root, 0))
        rows.extend((c, 1) for c in children.get(root.run_id, []))
    return rows
