"""The consumer import surface never drags in `ppxai.commands`.

A sister repo, ppxai-sre, consumes ppxai as an editable path dependency and
imports a small engine/config surface (see `PRODUCTION_IMPORTS` below). The
property it depends on: importing that surface loads ZERO `ppxai.commands`
modules — the command layer, and any import-time side effect it ever
acquires, must never reach an SDK embedder that only wants the engine.

ADR 0007 (docs/decisions/0007-completion-first-class-service.md,
"Re-measured status") MEASURED this by hand three times, and the
measurement decayed once — it cited a module that had already been
deleted. This test is that measurement made executable, so it decays by
failing a CI run instead of by going stale in prose.

Every other fence in this repo guards one EDGE per package
(`tests/test_no_new_lazy_imports.py`: engine imports no commands, config
imports no engine — see `RETAINED_ON_PURPOSE`/`BASELINE` there for the
sibling pattern). This one asserts the consumer's PROPERTY directly over
the real closure a fresh interpreter builds, so it fails no matter which
edge introduces the problem — including a brand-new package nobody wrote a
per-edge fence for. The motivating incident: commit ed3c069a deleted
`engine/model_profiles.py` deliberately, with no shim, and ppxai-sre's test
collection died with nothing upstream signalling it.

## Two copies, deliberately

ppxai-sre holds its OWN executable copy of this same property:
`libs/core/tests/test_ppxai_seam.py` (their commit d152000). That file is
the PEER fence, not the source of truth for this one — this file does not
read it, does not read anything from that repo, and does not need to: a
cross-repo file read would be a new coupling with no fence of its own, and
it would fail open the day their layout moves. The agreed rule between the
two repos is "every copy EXECUTABLE", not "one shared copy" — two
independent, executable copies fail independently, which is the point:
theirs runs against whatever ../ppxai happens to be checked out; this one
runs against changes they will not see for days.

Verified by hand against ppxai-sre's real imports on 2026-09-21 (grep of
`libs/core/src/ppxai_sre_core/*.py` for production code and
`libs/core/tests/test_ppxai_seam.py` for the seam-only tier): both pinned
lists below match exactly, no drift found.

## The two tiers

`PRODUCTION_IMPORTS` — what ppxai-sre's runtime imports.

`SEAM_ONLY_IMPORTS` — imported ONLY by ppxai-sre's seam test, never by
their runtime: COUPLING (a rename breaks their test suite), not DEPENDENCY
(their runtime never touches these). `TestSeamOnlyTierAddsNothingExtra`
below is what EARNS that label — it proves the two closures are the same
set of modules, rather than assuming it because the four names "sound
adjacent" to the production eight.

## `ppxai.engine.completion` is intentionally NOT asserted absent

Before ADR 0007 step 4 (commit 0a6e3534, "engine imports no commands"),
importing `ppxai.engine.completion` dragged six `ppxai.commands` modules
in behind it, so keeping it off the closure mattered a great deal. Step 4
removed its upward import; it is now an ordinary engine module, and its
presence in the closure today is harmless. Asserting its absence would be
a test whose premise already expired (docs/lessons/tests-whose-premise-expires.md
if present, or the general shape: a regression guard for a bug that a
later refactor made structurally impossible is dead weight that just
invites someone to "fix" the code back into the bug's precondition to make
the test pass). Do not restore that assertion.

## Measurement, fresh-interpreter only

Everything is measured via `subprocess.run([sys.executable, "-c", ...])`,
never in-process. An in-process `sys.modules` snapshot would measure
pytest's own import graph (and conftest's, and every other test module
collected in the same session) — not the clean closure a first-time
embedder gets. `_run_probe` below is that fresh-interpreter helper, shared
by every test in this file so the guard tests and the real assertions run
through the identical code path.

## Hermeticity

`ppxai.config.loader` resolves `PPXAI_HOME = Path.home() / ".ppxai"` at
IMPORT time (module-level, not inside a function) — see
docs/lessons/module-level-home-paths-leak-into-user-state.md. A probe run
with the developer's real `HOME` would compute paths into their real
`~/.ppxai`, and `PPXAI_HOME` is NOT read from an environment variable of
the same name (that lesson's documented trap), so only overriding `HOME`
itself at process launch works. `_run_probe` sets `HOME` to a fresh
`tmp_path` and passes a minimal, fully-replaced (not merged) environment,
so a developer's real `PPXAI_DEBUG`/`PPXAI_*_DEBUG` never leaks in and
flips on `ppxai.common.logger.Logger`'s file-handler + `mkdir` side effect
(`ppxai/common/logger.py`: `_initialize_logger` only creates
`~/.ppxai/logs/` and opens a file when one of those env vars is truthy;
default off, so a clean env never triggers it). Measured by hand: running
the production-tier probe with `HOME` pointed at an empty directory leaves
that directory empty afterward — nothing is read from or written into it.

## The measured numbers (sha 0a6e3534, 2026-09-21)

Both the production tier and the production+seam tier close over exactly
77 `ppxai.*` modules, and the two closures are the SAME 77 modules (not
just the same count) — `TestSeamOnlyTierAddsNothingExtra` checks the set
equality, not the size. This number is expected to grow over time (a
sibling fence, `tests/test_no_new_lazy_imports.py`, records a similar
comment: cleanup work adds modules legitimately) — it is deliberately not
pinned as an assertion; `test_closure_is_plausibly_large` only floors it
at 50 so a broken or empty probe cannot be mistaken for a clean one.
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Production tier: what ppxai-sre's RUNTIME imports (verified against
#: `libs/core/src/ppxai_sre_core/{bootstrap_loader,config,events,heartbeat,
#: manager,tools_adapter}.py` on 2026-09-21 — matches exactly).
PRODUCTION_IMPORTS = (
    "from ppxai.engine.client import EngineClient",
    "from ppxai.engine.types import Event, EventType",
    "from ppxai.engine.tools.base import FunctionTool",
    "from ppxai.engine.tools.manager import ToolManager",
    "from ppxai.engine.bootstrap import BootstrapContext",
    "from ppxai.engine.facts_resolver import facts_without_an_instance",
    "from ppxai.config.loader import PPXAI_HOME",
    "from ppxai.config.providers import get_default_provider, get_provider_config",
)

#: Seam-only tier: imported ONLY by ppxai-sre's seam test
#: (`libs/core/tests/test_ppxai_seam.py`, verified 2026-09-21 — matches
#: exactly), never by their runtime. Coupling, not dependency — see the
#: module docstring and `TestSeamOnlyTierAddsNothingExtra`.
SEAM_ONLY_IMPORTS = (
    "from ppxai.engine.session import SessionManager",
    "from ppxai.engine import provider_ops",
    "from ppxai.engine.provider_ops import ModelSwitchInFlightError",
    "from ppxai.config import loader",
)

#: Source for the fresh interpreter the probe runs in. Printing a single
#: JSON line keeps the parse side trivial and lets a crashed or confused
#: probe (extra prints, a traceback on stdout) be told apart from a clean
#: result instead of silently parsed as one.
_PROBE_SOURCE = """\
import json
import sys

{imports}

{extra}

_mods = sorted(m for m in sys.modules if m == "ppxai" or m.startswith("ppxai."))
print(json.dumps(_mods))
"""


def _run_probe(tmp_path, import_lines, extra_lines=()):
    """Import `import_lines` in a fresh interpreter; return the resulting
    `ppxai.*` module closure as a list of dotted names.

    Shared by every test below — the guard tests (crashed probe, planted
    violation) and the real pinned-surface tests all go through this same
    function, so a guard that passes proves something about the code path
    the real assertions actually use.

    Hermetic: `HOME` points at `tmp_path` (see module docstring) and the
    subprocess environment is a fresh dict, never `os.environ` merged with
    overrides, so no ambient `PPXAI_*` variable from the developer's shell
    can reach the probe. Runs with `cwd=REPO_ROOT` so `-c`'s implicit
    `sys.path[0]` (the empty string, i.e. cwd) resolves inside THIS
    working tree rather than wherever pytest happened to be invoked from.

    Raises `RuntimeError` — never returns an empty list — when the probe
    exits non-zero or does not print valid JSON, so a crashed probe can
    never be misread as an empty, clean closure (guard ii below).
    """
    source = _PROBE_SOURCE.format(
        imports="\n".join(import_lines),
        extra="\n".join(extra_lines),
    )
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", "")}
    if sys.platform == "win32":
        for key in ("SystemRoot", "SystemDrive", "TEMP", "TMP", "USERPROFILE"):
            if key in os.environ:
                env[key] = os.environ[key]
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"probe process exited {result.returncode} — a crashed probe "
            "must never be read as an empty, clean closure. stderr:\n"
            f"{result.stderr}"
        )
    lines = result.stdout.strip().splitlines()
    if not lines:
        raise RuntimeError(
            "probe printed no output — must never be read as an empty, "
            f"clean closure. stderr:\n{result.stderr}"
        )
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "probe did not print valid JSON — must never be read as an "
            f"empty, clean closure. stdout:\n{result.stdout}\nstderr:\n"
            f"{result.stderr}"
        ) from exc


def _forbidden(modules):
    """`ppxai.commands` modules in `modules`, matched on dotted module
    path — NEVER on a substring.

    A substring match on "commands" (or on "completion", the other name
    this codebase's own history got burned by) produces false hits: ADR
    0007 recorded 56 of them against `ppxai.engine.providers.wire.
    chat_completions` when a prior re-measurement used a substring check.
    Forbidden means exactly `ppxai.commands` or a name starting with
    `ppxai.commands.` — a dotted-path prefix check, not `in`/`contains`.
    """
    return sorted(
        m for m in modules if m == "ppxai.commands" or m.startswith("ppxai.commands.")
    )


def _violation_message(forbidden):
    return (
        f"consumer surface pulled in forbidden ppxai.commands modules: {forbidden}. "
        "Find the edge with `python -X importtime -c '<the same import lines>'` "
        "or a `sys.meta_path` observer around the failing import; the fix is to "
        "remove or break that edge — never to weaken this test."
    )


class TestForbiddenMatcherIsExact:
    """Guards FIRST, part 1: the matcher itself, no subprocess needed.

    A negative detector that flags everything (or nothing) is worthless.
    These prove `_forbidden` distinguishes the one case that burned ADR
    0007 (`chat_completions`, an innocent module whose name contains
    "completion") from the case it must catch (`ppxai.commands.factory`).
    """

    def test_does_not_substring_match_wire_chat_completions(self):
        modules = ["ppxai.engine.providers.wire.chat_completions", "ppxai.engine"]
        assert _forbidden(modules) == []

    def test_flags_the_commands_package_and_its_submodules(self):
        modules = [
            "ppxai.commands",
            "ppxai.commands.factory",
            "ppxai.engine.client",
            "ppxai.commandsnotarealsubpackage",
        ]
        # "ppxai.commandsnotarealsubpackage" shares the "ppxai.commands"
        # prefix as raw characters but is not `ppxai.commands.<anything>`
        # (no dot boundary) and is not `ppxai.commands` itself — a
        # substring check would flag it, a dotted-path check must not.
        assert _forbidden(modules) == ["ppxai.commands", "ppxai.commands.factory"]


class TestProbeHelperGuards:
    """Guards FIRST, part 2: the subprocess helper, exercised through the
    exact same `_run_probe` the real assertions call below."""

    def test_closure_is_plausibly_large(self, tmp_path):
        """POSITIVE CONTROL. An empty or broken probe (wrong cwd, wrong
        interpreter, `ppxai` not importable) would report a trivially
        small or empty closure and every "zero forbidden" assertion would
        pass vacuously. Floor, not a pin: measured 77 at sha 0a6e3534;
        expected to grow over time (recorded, not asserted, per the
        module docstring)."""
        modules = _run_probe(tmp_path, PRODUCTION_IMPORTS)
        assert len(modules) > 50, (
            f"production-tier closure only had {len(modules)} ppxai.* modules "
            "— too small to trust a zero-forbidden result; the probe is "
            f"probably broken, not clean. Modules: {modules}"
        )

    def test_crashed_probe_is_rejected_not_read_as_clean(self, tmp_path):
        """CRASHED PROBE REJECTED. A probe that raises after a successful
        import must surface as a hard failure here, not as an empty
        (therefore vacuously "clean") module list."""
        with pytest.raises(RuntimeError, match="exited"):
            _run_probe(tmp_path, PRODUCTION_IMPORTS, extra_lines=["raise SystemExit(3)"])

    def test_planted_violation_fires(self, tmp_path):
        """PLANTED VIOLATION FIRES. Adding one `ppxai.commands` import on
        top of the real production tier must be caught and named by
        `_forbidden`, through the identical helper the real tests use."""
        modules = _run_probe(
            tmp_path, PRODUCTION_IMPORTS, extra_lines=["import ppxai.commands.factory"]
        )
        forbidden = _forbidden(modules)
        assert forbidden, "planted `ppxai.commands.factory` import was not detected"
        assert "ppxai.commands.factory" in forbidden
        assert "ppxai.commands" in forbidden


class TestConsumerImportSurface:
    """The real assertions: the pinned surface from the module docstring,
    measured in a fresh interpreter, never touches `ppxai.commands`."""

    def test_production_tier_imports_zero_commands_modules(self, tmp_path):
        modules = _run_probe(tmp_path, PRODUCTION_IMPORTS)
        forbidden = _forbidden(modules)
        assert not forbidden, _violation_message(forbidden)

    def test_production_plus_seam_tier_imports_zero_commands_modules(self, tmp_path):
        modules = _run_probe(tmp_path, PRODUCTION_IMPORTS + SEAM_ONLY_IMPORTS)
        forbidden = _forbidden(modules)
        assert not forbidden, _violation_message(forbidden)


class TestSeamOnlyTierAddsNothingExtra:
    """Earns the "coupling, not dependency" label for the seam-only four
    by checking SET EQUALITY of the two closures, not just that both are
    forbidden-free. If the seam-only imports pulled in modules the
    production tier does not already pull in, the seam-only tier would be
    a real (if small) additional dependency, not mere coupling."""

    def test_seam_only_closure_equals_production_closure(self, tmp_path):
        production = set(_run_probe(tmp_path, PRODUCTION_IMPORTS))
        both = set(_run_probe(tmp_path, PRODUCTION_IMPORTS + SEAM_ONLY_IMPORTS))
        assert both == production, (
            "the seam-only imports changed the module closure — they are no "
            "longer mere coupling. Extra modules pulled in: "
            f"{sorted(both - production)}; modules the seam-only run dropped "
            f"(should not happen): {sorted(production - both)}"
        )
