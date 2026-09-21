"""Sensitive subcommands — one declaration, every sink derives (ADR 0007 step 3a-sec).

`/token set <bearer>` typed INLINE in the web composer reached the server
on two paths that run BEFORE any command routing is consulted:

  1. the `> <input>` chat echo, which `app.showSystemMessage` mirrors to
     `POST /client-log` -> `~/.ppxai/logs`;
  2. the composer buffer, which autocomplete sends to `POST /complete`
     on every keystroke.

Step 1b closed the DISPATCH path (`POST /command/token` logs nothing
derived from `args`) and step 3a made routing data-driven, but neither
touched these two — `tests/e2e/live-app.spec.ts` pinned the leaking set
as exactly `['/client-log', '/complete']` so it could not grow silently.
This closes it, the ADR 0007 way: Python DECLARES
(`CommandSpec.sensitive_subcommands`), the roster PUBLISHES a per-
subcommand `sensitive` flag, and every client and server sink DERIVES.
No client may hardcode "/token" or "set".

This file covers the Python half:

  - registration-time validation of `sensitive_subcommands`;
  - `/token` declaring `set`, and the roster + completion snapshot
    carrying the flag;
  - the full truth table of `CommandFactory.redact_sensitive`, including
    the alias, echo-prefix, case and whitespace decisions, and that it
    never raises on odd input;
  - the two routes: a secret POSTed to `/client-log` reaches no log
    record, and one POSTed to `/complete` never reaches the completion
    engine and comes back in no response.

Both route tests are MUTATION-VERIFIED: with redaction neutered, the
same assertion must FAIL, so a helper that quietly stopped working could
not look green.
"""

from __future__ import annotations

import logging
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

import ppxai.server.http as http_module
import ppxai.server.routes.completion as completion_route
from ppxai.commands.factory import (
    SENSITIVE_MASK,
    CommandFactory,
    CommandSpec,
)
from ppxai.common.logger import get_logger

SECRET = "SECRET-BEARER-9f2a"
MASK = SENSITIVE_MASK


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def http_client():
    """TestClient against the FastAPI app (idiom from
    tests/test_client_handled_dispatch.py). Context-managed so the app
    gets one persistent event loop — see
    docs/lessons/testclient-per-request-event-loop.md."""
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def server_logging(tmp_path, monkeypatch):
    """Force the server Logger on so caplog sees the route's lines.

    The `ppxai.common.Logger` wrapper is a no-op until enabled, so
    without this every "no secret in the log" assertion would pass
    vacuously.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    log = get_logger("server")
    was_enabled = log.enabled
    if not was_enabled:
        log.enable()
    yield
    if not was_enabled and hasattr(log, "disable"):
        log.disable()


@pytest.fixture
def no_redaction(monkeypatch):
    """Neuter the redaction helper — the mutation lever.

    Every security assertion below is run a second time with this
    applied and must FAIL, which is what proves the assertion is
    actually watching the redaction and not something else.
    """
    monkeypatch.setattr(
        CommandFactory, "redact_sensitive", classmethod(lambda cls, text: text)
    )


@pytest.fixture
def aliased_sensitive_command():
    """A probe spec with an ALIAS and a sensitive subcommand.

    `/token` has no alias, so without this the alias arm of the helper
    would be untested — and alias resolution is exactly where a
    hand-rolled "does this start with /token?" check breaks.
    """
    name = "_sensitive_probe"

    def handler(ctx, args):  # pragma: no cover - never dispatched here
        return None

    CommandFactory.register(CommandSpec(
        name=name,
        description="probe",
        handler=handler,
        aliases=["_sp"],
        subcommands=[("stash", "sensitive"), ("look", "harmless")],
        sensitive_subcommands=frozenset({"stash"}),
    ))
    yield name
    CommandFactory.unregister(name)


def assert_not_in_log(caplog, secret: str) -> None:
    """No log record may carry `secret`."""
    for record in caplog.records:
        if secret in record.getMessage():
            raise AssertionError(
                f"secret leaked into a log line: {record.getMessage()!r}"
            )


# ---------------------------------------------------------------------------
# Declaration + validation
# ---------------------------------------------------------------------------

class TestSpecValidation:
    def test_default_is_empty(self):
        spec = CommandSpec(name="x", description="d", handler=lambda c, a: None)
        assert spec.sensitive_subcommands == frozenset()

    def test_undeclared_name_is_rejected(self):
        with pytest.raises(ValueError) as exc:
            CommandFactory.register(CommandSpec(
                name="_bad_sensitive_probe",
                description="d",
                handler=lambda c, a: None,
                subcommands=[("status", "s")],
                sensitive_subcommands=frozenset({"set"}),
            ))
        message = str(exc.value)
        assert "_bad_sensitive_probe" in message, "the error must name the command"
        assert "set" in message
        assert CommandFactory.get("_bad_sensitive_probe") is None, (
            "a spec that failed validation must not be registered"
        )

    def test_no_subcommands_at_all_is_rejected(self):
        """The common typo: flagging a subcommand on a spec that declares
        none. Silently disabling redaction is the failure mode worth
        failing loudly for."""
        with pytest.raises(ValueError):
            CommandFactory.register(CommandSpec(
                name="_bad_sensitive_probe2",
                description="d",
                handler=lambda c, a: None,
                sensitive_subcommands=frozenset({"set"}),
            ))

    def test_declared_name_is_accepted(self, aliased_sensitive_command):
        spec = CommandFactory.get(aliased_sensitive_command)
        assert spec.sensitive_subcommands == frozenset({"stash"})

    def test_subcommands_shape_is_unchanged(self):
        """ADDITIVE on purpose — `subcommands` stays list[tuple[str, str]]."""
        spec = CommandFactory.get("token")
        assert all(isinstance(s, tuple) and len(s) == 2 for s in spec.subcommands)


class TestTokenDeclaresSet:
    def test_token_spec(self):
        spec = CommandFactory.get("token")
        assert spec.sensitive_subcommands == frozenset({"set"})

    def test_it_is_the_only_sensitive_command_today(self):
        """A shrinking-baseline style pin: the day another command
        declares one, this test says so and the reviewer checks every
        sink still holds."""
        flagged = {
            name for name, spec in CommandFactory._registry.items()
            if spec.sensitive_subcommands
        }
        assert flagged == {"token"}


# ---------------------------------------------------------------------------
# Publication — the roster + the completion snapshot
# ---------------------------------------------------------------------------

class TestRosterCarriesSensitive:
    def test_token_subcommands(self):
        roster = CommandFactory.roster("web")
        token = next(c for c in roster["commands"] if c["name"] == "token")
        flags = {s["name"]: s["sensitive"] for s in token["subcommands"]}
        assert flags == {
            "status": False, "set": True, "mint": False, "clear": False
        }

    def test_every_subcommand_everywhere_has_the_field(self):
        roster = CommandFactory.roster(None)
        for command in roster["commands"]:
            for sub in command["subcommands"]:
                assert isinstance(sub["sensitive"], bool), (command["name"], sub)

    def test_version_semantics_unchanged(self):
        """The flag rides on the existing payload; it is not a new
        version axis."""
        assert CommandFactory.roster("web")["version"] == (
            CommandFactory.roster_version()
        )

    def test_completion_info_carries_it(self):
        infos = {i.name: i for i in CommandFactory.iter_completion_specs()}
        assert infos["token"].sensitive_subcommands == frozenset({"set"})

    def test_alias_entry_inherits_it(self, aliased_sensitive_command):
        infos = {i.name: i for i in CommandFactory.iter_completion_specs()}
        assert infos["_sp"].is_alias is True
        assert infos["_sp"].sensitive_subcommands == frozenset({"stash"})


# ---------------------------------------------------------------------------
# The helper — the whole truth table
# ---------------------------------------------------------------------------

class TestRedactSensitive:
    @pytest.mark.parametrize("text,expected", [
        # The leak itself, and its chat-echo form.
        (f"/token set {SECRET}", f"/token set {MASK}"),
        (f"> /token set {SECRET}", f"> /token set {MASK}"),
        (f">  /token set {SECRET}", f">  /token set {MASK}"),
        (f">>> /token set {SECRET}", f">>> /token set {MASK}"),
        # Everything after the subcommand goes, not just the first word.
        (f"/token set {SECRET} and more", f"/token set {MASK}"),
        # DECISION: case-insensitive on both the command and the
        # subcommand (the web dispatcher lowercases both, so /TOKEN SET
        # really does store a token). The kept text is the original.
        (f"/TOKEN SET {SECRET}", f"/TOKEN SET {MASK}"),
        (f"/Token Set {SECRET}", f"/Token Set {MASK}"),
        # DECISION: any run of whitespace separates tokens; the kept
        # prefix is byte-for-byte original, only the separator before the
        # mask is normalised to one space.
        (f"/token  set   {SECRET}", f"/token  set {MASK}"),
        (f"/token\tset\t{SECRET}", f"/token\tset {MASK}"),
        (f"   /token set {SECRET}", f"   /token set {MASK}"),
        # A value is REQUIRED — these are not secrets.
        ("/token set", "/token set"),
        ("/token set   ", "/token set   "),
        ("/token set\t", "/token set\t"),
        # Not a declared subcommand (this is what keeps `/token se` ->
        # `set` completing).
        ("/token se", "/token se"),
        ("/token se abc", "/token se abc"),
        # Declared, but not sensitive.
        ("/token status x", "/token status x"),
        ("/token clear now", "/token clear now"),
        # A command with no sensitive subcommands at all.
        ("/help me", "/help me"),
        ("/show /etc/hosts", "/show /etc/hosts"),
        # Unknown command.
        ("/nosuchcommand set abc", "/nosuchcommand set abc"),
        # Not a command line.
        (f"tell me about /token set {SECRET}", f"tell me about /token set {SECRET}"),
        ("plain chat text", "plain chat text"),
        ("", ""),
        ("   ", "   "),
        ("/", "/"),
        ("/token", "/token"),
        ("//token set x", "//token set x"),
    ])
    def test_truth_table(self, text, expected):
        assert CommandFactory.redact_sensitive(text) == expected

    def test_secret_is_absent_from_the_output(self):
        assert SECRET not in CommandFactory.redact_sensitive(f"/token set {SECRET}")

    def test_mask_is_fixed_length(self):
        """Never derived from the secret — a length-preserving mask would
        leak the length."""
        short = CommandFactory.redact_sensitive("/token set a")
        long = CommandFactory.redact_sensitive("/token set " + "a" * 5000)
        assert short == long == f"/token set {MASK}"

    def test_alias_resolves(self, aliased_sensitive_command):
        assert CommandFactory.redact_sensitive(f"/_sp stash {SECRET}") == (
            f"/_sp stash {MASK}"
        )
        assert CommandFactory.redact_sensitive(f"/_SP STASH {SECRET}") == (
            f"/_SP STASH {MASK}"
        )
        assert CommandFactory.redact_sensitive(f"/_sp look {SECRET}") == (
            f"/_sp look {SECRET}"
        )

    def test_is_idempotent(self):
        once = CommandFactory.redact_sensitive(f"/token set {SECRET}")
        assert CommandFactory.redact_sensitive(once) == once

    @pytest.mark.parametrize("text", [
        "", " ", "\t", "\n", "\r\n", "/", "//", "///", ">", "> ", ">>>",
        "/ ", "/token ", "/token set x", "/tökèn set x", "/token sét x",
        "/токен сет x", "/token set \u0000", "/token set 🔑🔑",
        "‮/token set x", "/" + "a" * 10_000 + " set x",
        "/token set " + "x" * 100_000, "> " * 500 + "/token set x",
        "/token" + " " * 5000 + "set" + " " * 5000 + "secret",
        "\x00\x01\x02", "🔑", "/🔑 set x",
    ])
    def test_never_raises(self, text):
        out = CommandFactory.redact_sensitive(text)
        assert isinstance(out, str)

    @pytest.mark.parametrize("value", [None, 42, b"/token set x", ["/token"], {}])
    def test_non_string_is_empty_not_an_exception(self, value):
        """A sink handed a non-string (a dict body, say) must not 500 —
        and must certainly not stringify whatever it was."""
        assert CommandFactory.redact_sensitive(value) == ""

    def test_long_input_is_not_quadratic(self):
        """The regexes are token-based (`\\S+`) precisely so this runs on
        every keystroke-sized buffer without backtracking."""
        blob = "/token set " + ("a" * 200_000)
        start = time.perf_counter()
        CommandFactory.redact_sensitive(blob)
        assert time.perf_counter() - start < 1.0


# ---------------------------------------------------------------------------
# Sink 1 — POST /client-log (the `> <input>` chat-echo mirror)
# ---------------------------------------------------------------------------

class TestClientLogRoute:
    ECHO = f"> /token set {SECRET}"

    def test_secret_reaches_no_log_record(self, http_client, server_logging, caplog):
        with caplog.at_level(logging.DEBUG, logger="ppxai.server"):
            resp = http_client.post(
                "/client-log",
                json={"level": "info", "message": self.ECHO, "client": "web"},
            )
        assert resp.status_code == 200
        assert SECRET not in resp.text
        assert_not_in_log(caplog, SECRET)

    def test_the_line_is_still_logged_masked(self, http_client, server_logging,
                                             caplog):
        """Redacted, not dropped — the debug log must still show that the
        command was run, or this fix would cost observability."""
        with caplog.at_level(logging.DEBUG, logger="ppxai.server"):
            http_client.post(
                "/client-log",
                json={"level": "info", "message": self.ECHO, "client": "web"},
            )
        assert any("/token set" in r.getMessage() for r in caplog.records), (
            "the masked echo did not reach the log at all"
        )

    def test_harmless_messages_are_untouched(self, http_client, server_logging,
                                             caplog):
        with caplog.at_level(logging.DEBUG, logger="ppxai.server"):
            http_client.post(
                "/client-log",
                json={"level": "info", "message": "> /token status", "client": "web"},
            )
        assert any("/token status" in r.getMessage() for r in caplog.records)

    def test_mutation_the_assertion_can_fail(self, http_client, server_logging,
                                             caplog, no_redaction):
        """With redaction disabled the SAME request leaks — proving the
        test above watches the redaction and not something else. This is
        the pre-fix behaviour, reproduced on demand."""
        with caplog.at_level(logging.DEBUG, logger="ppxai.server"):
            http_client.post(
                "/client-log",
                json={"level": "info", "message": self.ECHO, "client": "web"},
            )
        with pytest.raises(AssertionError):
            assert_not_in_log(caplog, SECRET)


# ---------------------------------------------------------------------------
# Sink 2 — POST /complete (the composer buffer, sent per keystroke)
# ---------------------------------------------------------------------------

class TestCompleteRoute:
    def test_no_items_and_nothing_logged(self, http_client, server_logging, caplog):
        with caplog.at_level(logging.DEBUG, logger="ppxai.server"):
            resp = http_client.post(
                "/complete",
                json={"buffer": f"/token set {SECRET}", "cursor": -1, "client": "web"},
            )
        assert resp.status_code == 200
        assert resp.json()["items"] == []
        assert SECRET not in resp.text
        assert_not_in_log(caplog, SECRET)

    def test_the_engine_never_sees_the_secret(self, http_client, monkeypatch):
        """The mechanism, not just the outcome: `complete()` is not called
        at all for a sensitive buffer. `complete()` happens to return []
        for this buffer today, so an outcome-only test would pass even
        with the guard removed."""
        seen: list[str] = []

        def spy(buffer, cursor, **kwargs):
            seen.append(buffer)
            return []

        monkeypatch.setattr(completion_route, "complete", spy)
        http_client.post(
            "/complete",
            json={"buffer": f"/token set {SECRET}", "cursor": -1, "client": "web"},
        )
        assert seen == [], f"the buffer reached the completion engine: {seen!r}"

    def test_mutation_without_redaction_the_engine_does_see_it(
        self, http_client, monkeypatch, no_redaction
    ):
        """The same spy, with redaction disabled, MUST record the secret —
        otherwise the test above proves nothing."""
        seen: list[str] = []

        def spy(buffer, cursor, **kwargs):
            seen.append(buffer)
            return []

        monkeypatch.setattr(completion_route, "complete", spy)
        http_client.post(
            "/complete",
            json={"buffer": f"/token set {SECRET}", "cursor": -1, "client": "web"},
        )
        assert any(SECRET in b for b in seen), (
            "the mutation is not exercised — the buffer did not reach the engine "
            "even with redaction disabled"
        )

    def test_subcommand_completion_still_works(self, http_client):
        """The whole point of requiring a VALUE: `/token se` must still
        complete to `set`."""
        resp = http_client.post(
            "/complete", json={"buffer": "/token se", "cursor": -1, "client": "web"}
        )
        assert [i["text"] for i in resp.json()["items"]] == ["set"]

    def test_bare_subcommand_list_still_works(self, http_client):
        resp = http_client.post(
            "/complete", json={"buffer": "/token ", "cursor": -1, "client": "web"}
        )
        assert "set" in [i["text"] for i in resp.json()["items"]]

    def test_ordinary_buffers_are_unaffected(self, http_client):
        resp = http_client.post(
            "/complete", json={"buffer": "/hel", "cursor": -1, "client": "web"}
        )
        assert [i["text"] for i in resp.json()["items"]]


# ---------------------------------------------------------------------------
# Sink 3 — POST /command/{name} (already argument-free for /token; this
# pins the guard that protects a future SERVER-dispatched sensitive command)
# ---------------------------------------------------------------------------

class TestCommandRouteArgsPreview:
    def test_a_server_dispatched_sensitive_command_is_redacted(
        self, http_client, server_logging, caplog, aliased_sensitive_command
    ):
        with caplog.at_level(logging.DEBUG, logger="ppxai.server"):
            http_client.post(
                f"/command/{aliased_sensitive_command}",
                json={"args": f"stash {SECRET}"},
            )
        assert_not_in_log(caplog, SECRET)
        assert any("stash" in r.getMessage() for r in caplog.records), (
            "the masked args line did not reach the log at all"
        )

    def test_mutation_without_redaction_it_leaks(
        self, http_client, server_logging, caplog, aliased_sensitive_command,
        no_redaction
    ):
        with caplog.at_level(logging.DEBUG, logger="ppxai.server"):
            http_client.post(
                f"/command/{aliased_sensitive_command}",
                json={"args": f"stash {SECRET}"},
            )
        with pytest.raises(AssertionError):
            assert_not_in_log(caplog, SECRET)

    def test_ordinary_args_still_logged(self, http_client, server_logging, caplog):
        with caplog.at_level(logging.DEBUG, logger="ppxai.server"):
            http_client.post("/command/help", json={"args": "status"})
        assert any("args='status'" in r.getMessage() for r in caplog.records)
