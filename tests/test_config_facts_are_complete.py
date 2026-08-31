"""Config `facts` blocks must be complete records (ADR 0012 Q0d).

The ADR states the rule and the reason in one breath (§Q0d):

    Code rows may rely on dataclass defaults; config rows may not. A code
    row is a complete record *by construction* — the dataclass guarantees
    every field has a value, and the row is reviewed in a diff alongside
    the type. A config file has no such guarantee and no reviewer.

The shipped table has had a mutation-verified fence requiring all 12 fields
on all 65 rows since Item 65. Config rows — the ones the ADR calls *less*
trustworthy, precisely because they are unreviewed — had none. That
asymmetry runs backwards from the ADR's own reasoning, and it produced a
real divergence: `perplexity/sonar` stated only `wire_protocol` in the
tracked root config while the shipped example config stated all twelve, so
the same model resolved differently depending on which config won the
loader's search order.

**A partial row is not the same as a broken row, and this fence does not
claim it is.** Of the four partials measured when this was written, only
sonar changed behaviour; the three OpenAI rows happened to land on shipped
glob rows that supplied the rest. That is the point rather than a
mitigation: a partial row makes the effective answer depend on a table the
operator never looked at, and whether that silently works is luck, not
design.

**An absent or empty `facts` block is not a partial row.** "No config
opinion about this model" is the normal case and must stay free —
the rule is about blocks that exist and under-specify.
"""

import json
import pathlib
import subprocess

import pytest

from ppxai.config.facts_config import FACT_FIELDS

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _tracked_configs():
    """Every tracked `ppxai-config*.json`, so a third joins by existing.

    Mirrors `test_doctor.py::TestDeprecationTableInvariants._tracked_configs`,
    including its no-git fallback: a missing `git` must not silently empty
    the parametrisation, which would turn this fence into a no-op.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "ppxai-config*.json"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
        ).stdout.split()
    except Exception:  # noqa: BLE001 — no git (sdist, vendored tree)
        out = []
    names = out or ["ppxai-config.example.json", "ppxai-config.json"]
    return [REPO_ROOT / n for n in names if (REPO_ROOT / n).exists()]


def _facts_blocks(path):
    """Yield `(provider, model, block)` for every non-empty facts block."""
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for provider, pblock in (cfg.get("providers") or {}).items():
        for model, mblock in ((pblock or {}).get("models") or {}).items():
            if not isinstance(mblock, dict):
                continue
            block = mblock.get("facts")
            # Absent or empty is "no opinion" — deliberately not a finding.
            if isinstance(block, dict) and block:
                yield provider, model, block


class TestTrackedConfigFactsBlocksAreComplete:
    def test_the_tracked_config_set_is_not_empty(self):
        """A set that silently resolves to zero is a fence that cannot fail."""
        found = _tracked_configs()
        assert len(found) >= 2, (
            f"expected at least the example + root config, found {found}"
        )

    def test_there_are_facts_blocks_to_check(self):
        """Second vacuous-pass guard, one level deeper than the file list.

        The config set can be non-empty while the walk finds nothing —
        a renamed `facts` key, or a `models` shape change, would empty
        every parametrised case below and report success.
        """
        total = sum(len(list(_facts_blocks(p))) for p in _tracked_configs())
        assert total > 0, (
            "no facts block found in any tracked config — the walk no longer "
            "matches the config shape"
        )

    @pytest.mark.parametrize("path", _tracked_configs(), ids=lambda p: p.name)
    def test_every_facts_block_states_every_field(self, path):
        expected = set(FACT_FIELDS)
        partial = []
        for provider, model, block in _facts_blocks(path):
            missing = expected - set(block)
            if missing:
                partial.append(
                    f"{provider}/{model} states {len(block)}/{len(expected)}, "
                    f"missing {sorted(missing)}"
                )
        assert not partial, (
            f"{path.name} has partial facts blocks. ADR 0012 Q0d: a config row "
            f"must be a complete record, because unlike a code row it has no "
            f"dataclass defaults and no reviewer. State every field or state "
            f"none:\n  " + "\n  ".join(partial)
        )

    @pytest.mark.parametrize("path", _tracked_configs(), ids=lambda p: p.name)
    def test_no_facts_block_states_an_unknown_field(self, path):
        """The other direction: a typo'd key is silently ignored by the
        resolver, so the operator's stated intent never reaches the wire."""
        expected = set(FACT_FIELDS)
        unknown = []
        for provider, model, block in _facts_blocks(path):
            extra = set(block) - expected
            if extra:
                unknown.append(f"{provider}/{model}: {sorted(extra)}")
        assert not unknown, (
            f"{path.name} states fact keys that are not `ModelFacts` fields, so "
            f"the resolver drops them without complaint:\n  " + "\n  ".join(unknown)
        )


class TestTheRuleIsPinnedToTheDataclass:
    """`FACT_FIELDS`, never a literal list.

    A hand-maintained whitelist is the trap this project has hit repeatedly:
    a new `ModelFacts` field would be unenforceable — every existing config
    row would still pass while silently missing it.
    """

    def test_fact_fields_matches_the_dataclass(self):
        from ppxai.engine.model_facts import ModelFacts

        assert set(FACT_FIELDS) == set(ModelFacts.__dataclass_fields__), (
            "FACT_FIELDS has drifted from ModelFacts — the completeness rule "
            "above would enforce the wrong field set"
        )
