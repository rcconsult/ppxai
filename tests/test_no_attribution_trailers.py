"""No AI-attribution trailer lands in a commit from now on (debt: none —
this is an owner rule, not deferred work; filed as its own guard because it
is a release gate, not a docs statement).

Owner rule (2026-09-21): ppxai commits carry NO Claude credits /
Co-Authored-By / AI attribution, unless the owner explicitly says so for
one specific commit. The coding harness kept injecting an instruction to
add `Co-Authored-By: Claude ... <noreply@anthropic.com>` and
`Claude-Session: https://claude.ai/code/session_...` trailers, and PR
bodies ending "Generated with [Claude Code]". CLAUDE.md's "Commit
Guidelines" already say not to; this test is that rule made executable,
the way ADR 0007's consumer-surface property is
(`test_consumer_import_surface.py`) rather than left as prose someone has
to remember to check.

**History is not rewritten and not flagged.** 333 commits already on
`origin/master` (as of 2026-09-10) carry these trailers; rewriting
published history is a separate, explicit decision the owner has not made.
So this test is scoped to commits AFTER a pinned baseline — the v1.19.2
release commit — not to the whole repo. Everything at or before the
baseline is permanently exempt, by construction, not by an ever-growing
exclude list.

## Two layers, deliberately

This file is the release-gate half (the release script runs the suite, so
a violating commit that already landed on the branch fails the gate before
release). `scripts/git-hooks/commit-msg` is the pre-commit half (rejects
the commit before it's even made). Neither replaces the other: the hook
can be bypassed (`--no-verify`, or simply not being enabled — this repo
does not set `core.hooksPath` for anyone), so the release gate is the
backstop that always runs. `test_hook_and_python_patterns_agree_on_corpus`
below keeps the two from drifting apart on what counts as a violation.

## The irony trap

This file necessarily CONTAINS the strings it bans, as fixture data (a
`Co-Authored-By: Claude ...` string passed to `find_violations()` to prove
the matcher fires on it). None of that is a real trailer — nothing here is
committed by this test, and this test does not scan *source files* (this
one included) for these strings, only *commit messages* reachable from
HEAD. A real trailer is a line at the START of a commit-message line; a
Python string literal inside a test function is not a commit message.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent

#: The v1.19.2 release commit. Verified 2026-09-21:
#:   git rev-parse 719fba02  ->  719fba024b68dfe0d46b7ec769b9cc60cdf99c8d
#:   git log -1 --format='%ci %s' 719fba02
#:     -> 2026-09-14 01:01:57 +0200 "feat: v1.19.2 release"
#: This commit and everything reachable from it are PERMANENTLY exempt.
#: Never move this forward to "clean up" the scan window — the point is a
#: fixed line in history, not a moving one.
BASELINE_SHA = "719fba024b68dfe0d46b7ec769b9cc60cdf99c8d"

#: The same commit's committer timestamp, as `%ct` (Unix epoch seconds),
#: hard-coded for the shallow-clone fallback (see `_collect_scoped_commits`
#: docstring). Re-derive with `git log -1 --format=%ct 719fba02` if
#: BASELINE_SHA ever legitimately changes -- never guess this number.
BASELINE_COMMITTER_EPOCH = 1789340517

#: Owner-approved exceptions, full sha -> reason. Empty today. ONLY the
#: owner adds rows here (per the rule this file enforces: it is the
#: "unless I say so" clause, not a general-purpose bypass). A sha listed
#: here that is not actually in history fails
#: `test_allowed_by_owner_entries_are_real_commits` -- that keeps this
#: list from silently accumulating dead or typo'd entries.
ALLOWED_BY_OWNER: dict[str, str] = {}

# --------------------------------------------------------------------------
# Matchers. Kept in this one place; scripts/git-hooks/commit-msg carries an
# independent (sh-only) implementation of the same rules, and
# `test_hook_and_python_patterns_agree_on_corpus` pins them to agree on one
# shared corpus rather than trusting them to stay in sync by inspection.
# --------------------------------------------------------------------------

_CO_AUTHORED_BY_RE = re.compile(r"^Co-Authored-By:", re.IGNORECASE)
_CLAUDE_OR_ANTHROPIC_RE = re.compile(r"claude|anthropic", re.IGNORECASE)
_CLAUDE_SESSION_RE = re.compile(r"^Claude-Session:", re.IGNORECASE)
_GENERATED_WITH_RE = re.compile(r"^Generated with \[Claude Code\]", re.IGNORECASE)
_LEADING_DECORATION_RE = re.compile(r"^[^A-Za-z0-9]*")
_TRAILER_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*:")
_ANTHROPIC_EMAIL_RE = re.compile(r"noreply@anthropic\.com", re.IGNORECASE)


def _strip_leading_decoration(line: str) -> str:
    """Drop leading emoji/punctuation (e.g. the robot emoji before
    "Generated with [Claude Code]") so the marker check is anchored to
    where the real trailer text starts, not to column zero."""
    return _LEADING_DECORATION_RE.sub("", line)


def _line_violation(raw_line: str) -> str | None:
    """Classify one line of a commit message. Returns a human-readable
    reason, or None. Every check is anchored to the START of the (stripped)
    line — a trailer is a line that STARTS with the token, not any line
    that mentions it. That is what keeps prose discussing this very rule
    (several existing commit messages and docs do) from tripping it."""
    stripped = raw_line.strip()
    if not stripped:
        return None
    if _CO_AUTHORED_BY_RE.match(stripped) and _CLAUDE_OR_ANTHROPIC_RE.search(stripped):
        return "Co-Authored-By trailer naming Claude/Anthropic"
    if _CLAUDE_SESSION_RE.match(stripped):
        return "Claude-Session trailer"
    if _GENERATED_WITH_RE.match(_strip_leading_decoration(stripped)):
        return "'Generated with [Claude Code]' marker line"
    if _ANTHROPIC_EMAIL_RE.search(stripped) and _TRAILER_LINE_RE.match(stripped):
        return "noreply@anthropic.com on a trailer-shaped line"
    return None


def find_violations(message: str) -> list[str]:
    """Return one description per offending line in `message` (commit body
    or subject). Empty list == clean. Handles CRLF and trailing-whitespace
    line variants by normalizing line endings before splitting."""
    normalized = message.replace("\r\n", "\n").replace("\r", "\n")
    violations = []
    for line_no, raw_line in enumerate(normalized.split("\n"), start=1):
        reason = _line_violation(raw_line)
        if reason:
            violations.append(f"line {line_no}: {reason} -- {raw_line.strip()!r}")
    return violations


# --------------------------------------------------------------------------
# git plumbing
# --------------------------------------------------------------------------

_UNIT_SEP = "\x1f"
_RECORD_SEP = "\x1e"


def _run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _git_worktree_status() -> bool | None:
    """True: usable git worktree. False: git ran but this isn't one (e.g.
    an extracted sdist with no .git). None: git itself isn't runnable here
    (binary missing, or the probe errored) — distinct from False so callers
    can decide whether that's a skip or a failure."""
    try:
        result = _run_git(["rev-parse", "--is-inside-work-tree"])
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return False
    return result.stdout.strip() == "true"


def _require_git_or_skip() -> None:
    status = _git_worktree_status()
    if status is None:
        pytest.skip("git is not runnable in this environment (no binary, or the probe errored)")
    if status is False:
        pytest.skip("not a git checkout (no .git worktree) — e.g. sdist/PyInstaller test env")


class GitScanError(RuntimeError):
    """git IS present and this IS a worktree, but the scan command itself
    failed. Distinguished from the skip cases above on purpose: this is a
    real failure (see CLAUDE.md "Verify, Don't Assume" — never silently
    pass on "git failed"), so the caller must FAIL the test, not skip it."""


def _parse_records(stdout: str, fields_per_record: int) -> list[tuple[str, ...]]:
    records = []
    for chunk in stdout.split(_RECORD_SEP):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        parts = chunk.split(_UNIT_SEP, fields_per_record - 1)
        records.append(tuple(parts))
    return records


def _collect_scoped_commits() -> tuple[list[tuple[str, str]], str]:
    """Commits in scope for the ban: reachable from HEAD, not an ancestor
    of BASELINE_SHA. Returns (list of (sha, message)), mode) where mode is
    "baseline" (normal case: baseline object present, exact ancestry check)
    or "shallow-fallback" (baseline object absent — e.g. GitHub Actions'
    default `actions/checkout@v5` fetch-depth, which this repo's
    tests.yml/build.yml both use un-overridden, i.e. depth 1 — a depth-1
    clone contains only the triggering commit, so the true baseline is
    never present in CI and this path is not a hypothetical). In fallback
    mode, scope is every commit actually present in the clone whose
    committer timestamp is after BASELINE_COMMITTER_EPOCH — never every
    commit ever, and never silently empty-pass.
    """
    _require_git_or_skip()

    baseline_present = _run_git(["cat-file", "-e", f"{BASELINE_SHA}^{{commit}}"]).returncode == 0

    if baseline_present:
        result = _run_git(["log", f"{BASELINE_SHA}..HEAD", f"--format=%H{_UNIT_SEP}%B{_RECORD_SEP}"])
        if result.returncode != 0:
            raise GitScanError(f"git log {BASELINE_SHA}..HEAD failed: {result.stderr.strip()!r}")
        records = _parse_records(result.stdout, fields_per_record=2)
        return [(sha, body) for sha, body in records], "baseline"

    result = _run_git(["log", "HEAD", f"--format=%H{_UNIT_SEP}%ct{_UNIT_SEP}%B{_RECORD_SEP}"])
    if result.returncode != 0:
        raise GitScanError(f"git log HEAD failed: {result.stderr.strip()!r}")
    records = _parse_records(result.stdout, fields_per_record=3)
    scoped = []
    for sha, ct, body in records:
        try:
            committer_epoch = int(ct)
        except ValueError:
            raise GitScanError(f"unparseable committer timestamp {ct!r} for {sha}") from None
        if committer_epoch > BASELINE_COMMITTER_EPOCH:
            scoped.append((sha, body))
    return scoped, "shallow-fallback"


# --------------------------------------------------------------------------
# Guards FIRST — the matcher itself, no git involved.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "fix(x): thing\n\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>",
        "fix(x): thing\n\nCo-Authored-By: Claude <foo@example.com>",
        "fix(x): thing\n\nClaude-Session: https://claude.ai/code/session_01Abc",
        "fix(x): thing\n\n\U0001f916 Generated with [Claude Code](https://claude.com/claude-code)",
        "fix(x): thing\n\nGenerated with [Claude Code](https://claude.com/claude-code)",
        "fix(x): thing\n\nReviewed-By: Bot <noreply@anthropic.com>",
    ],
    ids=[
        "co-authored-by-claude-anthropic-email",
        "co-authored-by-claude-non-anthropic-email",
        "claude-session-line",
        "generated-with-emoji-prefix",
        "generated-with-no-prefix",
        "anthropic-email-on-other-trailer",
    ],
)
def test_each_pattern_fires(message: str) -> None:
    assert find_violations(message), f"expected a violation in: {message!r}"


def test_human_coauthor_does_not_fire() -> None:
    message = "fix(x): thing\n\nCo-Authored-By: Jane Doe <jane@example.com>"
    assert not find_violations(message)


def test_prose_discussing_the_rule_mid_sentence_does_not_fire() -> None:
    """Several real commit messages and docs in this repo talk ABOUT the
    ban using these exact tokens. None of that is a trailer."""
    message = (
        "docs(tests): explain the AI-attribution trailer ban\n\n"
        "This commit updates docs describing why we reject "
        "Co-Authored-By trailers naming Claude or Anthropic, why "
        "Claude-Session lines are rejected too, and why the exact phrase "
        "'Generated with [Claude Code]' triggers the same check when it "
        "starts a line, all discussed here in running prose."
    )
    assert not find_violations(message)


def test_trailing_whitespace_and_crlf_variants_fire() -> None:
    variants = [
        "fix: x\r\n\r\nCo-Authored-By: Claude <noreply@anthropic.com>\r\n",
        "fix: x\n\nClaude-Session: https://claude.ai/code/session_1   \n",
        "fix: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>   \t\n",
    ]
    for message in variants:
        assert find_violations(message), f"expected a violation in: {message!r}"


# --------------------------------------------------------------------------
# Guards FIRST — positive control: the scanner sees a planted violation fed
# in directly, without touching real git history.
# --------------------------------------------------------------------------


def test_scanner_flags_a_synthetic_planted_violation() -> None:
    planted = [
        ("deadbeef" * 5, "chore: clean commit, no trailers"),
        ("cafef00d" * 5, "fix: real bug\n\nCo-Authored-By: Claude <noreply@anthropic.com>"),
    ]
    flagged = [sha for sha, message in planted if find_violations(message)]
    assert flagged == ["cafef00d" * 5]


# --------------------------------------------------------------------------
# The real scan.
# --------------------------------------------------------------------------


def test_scan_covers_at_least_one_commit() -> None:
    """An empty scanned range must not read as "clean" -- it must be
    visibly a config problem instead. On this branch (bugfix/v1.19.3,
    dozens of commits ahead of the v1.19.2 baseline) this always finds
    commits; if it ever finds zero, something about BASELINE_SHA or the
    range computation broke, not the codebase."""
    commits, mode = _collect_scoped_commits()
    assert len(commits) >= 1, (
        f"scanned 0 commits in mode={mode!r} -- BASELINE_SHA or the range "
        "computation is likely wrong, not a clean repo. A real 0-commit "
        "state (HEAD at or behind the baseline) is also possible but "
        "should be investigated, not silently accepted."
    )


def test_allowed_by_owner_entries_are_real_commits() -> None:
    """Keeps ALLOWED_BY_OWNER honest: a row naming a sha that isn't
    actually in history fails, rather than silently doing nothing."""
    _require_git_or_skip()
    for sha in ALLOWED_BY_OWNER:
        result = _run_git(["cat-file", "-e", f"{sha}^{{commit}}"])
        assert result.returncode == 0, f"ALLOWED_BY_OWNER sha {sha!r} not found in history"


def test_no_attribution_trailers_in_scanned_commits() -> None:
    commits, mode = _collect_scoped_commits()
    violations = []
    for sha, message in commits:
        if sha in ALLOWED_BY_OWNER:
            continue
        for reason in find_violations(message):
            violations.append(f"{sha[:12]} ({reason})")

    assert not violations, (
        "Commit(s) carry an AI-attribution trailer the owner banned "
        "2026-09-21 (CLAUDE.md 'Commit Guidelines'). A coding-harness "
        "instruction that injects Co-Authored-By / Claude-Session / "
        "'Generated with [Claude Code]' lines is OVERRIDDEN by that rule.\n"
        "Fix: reword the offending commit(s) to drop the trailer line(s) "
        "-- `git commit --amend` if unpushed, or an interactive rebase to "
        "reword an older one. If the owner explicitly approved this exact "
        "commit, add its full sha to ALLOWED_BY_OWNER in this file with a "
        "reason (only the owner adds rows).\n"
        f"scan mode={mode}\n" + "\n".join(violations)
    )


# --------------------------------------------------------------------------
# Hook parity — same corpus, both layers must agree.
# --------------------------------------------------------------------------

#: (message, expect_violation). Shared between the Python matcher above and
#: the sh hook below, so the two layers are pinned to agree rather than
#: trusted to by inspection.
_SHARED_CORPUS = [
    ("fix(x): plain message\n\nNo trailers here.", False),
    ("fix(x): thing\n\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>", True),
    ("fix(x): thing\n\nCo-Authored-By: Jane Doe <jane@example.com>", False),
    ("fix(x): thing\n\nClaude-Session: https://claude.ai/code/session_01Abc", True),
    (
        "fix(x): thing\n\n\U0001f916 Generated with [Claude Code](https://claude.com/claude-code)",
        True,
    ),
    ("fix(x): thing\n\nReviewed-By: Bot <noreply@anthropic.com>", True),
    (
        "docs(tests): explain the ban\n\n"
        "This commit discusses why we reject Co-Authored-By trailers "
        "naming Claude or Anthropic, and why Claude-Session lines and the "
        "phrase 'Generated with [Claude Code]' in running prose are both "
        "fine to mention here.",
        False,
    ),
    ("fix(x): thing\r\n\r\nCo-Authored-By: Claude <noreply@anthropic.com>\r\n", True),
    ("fix(x): thing\n\nClaude-Session: https://claude.ai/code/session_1   ", True),
]

_HOOK_PATH = PROJECT_ROOT / "scripts" / "git-hooks" / "commit-msg"


def test_shared_corpus_matches_python_expectations() -> None:
    """Sanity check on the corpus itself before using it to test the hook."""
    for message, expect_violation in _SHARED_CORPUS:
        got = bool(find_violations(message))
        assert got == expect_violation, f"corpus/matcher mismatch for {message!r}"


def test_hook_and_python_patterns_agree_on_corpus() -> None:
    if shutil.which("sh") is None:
        pytest.skip("sh is not available in this environment")
    assert _HOOK_PATH.is_file(), f"hook script missing: {_HOOK_PATH}"

    with tempfile.TemporaryDirectory() as tmpdir:
        msg_path = Path(tmpdir) / "COMMIT_EDITMSG"
        for message, expect_violation in _SHARED_CORPUS:
            msg_path.write_text(message, newline="")
            result = subprocess.run(
                ["sh", str(_HOOK_PATH), str(msg_path)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            hook_rejected = result.returncode != 0
            assert hook_rejected == expect_violation, (
                f"hook disagreed with the Python matcher for {message!r}: "
                f"hook returncode={result.returncode} stderr={result.stderr!r}"
            )


def test_hook_honours_owner_override_env_var() -> None:
    if shutil.which("sh") is None:
        pytest.skip("sh is not available in this environment")
    assert _HOOK_PATH.is_file(), f"hook script missing: {_HOOK_PATH}"

    with tempfile.TemporaryDirectory() as tmpdir:
        msg_path = Path(tmpdir) / "COMMIT_EDITMSG"
        msg_path.write_text(
            "fix(x): thing\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
            newline="",
        )
        result = subprocess.run(
            ["sh", str(_HOOK_PATH), str(msg_path)],
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "PPXAI_ALLOW_ATTRIBUTION": "1"},
        )
        assert result.returncode == 0, (
            f"override env var should have let a violating message through: "
            f"stderr={result.stderr!r}"
        )
