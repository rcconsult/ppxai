"""A stale ADR 0010 key must say what it COSTS, not just where it moved.

ADR 0010 was a clean break: a key left at `tools.agent.*` is silently
ignored and its setting reverts to the default. `/doctor` is the operator's
only discovery path for that, and it used to print the mapping alone —
`tools.agent.sandbox -> execution.task.sandbox` — which reads as clerical.

One of those reversions is not clerical. `tools.agent.sandbox` held the
filesystem seal, and its default is `enforcement: "off"`, which makes the
whole `read_paths.deny` list (`.env`, `.ssh`, `secrets`, …) inert. So the
operator careful enough to have configured a jail is exactly the one whose
jail this upgrade silently removes, and the old output gave them no reason
to treat that row differently from a changed timeout.
"""

from __future__ import annotations

import pytest

from ppxai.commands.doctor import (
    ADR_0010_KEY_MOVES,
    _format_config_migration_section,
)

SANDBOX_STALE = {"tools": {"agent": {"sandbox": {"enforcement": "in_process"}}}}


def _render(config: dict) -> str:
    return "\n".join(_format_config_migration_section(config))


class TestTheSecurityLossIsNamed:
    def test_the_sandbox_row_says_what_becomes_readable(self):
        out = _render(SANDBOX_STALE)

        assert ".env" in out, (
            "the operator must learn that provider API keys become readable, "
            "not merely that a key moved"
        )
        assert "read_paths.deny" in out
        assert 'enforcement:"off"' in out or "enforcement: \"off\"" in out

    def test_it_is_marked_as_security_not_just_listed(self):
        out = _render(SANDBOX_STALE)
        assert "SECURITY" in out

    def test_the_security_row_sorts_above_mere_behaviour_changes(self):
        """A flat list buries the one row that widens what a run can reach."""
        out = _render({
            "tools": {"agent": {
                "consent_ttl_s": 900,
                "result_retention_s": 60,
                "sandbox": {"enforcement": "in_process"},
            }}
        })

        assert out.index("tools.agent.sandbox") < out.index("tools.agent.consent_ttl_s")
        assert out.index("tools.agent.sandbox") < out.index("tools.agent.result_retention_s")


class TestEveryMoveCarriesItsCost:
    @pytest.mark.parametrize("row", ADR_0010_KEY_MOVES, ids=lambda r: ".".join(r[0]))
    def test_the_row_is_complete(self, row):
        path, new, cost, severity = row
        assert new.startswith("execution."), path
        assert severity in ("security", "behaviour"), path
        assert len(cost) > 40, (
            f"{'.'.join(path)} has no usable cost line. 'moved, now ignored' "
            f"is half a message — say what reverting loses."
        )

    def test_exactly_one_move_is_a_security_loss(self):
        """Pins the classification. If a second key ever widens reach, this
        fails and forces the decision rather than letting it ride in as
        another 'behaviour' row."""
        security = [r for r in ADR_0010_KEY_MOVES if r[3] == "security"]
        assert [".".join(r[0]) for r in security] == ["tools.agent.sandbox"]


class TestACleanConfigStaysQuiet:
    def test_no_stale_keys_produces_no_warning(self):
        out = _render({"execution": {"task": {"enabled": True}}})

        assert "✓" in out
        assert "SECURITY" not in out
        assert "cost while stale" not in out
