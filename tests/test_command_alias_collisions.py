"""Fence: no alias collisions in the SHIPPED command roster.

**RELEASE GATE (owner decision, 2026-09-20).** Command aliases are code
configuration — the set of strings a user can type after `/` — and a
collision between two of them is a routing bug, not a style nit. This
suite gates release, so this file is the mechanism: a collision in the
built-in roster must fail the suite, not just log a warning.

**What "collision" means here, and why it matters:**

1. An alias equal to an existing CANONICAL command name. `CommandFactory
   .get()` (`ppxai/commands/factory.py`) checks `_aliases` FIRST, so an
   alias shadows a same-named command — `/foo` silently stops meaning
   `/foo` and starts meaning whatever registered the alias. This is the
   dangerous case: it changes behaviour for an existing command, not just
   a new one.
2. The same alias declared by two different commands. Whichever module
   is imported later (import order = `_BUILTIN_COMMAND_MODULES` in
   `factory.py`) wins; the other command's alias silently stops working.
3. A command declaring its own name as an alias, or declaring the same
   alias twice in one `CommandSpec.aliases` list — dead weight at best,
   a sign the spec was edited carelessly at worst.
4. Two different MODULES registering the same canonical command `name`
   (a distinct hazard from #2 — see below).

**Why this needs a dedicated fence: `CommandFactory.register()` does not
raise.** Verified in `ppxai/commands/factory.py::register()`: on a
colliding alias it does `logger.warning(...)` and then unconditionally
runs `cls._aliases[alias] = spec.name` — the newcomer takes the name. On
a colliding canonical `name` it also just warns and overwrites
`cls._registry[spec.name]`. `ppxai/commands/coding.py` even carries a
scar from this: `aliases=[],  # Removed "t" alias - conflicts with
/tools` — a human working around the missing guard by hand, for exactly
one collision, with no fence to stop the next one.

**Why detection reads DECLARATIONS, not `_aliases`.** By the time all
built-in modules have imported, `CommandFactory._aliases` is a flat
`alias -> canonical name` map — the overwrite already happened and the
loser's mapping is gone. There is no way to recover "these two specs both
declared alias X" from that dict; it only ever shows the winner. So
detection here walks the fully-populated `CommandFactory._registry`
(each `CommandSpec` still carries its own *declared* `aliases` list
intact — only the cross-command `_aliases` index is overwrite-lossy) and,
for check 4, the raw `CommandSpec(name=...)` source declarations via
`ast`, since two modules registering the same name is invisible even in
`_registry` (last writer wins there too).

**Runtime behaviour is deliberately UNCHANGED by this fence.** This test
does not touch `CommandFactory.register()`. `reload_user_commands()`
(`~/.ppxai/commands/*.py`, loaded live, outside this repo, outside CI)
keeps its existing warn-and-overwrite semantics — a user dropping a
`.py` file with a colliding alias into their own commands directory
still gets a warning and a silent overwrite, not a crash. Only the
SHIPPED, built-in roster is gated, and only in the test suite.

**Guards first.** All detection lives in pure helper functions over
plain `(name, aliases)` data so they can be proven correct on synthetic,
planted collisions before being trusted against the real roster
(`TestHelpersRejectPlantedCollisions` below). `TestTheRosterIsRealistic`
guards against an empty/partial registry making every check pass
vacuously.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from ppxai.commands.factory import CommandFactory

COMMANDS_DIR = Path(__file__).resolve().parent.parent / "ppxai" / "commands"


# =============================================================================
# Pure helpers — operate on plain data, no registry access.
# =============================================================================


def find_alias_shadows(
    commands: list[tuple[str, list[str]]],
) -> list[tuple[str, str]]:
    """Return `(owner, alias)` for every alias that equals some OTHER
    command's canonical name — the shadowed command's name is `alias`
    itself, since that is exactly what makes it a collision.

    This is check 1, the dangerous case: `CommandFactory.get()` consults
    the alias map before the command map, so such an alias makes the
    shadowed command unreachable by its own name.

    Self-aliasing (a command's alias equal to its own name) is reported
    by `find_self_and_duplicate_declarations` instead, to keep the two
    failure modes from being conflated in one message.
    """
    names = {name for name, _aliases in commands}
    shadows: list[tuple[str, str]] = []
    for owner, aliases in commands:
        for alias in aliases:
            if alias in names and alias != owner:
                shadows.append((owner, alias))
    return shadows


def find_duplicate_alias_owners(
    commands: list[tuple[str, list[str]]],
) -> dict[str, list[str]]:
    """Return `alias -> sorted distinct owners` for every alias declared
    by more than one command (check 2).

    A command that (incorrectly) lists the same alias twice in its own
    `aliases` list contributes only one owner here — that case is
    `find_self_and_duplicate_declarations`'s job (check 3), not this
    one's.
    """
    owners_by_alias: dict[str, set[str]] = defaultdict(set)
    for owner, aliases in commands:
        for alias in aliases:
            owners_by_alias[alias].add(owner)
    return {
        alias: sorted(owners)
        for alias, owners in owners_by_alias.items()
        if len(owners) > 1
    }


def find_self_and_duplicate_declarations(
    commands: list[tuple[str, list[str]]],
) -> list[tuple[str, str]]:
    """Return `(name, problem)` pairs for check 3:

    - a command declaring its own name as an alias
    - a command declaring the same alias twice in one `aliases` list
    """
    problems: list[tuple[str, str]] = []
    for name, aliases in commands:
        if name in aliases:
            problems.append((name, f"declares its own name '{name}' as an alias"))
        seen: set[str] = set()
        dupes: set[str] = set()
        for alias in aliases:
            if alias in seen:
                dupes.add(alias)
            seen.add(alias)
        for alias in sorted(dupes):
            problems.append((name, f"declares alias '{alias}' twice"))
    return problems


def find_cross_declaration_duplicate_names(
    name_locations: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Return the subset of `name -> [location, ...]` with more than one
    location — i.e. a canonical command `name` declared by more than one
    `CommandSpec(...)` call site (check 4).

    `name_locations` is plain data (name -> list of "file:line" strings)
    so this can be exercised on synthetic input; the real caller builds
    it with `_scan_declared_command_names()` via `ast`.
    """
    return {name: locs for name, locs in name_locations.items() if len(locs) > 1}


# =============================================================================
# Real data: the shipped registry, and the raw declarations.
# =============================================================================


def _load_shipped_commands() -> list[tuple[str, list[str]]]:
    """The fully-populated built-in registry, as declared.

    `CommandFactory.list_all()` triggers `_ensure_loaded()`, which
    imports every module in `_BUILTIN_COMMAND_MODULES` (the same
    eager-load path every client goes through — see
    `tests/test_tui_command_factory.py` and
    `tests/test_help_command_reconciliation.py` for the same pattern of
    reading `CommandFactory._registry` once it's populated). This reads
    the registry; it registers nothing and mutates no global state.
    """
    CommandFactory.list_all()
    return [
        (name, list(spec.aliases))
        for name, spec in CommandFactory._registry.items()
    ]


def _scan_declared_command_names() -> dict[str, list[str]]:
    """AST scan of `ppxai/commands/*.py` for `CommandSpec(name="...")`
    string-literal declarations, mapping each declared name to every
    `file:line` that declares it.

    This exists because `CommandFactory._registry` overwrites on a
    duplicate canonical name (same as it does for aliases — see the
    module docstring), so by the time the registry is populated the
    losing declaration has already vanished from it. The declarations on
    disk are the only place a duplicate `name=` is still observable.
    """
    locations: dict[str, list[str]] = defaultdict(list)
    for path in sorted(COMMANDS_DIR.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            func_name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if func_name != "CommandSpec":
                continue
            for kw in node.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    locations[kw.value.value].append(f"{path.name}:{node.lineno}")
    return dict(locations)


# =============================================================================
# Guards first: helpers must reject planted collisions and accept a clean
# roster, before the real roster is trusted to their verdict.
# =============================================================================


class TestHelpersRejectPlantedCollisions:
    def test_find_alias_shadows_catches_alias_equal_to_command_name(self):
        roster = [("save", ["s"]), ("sessions", ["save"])]
        shadows = find_alias_shadows(roster)
        assert shadows == [("sessions", "save")]

    def test_find_alias_shadows_ignores_self_alias(self):
        """Self-aliasing is check 3's job, not check 1's — assert no
        double-reporting."""
        roster = [("docs", ["docs"])]
        assert find_alias_shadows(roster) == []

    def test_find_alias_shadows_accepts_clean_roster(self):
        roster = [("save", ["s"]), ("load", ["l"]), ("tools", ["t"])]
        assert find_alias_shadows(roster) == []

    def test_find_duplicate_alias_owners_catches_shared_alias(self):
        roster = [("save", ["s"]), ("sessions", ["s"])]
        dupes = find_duplicate_alias_owners(roster)
        assert dupes == {"s": ["save", "sessions"]}

    def test_find_duplicate_alias_owners_ignores_repeat_within_one_command(self):
        """A single command listing the same alias twice has exactly one
        owner for that alias — not a cross-command collision (check 3's
        job instead)."""
        roster = [("docs", ["d", "d"])]
        assert find_duplicate_alias_owners(roster) == {}

    def test_find_duplicate_alias_owners_accepts_clean_roster(self):
        roster = [("save", ["s"]), ("load", ["l"])]
        assert find_duplicate_alias_owners(roster) == {}

    def test_find_self_and_duplicate_declarations_catches_self_alias(self):
        roster = [("docs", ["docs", "d"])]
        problems = find_self_and_duplicate_declarations(roster)
        assert ("docs", "declares its own name 'docs' as an alias") in problems

    def test_find_self_and_duplicate_declarations_catches_repeated_alias(self):
        roster = [("docs", ["d", "d"])]
        problems = find_self_and_duplicate_declarations(roster)
        assert ("docs", "declares alias 'd' twice") in problems

    def test_find_self_and_duplicate_declarations_accepts_clean_roster(self):
        roster = [("docs", ["d"]), ("save", ["s"])]
        assert find_self_and_duplicate_declarations(roster) == []

    def test_find_cross_declaration_duplicate_names_catches_two_locations(self):
        locations = {"tools": ["tools.py:10", "coding.py:99"], "save": ["session.py:5"]}
        dupes = find_cross_declaration_duplicate_names(locations)
        assert dupes == {"tools": ["tools.py:10", "coding.py:99"]}

    def test_find_cross_declaration_duplicate_names_accepts_clean_locations(self):
        locations = {"tools": ["tools.py:10"], "save": ["session.py:5"]}
        assert find_cross_declaration_duplicate_names(locations) == {}


# =============================================================================
# Guard: the loaded roster must be big enough that a vacuous pass is
# impossible (an empty/partial registry would make every check below
# trivially true).
# =============================================================================


class TestTheRosterIsRealistic:
    def test_roster_is_non_trivially_large(self):
        commands = _load_shipped_commands()
        assert len(commands) > 30, (
            f"only {len(commands)} commands loaded — CommandFactory's "
            "registry looks empty or partial, which would make every "
            "collision check in this file pass vacuously. Check "
            "CommandFactory._ensure_loaded() / _BUILTIN_COMMAND_MODULES "
            "in ppxai/commands/factory.py."
        )

    def test_declared_names_scan_is_non_trivially_large(self):
        locations = _scan_declared_command_names()
        assert len(locations) > 30, (
            f"only {len(locations)} distinct command names found by the "
            "ast scan of ppxai/commands/*.py — the scan may have stopped "
            "matching CommandSpec(name=...) declarations."
        )


# =============================================================================
# The real fence: the shipped roster.
# =============================================================================


class TestNoAliasShadowsACommandName:
    def test_no_alias_equals_an_existing_command_name(self):
        """Check 1 — the dangerous case. `CommandFactory.get()` checks
        `_aliases` before `_registry`, so an alias equal to another
        command's name makes that command unreachable by its own name."""
        commands = _load_shipped_commands()
        shadows = find_alias_shadows(commands)
        assert not shadows, (
            "alias shadows an existing command name — CommandFactory.get() "
            "checks aliases first, so the shadowed command becomes "
            "unreachable by its own name. Fix: rename the alias on the "
            "owning spec (see ppxai/commands/coding.py's `aliases=[],  # "
            "Removed \"t\" alias - conflicts with /tools` for the pattern "
            "to follow). Collisions (owner, alias): "
            + ", ".join(f"'{owner}' aliases '{alias}' which is also the "
                        f"name of command '{alias}'" for owner, alias in shadows)
        )


class TestNoAliasSharedByTwoCommands:
    def test_no_alias_declared_by_two_different_commands(self):
        """Check 2. `CommandFactory.register()` on a colliding alias just
        warns and overwrites `_aliases[alias]` — whichever module in
        `_BUILTIN_COMMAND_MODULES` (factory.py) imports later wins, and
        the other command's alias silently stops routing to it."""
        commands = _load_shipped_commands()
        dupes = find_duplicate_alias_owners(commands)
        assert not dupes, (
            "the same alias is declared by two different commands — only "
            "the later-imported module's command will actually be "
            "reachable through it (CommandFactory.register() overwrites "
            "_aliases silently). Fix: rename the alias on one of the "
            "specs so each alias has exactly one owner. Alias -> owners: "
            + ", ".join(f"'{alias}' -> {owners}" for alias, owners in dupes.items())
        )


class TestNoSelfAliasOrDuplicateDeclaration:
    def test_no_command_declares_its_own_name_or_repeats_an_alias(self):
        """Check 3. Neither case breaks routing today, but both indicate
        a spec edited carelessly and are worth fencing before they hide
        a real collision behind noise."""
        commands = _load_shipped_commands()
        problems = find_self_and_duplicate_declarations(commands)
        assert not problems, (
            "a command's own aliases list is malformed. Fix: edit the "
            "CommandSpec's `aliases=[...]` list for the named command(s) "
            "to remove the self-reference or the repeated entry. "
            "Problems (command, issue): "
            + ", ".join(f"'{name}': {issue}" for name, issue in problems)
        )


class TestNoCrossModuleDuplicateCommandNames:
    def test_no_two_modules_register_the_same_canonical_name(self):
        """Check 4. `CommandFactory.register()` on a colliding canonical
        `name` also just warns and overwrites `_registry[spec.name]` —
        by the time the registry is populated the losing module's spec
        (handler, aliases, everything) is gone without a trace, which is
        why this reads the `CommandSpec(name=...)` declarations directly
        via ast instead of the registry."""
        locations = _scan_declared_command_names()
        dupes = find_cross_declaration_duplicate_names(locations)
        assert not dupes, (
            "the same canonical command name is declared by more than "
            "one CommandSpec(...) call — CommandFactory.register() "
            "overwrites _registry[name] silently, so one module's entire "
            "command spec is discarded at import time. Fix: rename one "
            "of the colliding commands, or remove the duplicate "
            "registration. Name -> declaration sites: "
            + ", ".join(f"'{name}' -> {locs}" for name, locs in dupes.items())
        )
