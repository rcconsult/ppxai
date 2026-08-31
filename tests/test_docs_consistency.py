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

4. **A shipped feature described as unshipped.** T8b put ``/task`` and ``/run``
   in every client on 2026-08-08; nine active docs still said "web + VSCode
   only" or "T8b is parked" a week later, each phrased differently.

5. **Numbers and stamps that quietly rot.** CLAUDE.md's test count, model ids
   named in the README that were never in ``ppxai-config.json``, and
   ``**Version:**`` footers up to eight minor releases behind on guides
   linked as current.

The 2026-08-15 accuracy sweep found the ADR-0010 key check was scanning only
``docs/``, so three live references to a retired config key survived in
``README.md``, ``scripts/`` and ``.claude/``. That check now runs over a
wider corpus (see ``_adr0010_corpus``) with its own exemption list, because
a skill file and a README instruct an operator exactly as a guide does.

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
    "docs/TODO-",               # sweep/routing trackers quote the bad strings
    "docs/research/",
    ".claude/",                 # prompt templates, not user docs
)

# The ADR-0010 key check uses its own exemption list, NOT ``HISTORICAL``:
# `.claude/` skill files DO instruct an operator (a stale key hid in one),
# so they stay in scope, while plans, handoffs and lessons must be able to
# name the old path because they are *about* the migration.
ADR0010_EXEMPT = (
    "CHANGELOG.md",
    "docs/release-notes-",
    "docs/archive/",
    "docs/decisions/",
    "docs/lessons/",
    "docs/plan-",
    "docs/handoff-",
    "docs/debt-inventory.md",
    "docs/TODO-",
    "docs/research/",
    "docs/agent-platform-call-graphs.md",
)

# Sections of ROADMAP.md under "## Completed (vN.NN.x)" correctly use the
# names of that era. ROADMAP is checked for links but not command names.
COMMAND_CHECK_SKIP = HISTORICAL + ("ROADMAP.md",)


#: Directories whose contents are never tracked docs. Pruned by path BEFORE
#: any filesystem stat: a dangling symlink under node_modules (npm leaves
#: these behind) raises OSError on is_file() under Windows, so a filter
#: applied afterwards never runs.
_PRUNED_SEGMENTS = ("node_modules", ".venv", "graphify-out",
                    "dist/", "build/", ".git/")


def _is_pruned(rel: str) -> bool:
    return any(seg in rel for seg in _PRUNED_SEGMENTS)


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
        if path.suffix not in suffixes:
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        # Prune BEFORE any stat: node_modules carries dangling npm symlink
        # stubs that raise WinError 1920 on is_file() (Windows returns
        # ERROR_CANT_ACCESS_FILE for a reparse point whose target is gone).
        # Filtering after the stat crashed the whole walk on a repo that had
        # simply run `npm install`.
        if _is_pruned(rel):
            continue
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue  # unreadable build artifact, never a tracked doc
        out.append((rel, path, text))
    return tuple(out)


@lru_cache(maxsize=None)
def _adr0010_corpus():
    """Files that may instruct an operator to set a config key.

    Deliberately WIDER than ``docs/``. The ADR-0010 key check used to scan
    only ``docs/``, so three live references to the retired tier key
    survived the migration in ``README.md``, ``scripts/gateway-smoke.py``
    and ``.claude/skills/build-install/SKILL.md`` -- found by hand in the
    2026-08-15 accuracy sweep, which is exactly the drift this test exists
    to make impossible. An operator reads a README and a skill file the
    same way they read a guide.
    """
    out = []
    for path in PROJECT_ROOT.rglob("*"):
        if path.suffix not in (".md", ".html", ".py"):
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        # Prune BEFORE the is_file() stat -- see _active_docs for why.
        if _is_pruned(rel) or "tests/" in rel:
            continue
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        if any(seg in rel for seg in ADR0010_EXEMPT):
            continue
        top = rel.split("/")[0]
        if top not in ("docs", "scripts", ".claude") and "/" in rel:
            continue  # nested source trees; config keys are not taught there
        out.append((rel, path))
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
    "sandbox": "execution.task.sandbox",
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
        for rel, path in _adr0010_corpus():
            # Frozen and both-sided files are already excluded by the corpus
            # helper (archives, per-version release notes, the ADR itself,
            # CHANGELOG) -- they must be able to name the old path to
            # describe the migration.
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


# ---------------------------------------------------------------------------
# 5. T8b shipped: no doc may re-park it or re-split the client surface
# ---------------------------------------------------------------------------

SURFACE_SPLIT = re.compile(r"web\s*\+\s*VSCode\s+only", re.I)
T8B_PARKED = re.compile(r"T8b[^\n]{0,80}\bparked\b|\bparked\b[^\n]{0,80}T8b", re.I)


class TestT8bIsNotReParked:
    """`/task` + `/run` ship in all four clients since 2026-08-08.

    Nine active docs asserted the opposite for a week after the port
    landed, because the claim was phrased differently in each of them.
    The real constraint is per-VERB (`launch`/`resume` need a live event
    loop, so the Rich TUI declines those two) and never per-client.
    """

    def test_no_doc_claims_web_vscode_only(self):
        hits = [rel for rel, _p, text in _active_docs()
                if not any(seg in rel for seg in COMMAND_CHECK_SKIP)
                and SURFACE_SPLIT.search(text)]
        assert not hits, (
            f"{hits} still claim /run + /task are 'web + VSCode only'. T8b "
            f"shipped: they register in ppxai/commands/factory.py for every "
            f"client. Only `launch`/`resume` are gated, on a live event loop."
        )

    def test_no_doc_says_t8b_is_parked(self):
        hits = [rel for rel, _p, text in _active_docs()
                if not any(seg in rel for seg in COMMAND_CHECK_SKIP)
                and T8B_PARKED.search(text)]
        assert not hits, (
            f"{hits} still describe T8b as parked. It was unparked "
            f"2026-08-08 and shipped via the in-process embed "
            f"(ppxai/engine/task_runner.py)."
        )


# ---------------------------------------------------------------------------
# 6. CLAUDE.md's stated test count must track the suite
# ---------------------------------------------------------------------------

class TestStatedTestCountTracksSuite:
    """CLAUDE.md's test count went 301 stale before anyone noticed.

    Collection can't be run from inside the suite, so this compares against
    the number of test *functions*, which is a hard lower bound (parametrize
    only ever multiplies). It catches the count going structurally stale --
    a claim below the function count is impossible, and one far above it
    means whole suites were deleted. It deliberately does NOT catch small
    drift; the README badge is exempt entirely, since it trails by design
    and `/release` owns it.
    """

    def test_claude_md_count_is_plausible(self):
        text = (PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        # Tolerate a richer bold span than "**N collected**" -- the line now
        # also carries passed/skipped/failed, which is the more useful claim
        # (a bare "collected" count let a suite with a permanent hang look
        # healthy). Only the leading number is load-bearing here.
        m = re.search(r"Tests:\s*\*\*([\d,]+)\s+collected", text)
        assert m, (
            "CLAUDE.md lost its 'Tests: **N collected**' line. Keep it "
            "greppable -- this sentinel and every future reader depend on it."
        )
        stated = int(m.group(1).replace(",", ""))

        n_funcs = 0
        for path in (PROJECT_ROOT / "tests").rglob("*.py"):
            n_funcs += len(re.findall(
                r"^\s*(?:async\s+)?def\s+test_", path.read_text(
                    encoding="utf-8", errors="ignore"), re.M))

        assert stated >= n_funcs, (
            f"CLAUDE.md claims {stated:,} tests collected but the suite "
            f"defines {n_funcs:,} test functions, and collection can never "
            f"be below the function count. Re-run "
            f"`uv run pytest tests/ --collect-only -q` and update it."
        )
        assert stated <= n_funcs * 2, (
            f"CLAUDE.md claims {stated:,} tests against only {n_funcs:,} "
            f"test functions. Either whole suites were deleted or the "
            f"number is fiction; re-collect and update it."
        )


# ---------------------------------------------------------------------------
# 7. Model ids named in the README must exist in the shipped catalog
# ---------------------------------------------------------------------------

MODEL_ID = re.compile(r"\b(gpt-[0-9][\w.-]*|gemini-[0-9][\w.-]*|gemma-[0-9][\w.-]*)")


class TestReadmeModelsExistInConfig:
    """The README named four models that were never in `ppxai-config.json`.

    It advertised `gemini-2.5-pro` and `gpt-5.1-codex` (neither shipped) and
    told users to type `/model gemini-2.5-pro`, a model past its shutdown
    date. The README is an overview, not a migration note, so every model
    id it names must be one a user can actually select.
    """

    def test_every_readme_model_is_configured(self):
        import json

        cfg = json.loads((PROJECT_ROOT / "ppxai-config.json").read_text(
            encoding="utf-8"))
        known = set()
        for prov in (cfg.get("providers") or {}).values():
            for m in prov.get("models", []) or []:
                known.add(m if isinstance(m, str) else m.get("id", ""))
            if prov.get("default_model"):
                known.add(prov["default_model"])

        text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        named = {m.group(1).rstrip(".,);:") for m in MODEL_ID.finditer(text)}
        # Family names in prose ("GPT-5.4-mini/nano/pro") are not ids; only
        # flag lowercase, fully-qualified ids, which is how a user types them.
        named = {n for n in named if n.islower()}
        missing = sorted(named - known)
        assert not missing, (
            f"README.md names model id(s) {missing} that are not in "
            f"ppxai-config.json. A reader will type one and get an error. "
            f"Shipped ids: {sorted(known)}"
        )


# ---------------------------------------------------------------------------
# 8. Version stamps: current, or explicitly open-ended
# ---------------------------------------------------------------------------

VERSION_STAMP = re.compile(
    r"^\*\*(?:Document\s+)?Version:?\*\*:?\s*v?(\d+\.\d+\.\d+)(\+?)", re.M)


class TestVersionStampsAreNotStale:
    """A bare `**Version:** v1.11.2` on a live guide reads as "last true then".

    Guides carried stamps up to eight minor versions behind while being
    linked as current. The fix is not to bump them mechanically: a stamp
    means one of two things, so say which. `vX.Y.Z+` = "applies from here
    onward" and never goes stale; a bare `vX.Y.Z` is a claim about the
    CURRENT release and must equal it.
    """

    def test_bare_version_stamps_match_current_release(self):
        from ppxai.version import __version__

        stale = []
        for rel, _path, text in _active_docs(suffixes=(".md",)):
            # docs/ guides only. THIRD_PARTY_LICENSES.md stamps *dependency*
            # versions, and benchmark records are dated by design -- neither
            # is a claim about which ppxai release the text describes.
            if not rel.startswith("docs/") or any(s in rel for s in HISTORICAL):
                continue
            for m in VERSION_STAMP.finditer(text):
                ver, open_ended = m.group(1), m.group(2)
                if not open_ended and ver != __version__:
                    stale.append(f"{rel} (v{ver})")
        assert not stale, (
            f"{stale} carry a bare version stamp that is not the current "
            f"release (v{__version__}). Either bump it, or mark it "
            f"open-ended as `vX.Y.Z+` if the doc applies from that version "
            f"onward."
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


class TestEveryLessonIsDiscoverable:
    """A lesson absent from the index cannot be found by the reader it is for.

    CLAUDE.md tells every agent to "Read docs/lessons/README.md first", so the
    README is the discovery path for the whole directory. A lesson missing
    from it is reachable only by someone who already went looking in
    `docs/lessons/` — the population that least needs telling.

    That is the same shape as the hazards the directory documents: a file that
    exists but cannot be found reads identically to a file that was never
    written. Nothing enforced the convention, and two lessons had drifted out
    of the index by 2026-08-31 (`mutation-tests-that-never-ran.md`, added that
    day, and `sdk-validation-is-not-api-acceptance.md`, which had been
    unlisted for longer) with the docs suite green throughout.
    """

    @staticmethod
    def _lessons():
        root = Path(__file__).resolve().parents[1] / "docs" / "lessons"
        return sorted(
            p for p in root.glob("*.md") if p.name != "README.md"
        )

    def test_the_lesson_set_is_not_empty(self):
        """A glob that silently matches nothing passes this whole class."""
        found = self._lessons()
        assert len(found) >= 10, f"expected the lessons directory, found {found}"

    def test_lesson_filenames_are_kebab_case(self):
        """The convention the scan below RELIES on, made explicit.

        `test_the_readme_does_not_name_lessons_that_are_gone` finds `*.md`
        tokens with a lowercase-kebab pattern. A file named `GHOST.md` would
        therefore be invisible to it — the token captures nothing, `named`
        stays empty, and the check passes without having looked. That is the
        same species as an empty glob, one level down.

        Two ways to fix it: widen the scan, or make its assumption true.
        Asserting the convention is better, because the convention already
        holds for all 17 lessons and was previously implicit — this turns
        "everyone happens to do it" into a rule a new file must follow, and
        the scan's pattern into something guaranteed rather than hoped for.
        (The scan is ALSO case-insensitive now, so the two are independent:
        neither silently depends on the other.)
        """
        bad = [
            p.name for p in self._lessons()
            if not re.match(r"^[a-z0-9][a-z0-9-]*\.md$", p.name)
        ]
        assert not bad, (
            f"lesson filenames must be lowercase kebab-case: {bad}\n"
            "Anything else is skipped by the index scan in this class and "
            "reads inconsistently in the directory listing."
        )

    def test_every_lesson_is_listed_in_the_readme(self):
        root = Path(__file__).resolve().parents[1] / "docs" / "lessons"
        index = (root / "README.md").read_text(encoding="utf-8")
        missing = [p.name for p in self._lessons() if p.name not in index]
        assert not missing, (
            "lessons not listed in docs/lessons/README.md:\n  "
            + "\n  ".join(missing)
            + "\n\nCLAUDE.md points every agent at that README, so an "
            "unlisted lesson is invisible to the reader it was written for. "
            "Add a one-line entry under ## Index."
        )

    def test_the_readme_does_not_name_lessons_that_are_gone(self):
        """A renamed lesson leaves a dead entry, and the reader finds nothing.

        Scoped deliberately to what `TestDocLinksResolve` does NOT cover.
        That test already fails on a dangling *markdown link* anywhere in the
        repo — measured: deselect this class and it still catches
        `[ghost](ghost.md)` in this README on its own. So checking linked
        targets here would be pure duplication.

        What neither covers is a **bare filename mention**: this index's
        entries are prose as much as links, and `- old-name.md — ...` after a
        rename is a dead reference with no link syntax for the repo-wide test
        to find. Measured before writing this: a bare `ghost-lesson.md` line
        passed all 30 tests.

        **What this deliberately does NOT catch**, so the next reader does not
        mistake the line for an oversight: the exclusion below is repo-wide,
        which excuses ~280 distinct `.md` basenames. A lesson renamed away
        whose old basename *collides* with any other `.md` in the repo slips
        through in bare-mention form — measured: a bare `architecture.md`
        line passes, because `docs/architecture.md` exists. Its linked form
        is still caught by `TestDocLinksResolve` from the other side.

        Left open on purpose. No current lesson basename is duplicated
        anywhere outside this directory (measured: zero collisions across 17
        lessons and 280 other basenames), so no real rename can hit it today;
        it opens only if someone names a future lesson after an existing repo
        file. The alternative — an allowlist of the prose citations this
        index legitimately makes — trades a broad, self-maintaining exclusion
        for a hand-maintained list, and a hand-maintained list is the thing
        that rots. "Exists somewhere in the repo" is the deliberate line.
        """
        root = Path(__file__).resolve().parents[1] / "docs" / "lessons"
        index = (root / "README.md").read_text(encoding="utf-8")
        present = {p.name for p in self._lessons()} | {"README.md"}
        # Every `*.md` token the index names, however it names it.
        # Case-insensitive and underscore-aware so a name outside the kebab
        # convention is still SEEN here rather than silently skipped — the
        # convention is enforced by its own test above, and this scan does
        # not quietly depend on it holding.
        named = {
            m.lower()
            for m in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*\.md", index)
        }
        present = {n.lower() for n in present}
        # The index legitimately cites files OUTSIDE this directory in prose
        # (AGENTS.md, CLAUDE.md, docs/mcp-integration-plan.md). Those are not
        # dangling lesson references, and treating them as such was a false
        # positive this scan produced the moment it was widened. Anything that
        # exists somewhere in the repo is somebody else's file; only a name
        # that exists NOWHERE is a lesson that went away.
        repo = Path(__file__).resolve().parents[1]
        elsewhere = {q.name.lower() for q in repo.rglob("*.md")
                     if ".venv" not in q.parts and "node_modules" not in q.parts}
        dangling = sorted(named - present - elsewhere)
        assert not dangling, (
            "docs/lessons/README.md names lesson files that do not exist: "
            f"{dangling}\n\nA renamed or deleted lesson leaves the old name "
            "behind; a reader following it finds nothing."
        )
