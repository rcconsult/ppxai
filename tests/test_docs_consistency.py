"""Sentinel tests: documentation must not drift from the code it describes.

Companion to ``test_version_consistency.py``. That file pins version strings;
this one pins the *other* three things documentation has repeatedly gotten
wrong on this project:

1. **Retired command names.** ADR 0011 renamed the slash-command surface with
   NO aliases (``/agent`` -> ``/auto``, ``/agentrun(s)`` -> ``/run``,
   ``/task run`` -> direct launch, ``task show`` -> ``task get``,
   ``task ack`` -> ``task collect``). A doc telling a user to run a deleted
   command is worse than no doc.

2. **Broken relative links.** Docs get archived; the links to them do not get
   repointed. Every relative markdown link in an active doc must resolve.

3. **Phantom repo paths.** Directory trees and "the code lives here" prose in
   docs referenced ``ppxai/main.py``, ``ppxai/config.py``, ``ppxai/web/server.py``,
   ``scripts/install.sh`` and ``kubernetes/`` -- none of which exist.

Historical records are exempt by design: CHANGELOG entries, release notes,
ADRs and archived plans *should* name commands as they were at the time.
The exemption list is deliberately narrow -- if you find yourself adding to
it, ask whether the doc is really historical or just stale.
"""

import re
from functools import lru_cache
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent

# Docs that legitimately preserve old names / old paths: dated records of
# what was true then, not instructions for what to do now.
HISTORICAL = (
    "CHANGELOG.md",
    "docs/release-notes-",
    "docs/archive/",
    "docs/decisions/",          # ADRs are immutable records
    "docs/lessons/",            # lessons are *about* past hazards
    "docs/plan-",               # build-order records
    "docs/agent-platform-call-graphs.md",
    "docs/debt-inventory.md",
    "docs/TODO-routing.md",
    "docs/research/",
    ".claude/",                 # prompt templates, not user docs
)

# Sections of ROADMAP.md under "## Completed (vN.NN.x)" correctly use the
# names of that era. ROADMAP is checked for links but not command names.
COMMAND_CHECK_SKIP = HISTORICAL + ("ROADMAP.md",)


@lru_cache(maxsize=None)
def _active_docs(suffixes=(".md", ".html")):
    """Every tracked doc that is not a historical record.

    Cached: this walks the whole repo, and the suite's server smoke tests
    share the machine with it. Re-walking once per test added enough
    filesystem-stat load to push their timeout-based crash detection over
    the edge, so the corpus is read once and reused.
    """
    out = []
    for path in PROJECT_ROOT.rglob("*"):
        if path.suffix not in suffixes or not path.is_file():
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if any(seg in rel for seg in ("node_modules", ".venv", "graphify-out",
                                      "dist/", "build/", ".git/")):
            continue
        out.append((rel, path, path.read_text(encoding="utf-8", errors="ignore")))
    return tuple(out)


# ---------------------------------------------------------------------------
# 1. Retired command names (ADR 0011)
# ---------------------------------------------------------------------------

# Each pattern is anchored so it only fires on a *command invocation*, not on
# prose like "the agent platform" or paths like /v1/agent/task.
RETIRED_COMMANDS = [
    (re.compile(r"(?<![\w/-])/agent(?![\w/-])"), "/agent", "/auto"),
    (re.compile(r"(?<![\w/-])/agentruns?(?![\w/-])"), "/agentrun(s)", "/run"),
    (re.compile(r"(?<![\w/-])/tools\s+agent(?![\w-])"), "/tools agent", "/tools auto"),
    (re.compile(r"(?<![\w/-])/task\s+run(?![\w-])"), "/task run", "/task \"<desc>\" (direct launch)"),
    (re.compile(r"(?<![\w/-])/task\s+ack(?![\w-])"), "/task ack", "/task collect"),
    (re.compile(r"(?<![\w/-])/task\s+show(?![\w-])"), "/task show", "/task get"),
]


class TestNoRetiredCommandNames:
    """ADR 0011 renamed the command surface with no aliases."""

    def test_active_docs_use_current_command_names(self):
        violations = []
        for rel, _path, text in _active_docs():
            if any(seg in rel for seg in COMMAND_CHECK_SKIP):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                # A line that is explicitly documenting the rename is fine.
                if "ADR 0011" in line or "renamed" in line.lower():
                    continue
                for pattern, old, new in RETIRED_COMMANDS:
                    if not pattern.search(line):
                        continue
                    # A migration row names the old AND the new command on the
                    # same line ("| /agent | **/auto** |") -- that is the doc
                    # doing its job, not drift.
                    replacement = new.split()[0]
                    if replacement in line:
                        continue
                    violations.append(f"{rel}:{lineno} uses {old!r} (now {new!r})")
        assert not violations, (
            "Retired command names in active documentation:\n  "
            + "\n  ".join(violations)
            + "\n\nADR 0011 removed these with no aliases. Update the doc, or "
              "move it under a historical path if it is a dated record."
        )


# ---------------------------------------------------------------------------
# 2. Relative links must resolve
# ---------------------------------------------------------------------------

MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+?)(?:\s+\"[^\"]*\")?\)")
# Illustrative placeholders that are not meant to resolve.
PLACEHOLDER = re.compile(r"[<{]|path/to/|TARGET|DESCRIPTIVE-NAME")


class TestDocLinksResolve:
    """A link to an archived-away file is a dead end for the reader."""

    def test_relative_markdown_links_exist(self):
        broken = []
        for rel, path, text in _active_docs((".md",)):
            if "docs/archive/" in rel or ".venv" in rel:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for match in MD_LINK.finditer(line):
                    target = match.group(2)
                    if re.match(r"^(https?:|mailto:|#|data:|tel:)", target):
                        continue
                    if PLACEHOLDER.search(target):
                        continue
                    bare = target.split("#")[0].split("?")[0]
                    if not bare or "." not in bare and "/" not in bare:
                        continue
                    # Absolute paths are illustrative, not repo-relative.
                    if bare.startswith("/"):
                        continue
                    resolved = (path.parent / bare).resolve()
                    # Targets outside the repo are cross-repo or GitHub-relative
                    # (e.g. "../../releases", a sibling ppxai-sre checkout).
                    # This suite cannot speak to their existence.
                    if not resolved.is_relative_to(PROJECT_ROOT):
                        continue
                    if not resolved.exists():
                        broken.append(f"{rel}:{lineno} -> {target}")
        assert not broken, (
            "Broken relative links in documentation:\n  " + "\n  ".join(broken)
        )


# ---------------------------------------------------------------------------
# 3. Repo paths named in docs must exist
# ---------------------------------------------------------------------------

# Paths that docs have historically invented. Each must NOT reappear as a
# claimed-real path. Keyed by the wrong path -> where the real thing lives.
PHANTOM_PATHS = {
    "ppxai/main.py": "ppxai/rich/main.py",
    "ppxai/config.py": "ppxai/config/ (package)",
    "ppxai/themes.py": "ppxai/rich/themes.py",
    "ppxai/utils.py": "ppxai/rich/utils.py",
    "ppxai/commands.py": "ppxai/commands/ (package)",
    "ppxai/web/server.py": "ppxai/server/http.py",
    "ppxai/tui/renderer.py": "ppxai/rendering/textual_renderer.py",
    "ppxai/common/event_handler.py": "ppxai/rich/event_handler.py",
    "scripts/install.sh": "install.sh (repo root)",
}


class TestNoPhantomRepoPaths:
    """Docs must not name module paths that do not exist."""

    @pytest.mark.parametrize("phantom,real", sorted(PHANTOM_PATHS.items()))
    def test_phantom_path_absent_from_active_docs(self, phantom, real):
        # Guard the guard: if one of these ever becomes real, this test must
        # be updated rather than silently passing.
        assert not (PROJECT_ROOT / phantom).exists(), (
            f"{phantom} now exists — remove it from PHANTOM_PATHS."
        )
        hits = []
        for rel, _path, text in _active_docs((".md",)):
            if any(seg in rel for seg in HISTORICAL):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if phantom in line:
                    hits.append(f"{rel}:{lineno}")
        assert not hits, (
            f"Docs reference nonexistent {phantom!r} (real location: {real}):\n  "
            + "\n  ".join(hits)
        )


# ---------------------------------------------------------------------------
# 4. Config keys named in docs must be read by production code
# ---------------------------------------------------------------------------

# Keys that shipped in config and/or docs but have no reader. Documenting a
# knob that does nothing is worse than omitting it: the user believes they
# have control they do not have. Listed here so that WIRING one of them up
# forces a deliberate removal from this list.
KNOWN_INERT_KEYS = {
    "checkpoint_message": "hardcoded in ppxai/checkpoint.py::create_checkpoint",
    "require_consent": "consent is always required; never read",
    "default_runtime": "container runtime is hardcoded docker-then-podman",
}


# ADR 0010 (v1.19.1) moved these off `tools.agent.*` as a CLEAN BREAK — no
# dual-read. Because nothing reads the old locations any more, a doc or
# config sample left at the old path fails SILENTLY: the operator sets a key
# that is simply ignored. These sentinels make that silence loud.
ADR_0010_MOVED_KEYS = {
    "task_tier_enabled": "execution.task.enabled",
    "spawn_consent": "execution.task.consent.spawn_consent",
    "consent_ttl_s": "execution.task.consent.consent_ttl_s",
    "result_retention_s": "execution.task.budgets.result_retention_s",
    "default_subagent": "execution.default_subagent",
}


class TestAdr0010MigrationStaysComplete:
    """The tier keys must not drift back onto the `tools.agent.*` axis."""

    def test_config_accessor_does_not_resurface_tier_keys(self):
        """`get_agent_config()` must expose only tool-intrinsic loop knobs.

        Re-adding a tier key here would silently reinstate the pre-ADR-0010
        shape for every one of its call sites at once.
        """
        from ppxai.config.tools import get_agent_config

        surfaced = set(get_agent_config()) & set(ADR_0010_MOVED_KEYS)
        assert not surfaced, (
            f"tools.agent config resurfaced tier key(s) {sorted(surfaced)}. "
            "These belong on the execution axis (ADR 0010); see "
            "config/execution.py::get_execution_task_config."
        )

    def test_sandbox_is_not_read_from_tools_agent(self):
        from ppxai.config.tools import get_agent_config

        assert "sandbox" not in get_agent_config(), (
            "tools.agent.sandbox moved to execution.task.sandbox (ADR 0010)."
        )

    @pytest.mark.parametrize("old,new", sorted(ADR_0010_MOVED_KEYS.items()))
    def test_active_docs_do_not_use_legacy_path(self, old, new):
        """No active doc may still tell operators to set `tools.agent.<old>`."""
        stale = []
        for path in (PROJECT_ROOT / "docs").rglob("*"):
            if path.suffix not in (".md", ".html") or not path.is_file():
                continue
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            # Frozen or necessarily-both-sided documents:
            #  - archives and per-version release notes record what a PAST
            #    version shipped; rewriting them would falsify history.
            #  - the ADR itself, and any doc annotating "was X, now Y", must
            #    be able to name the old path to describe the migration.
            if (
                rel.startswith("docs/archive/")
                or rel.startswith("docs/release-notes-")
                or "0010-config-shape-review" in rel
            ):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            # A mention that DOCUMENTS the move is fine; only a mention that
            # still instructs an operator to use the old path is stale. Both
            # allowed forms must also name the new path, so a bare legacy
            # reference always fails.
            if new in text:
                # (a) prose provenance — "... was `tools.agent.X`"
                if re.search(
                    rf"(was|moved from|shipped as|formerly)\s+`?tools\.agent\.{re.escape(old)}`?",
                    text,
                ):
                    continue
                # (b) a migration table row mapping old -> new on one line,
                #     e.g. "| `tools.agent.X` | `execution.task.Y` |" or
                #     "tools.agent.X  ->  execution.task.Y".
                if re.search(
                    rf"tools\.agent\.{re.escape(old)}`?\s*(\||->|→|=>)[^\n]*{re.escape(new)}",
                    text,
                ):
                    continue
            if f"tools.agent.{old}" in text:
                stale.append(rel)
        assert not stale, (
            f"{stale} still document `tools.agent.{old}`, which nothing reads "
            f"since v1.19.1. Use `{new}` (ADR 0010 — clean break, no dual-read)."
        )


class TestInertConfigKeysStayDocumented:
    """If an inert key gets wired up, this test fails so the docs get updated."""

    @pytest.mark.parametrize("key,why", sorted(KNOWN_INERT_KEYS.items()))
    def test_key_is_still_inert(self, key, why):
        readers = []
        for path in (PROJECT_ROOT / "ppxai").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            # A "reader" pulls the key out of a dict/config, not just defines it.
            if re.search(rf"""\.get\(\s*["']{re.escape(key)}["']""", text):
                readers.append(path.relative_to(PROJECT_ROOT).as_posix())
        # config/tools.py parses these into the config dict; that is not a
        # consumer. Anything else reading them means the key went live.
        readers = [r for r in readers if r != "ppxai/config/tools.py"]
        assert not readers, (
            f"Config key {key!r} is now read by {readers} but was documented as "
            f"inert ({why}). Update the docs that call it non-functional and "
            f"remove it from KNOWN_INERT_KEYS."
        )
