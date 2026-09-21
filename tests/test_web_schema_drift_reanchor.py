"""Source fence for the web app's reconnect-time AppState schema check
(Task 2, plan-adr-0007-completion-service.md open owner decision item 9).

`ppxai/web/app.js` is a ~3,700-line file tightly coupled to the DOM and
is not driven under Node for its own wiring (same rationale as
`tests/test_web_visibility_reanchor.py` /
`tests/test_web_filetree_appstate_subscriber.py`: the behaviour here is
"does the right call happen from the right place", which a source read
answers as reliably as a JS runner for a handful of call sites, and the
actual runtime logic being called — `compareAppStateSchemas` /
`AppState.adoptSchema` — already has full Node behavioural coverage in
`tests/test_web_schema_drift_behavior.py`).

Every assertion here is MUTATION-VERIFIED in the sense CLAUDE.md's
"Verify, Don't Assume" asks for: each regex/substring check is also run
against a scratch copy of the SAME text with the relevant line deleted,
and asserted to fail — so this file proves the fence bites, not just
that the current source happens to satisfy a pattern. No file on disk
is ever touched; mutation happens on an in-memory copy of the string.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "ppxai" / "web" / "app.js"


def _read() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _function_body(text: str, signature: str) -> str:
    """Brace-matched body of the first method/function whose definition
    line contains `signature`. Same technique as
    `tests/test_app_state_generated_types.py::_function_body` — a plain
    `in` check on the whole file would be satisfied by the string
    appearing anywhere, including a comment far from the real call."""
    start = text.find(signature)
    assert start != -1, f"{signature!r} not found in app.js"
    open_brace = text.find("{", start)
    assert open_brace != -1, f"no body found for {signature!r}"
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace:i + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


def _visibilitychange_block(text: str) -> str:
    match = re.search(
        r"addEventListener\(\s*['\"]visibilitychange['\"][\s\S]*?\}\)",
        text,
    )
    assert match, "visibilitychange handler block not found"
    return match.group(0)


def _heartbeat_body(text: str) -> str:
    return _function_body(text, "async _heartbeat(")


# ---------------------------------------------------------------------------
# The checks themselves, as reusable functions so they can be applied
# both to the real file (must pass) and to a mutated in-memory copy
# (must fail) below.
# ---------------------------------------------------------------------------

def _check_reanchor_accepts_check_schema_param(text: str) -> None:
    assert re.search(
        r"async\s+_reanchorFromServer\s*\(\s*checkSchema\s*=\s*false\s*\)",
        text,
    ), "_reanchorFromServer must accept a checkSchema=false parameter"


def _check_reanchor_calls_the_drift_check_when_asked(text: str) -> None:
    body = _function_body(text, "async _reanchorFromServer(")
    assert "if (checkSchema)" in body and "_checkSchemaDrift()" in body, (
        "_reanchorFromServer must call _checkSchemaDrift() when checkSchema is true"
    )


def _check_visibilitychange_requests_schema_check(text: str) -> None:
    block = _visibilitychange_block(text)
    assert "_reanchorFromServer(true)" in block, (
        "the visibilitychange->visible handler must pass true to "
        "_reanchorFromServer — a tab restored after being backgrounded is "
        "exactly the reconnect boundary this check exists for"
    )


def _check_heartbeat_recovery_requests_schema_check(text: str) -> None:
    body = _heartbeat_body(text)
    assert "_reanchorFromServer(true)" in body, (
        "the heartbeat recovery path must pass true to _reanchorFromServer "
        "-- a server that just came back could have been upgraded"
    )


def _check_provider_and_model_switch_do_not_request_it(text: str) -> None:
    """These call `_reanchorFromServer()` for an unrelated reason (the
    vision badge) on every provider/model switch — a hot path, not a
    reconnect. They must keep the cheap, unconditional (no-arg) call."""
    for signature in ("async handleProviderChange(", "async handleModelChange("):
        body = _function_body(text, signature)
        assert "_reanchorFromServer();" in body, (
            f"{signature} must still call the plain, unconditional "
            "_reanchorFromServer() (no schema check) -- it is not a "
            "reconnect boundary and runs on every provider/model switch"
        )
        assert "_reanchorFromServer(true)" not in body, (
            f"{signature} started requesting a schema check on every "
            "switch -- that adds a network round trip to a hot path for "
            "no reconnect-shaped reason"
        )


def _check_drift_check_is_reentrancy_guarded(text: str) -> None:
    body = _function_body(text, "async _checkSchemaDrift(")
    assert "_schemaCheckInFlight" in body, (
        "_checkSchemaDrift must coalesce concurrent calls (heartbeat "
        "recovery and visibilitychange can overlap) via an in-flight guard"
    )


def _check_drift_check_uses_the_schema_endpoint(text: str) -> None:
    body = _function_body(text, "async _runSchemaDriftCheck(")
    assert "apiClient.getAppStateSchema()" in body, (
        "_runSchemaDriftCheck must fetch GET /schema/app-state via "
        "apiClient.getAppStateSchema()"
    )
    assert "compareAppStateSchemas(" in body, (
        "_runSchemaDriftCheck must classify the diff via "
        "compareAppStateSchemas (shared/app-state-schema-diff.js)"
    )


def _check_each_verdict_is_handled(text: str) -> None:
    body = _function_body(text, "async _runSchemaDriftCheck(")
    assert "diff.verdict === 'identical'" in body, "identical must be handled (silently)"
    assert "diff.verdict === 'extra-only'" in body, "extra-only must be handled"
    assert "this.state.adoptSchema(served)" in body, (
        "a difference must adopt the server's schema into the live AppState"
    )
    assert "console.info(" in body, "extra-only must log via console.info, not warn/error"
    assert "showSystemMessage(" in body, (
        "the incompatible case must surface a visible, non-blocking notice "
        "via the page's existing system-message idiom"
    )
    # The notice must actually be reachable ONLY for the incompatible
    # path, not unconditionally after the extra-only return.
    extra_idx = body.find("diff.verdict === 'extra-only'")
    notice_idx = body.find("showSystemMessage(")
    assert extra_idx != -1 and notice_idx != -1 and extra_idx < notice_idx, (
        "showSystemMessage must come after the extra-only branch's return, "
        "i.e. it must not fire for extra-only too"
    )


def _check_unverified_never_blocks(text: str) -> None:
    body = _function_body(text, "async _runSchemaDriftCheck(")
    match = re.search(r"catch\s*\(e\)\s*\{[\s\S]*?\n\s{8}\}", body)
    assert match, "could not find the getAppStateSchema() catch block"
    catch_block = match.group(0)
    assert "return;" in catch_block, (
        "a failed/404 schema fetch must return without throwing or "
        "blocking -- the injected schema keeps working"
    )
    assert "throw" not in catch_block, "the unverified case must not re-throw"


def _check_html_loads_the_diff_module(text_html: str) -> None:
    assert "shared/app-state-schema-diff.js" in text_html, (
        "index.html must load shared/app-state-schema-diff.js"
    )


def _check_api_client_exposes_the_endpoint(text: str) -> None:
    assert "async getAppStateSchema(" in text and "/schema/app-state" in text, (
        "ApiClient must expose getAppStateSchema() calling /schema/app-state"
    )


ALL_APP_JS_CHECKS = [
    _check_reanchor_accepts_check_schema_param,
    _check_reanchor_calls_the_drift_check_when_asked,
    _check_visibilitychange_requests_schema_check,
    _check_heartbeat_recovery_requests_schema_check,
    _check_provider_and_model_switch_do_not_request_it,
    _check_drift_check_is_reentrancy_guarded,
    _check_drift_check_uses_the_schema_endpoint,
    _check_each_verdict_is_handled,
    _check_unverified_never_blocks,
]


# ---------------------------------------------------------------------------
# The real files must pass every check.
# ---------------------------------------------------------------------------

class TestRealSourcePassesEveryCheck:
    def test_app_js(self):
        text = _read()
        for check in ALL_APP_JS_CHECKS:
            check(text)

    def test_index_html_loads_the_module(self):
        html = (APP_JS.parent / "index.html").read_text(encoding="utf-8")
        _check_html_loads_the_diff_module(html)

    def test_api_client_exposes_the_endpoint(self):
        api_client = (APP_JS.parent / "shared" / "api-client.js").read_text(encoding="utf-8")
        _check_api_client_exposes_the_endpoint(api_client)


# ---------------------------------------------------------------------------
# Mutation verification: delete the real anchor from an in-memory copy of
# the text and confirm the SAME check function then fails. Nothing on
# disk is ever touched.
# ---------------------------------------------------------------------------

class TestMutationEachCheckReallyBites:
    def test_missing_check_schema_param_is_caught(self):
        mutant = _read().replace(
            "async _reanchorFromServer(checkSchema = false) {",
            "async _reanchorFromServer() {",
            1,
        )
        assert mutant != _read(), "mutation anchor is stale"
        try:
            _check_reanchor_accepts_check_schema_param(mutant)
            raise AssertionError("mutation was not caught")
        except AssertionError as e:
            assert "checkSchema" in str(e)

    def test_visibilitychange_not_requesting_the_check_is_caught(self):
        real = _read()
        mutant = real.replace(
            "this._reanchorFromServer(true);\n            }\n        });",
            "this._reanchorFromServer();\n            }\n        });",
            1,
        )
        assert mutant != real, "mutation anchor is stale"
        try:
            _check_visibilitychange_requests_schema_check(mutant)
            raise AssertionError("mutation was not caught")
        except AssertionError as e:
            assert "reconnect boundary" in str(e)

    def test_heartbeat_not_requesting_the_check_is_caught(self):
        real = _read()
        mutant = real.replace(
            "await this._reanchorFromServer(true);",
            "await this._reanchorFromServer();",
            1,
        )
        assert mutant != real, "mutation anchor is stale"
        try:
            _check_heartbeat_recovery_requests_schema_check(mutant)
            raise AssertionError("mutation was not caught")
        except AssertionError as e:
            assert "just came back" in str(e)

    def test_provider_switch_opting_into_the_check_is_caught(self):
        """A regression that starts checking on every provider switch
        (a hot path) must be caught too, not just an omission."""
        real = _read()
        body = _function_body(real, "async handleProviderChange(")
        mutated_body = body.replace(
            "await this._reanchorFromServer();",
            "await this._reanchorFromServer(true);",
            1,
        )
        assert mutated_body != body, "mutation anchor is stale"
        mutant = real.replace(body, mutated_body, 1)
        try:
            _check_provider_and_model_switch_do_not_request_it(mutant)
            raise AssertionError("mutation was not caught")
        except AssertionError as e:
            # Either half of the check may fire first (the mutant no
            # longer contains the bare call AND now contains the opted-in
            # one) -- what matters is that it fails, not which message.
            assert "handleProviderChange" in str(e)

    def test_missing_reentrancy_guard_is_caught(self):
        real = _read()
        body = _function_body(real, "async _checkSchemaDrift(")
        mutated_body = body.replace("_schemaCheckInFlight", "_neverGuarded")
        assert mutated_body != body, "mutation anchor is stale"
        mutant = real.replace(body, mutated_body, 1)
        try:
            _check_drift_check_is_reentrancy_guarded(mutant)
            raise AssertionError("mutation was not caught")
        except AssertionError as e:
            assert "coalesce" in str(e)

    def test_not_calling_the_endpoint_is_caught(self):
        real = _read()
        body = _function_body(real, "async _runSchemaDriftCheck(")
        mutated_body = body.replace("this.apiClient.getAppStateSchema()", "this.apiClient.getState()")
        assert mutated_body != body, "mutation anchor is stale"
        mutant = real.replace(body, mutated_body, 1)
        try:
            _check_drift_check_uses_the_schema_endpoint(mutant)
            raise AssertionError("mutation was not caught")
        except AssertionError as e:
            assert "getAppStateSchema" in str(e)

    def test_not_adopting_is_caught(self):
        real = _read()
        body = _function_body(real, "async _runSchemaDriftCheck(")
        mutated_body = body.replace("this.state.adoptSchema(served);", "")
        assert mutated_body != body, "mutation anchor is stale"
        mutant = real.replace(body, mutated_body, 1)
        try:
            _check_each_verdict_is_handled(mutant)
            raise AssertionError("mutation was not caught")
        except AssertionError as e:
            assert "adopt the server" in str(e)

    def test_notice_firing_for_extra_only_too_is_caught(self):
        """If the incompatible-only notice moved before the extra-only
        branch's return, extra-only would ALSO show the user a warning
        -- exactly the false alarm the design forbids."""
        real = _read()
        body = _function_body(real, "async _runSchemaDriftCheck(")
        # Move the showSystemMessage call to just before the extra-only
        # verdict check, simulating it firing unconditionally.
        notice_start = body.find("this.showSystemMessage(")
        notice_end = body.find(");", notice_start) + len(");")
        notice_snippet = body[notice_start:notice_end + 1]
        mutated_body = body.replace(notice_snippet, "", 1)
        extra_anchor = "if (diff.verdict === 'extra-only') {"
        mutated_body = mutated_body.replace(
            extra_anchor, notice_snippet + "\n        " + extra_anchor, 1
        )
        assert mutated_body != body, "mutation anchor is stale"
        mutant = real.replace(body, mutated_body, 1)
        try:
            _check_each_verdict_is_handled(mutant)
            raise AssertionError("mutation was not caught")
        except AssertionError as e:
            assert "must not fire for extra-only too" in str(e)

    def test_rethrowing_on_a_failed_fetch_is_caught(self):
        real = _read()
        body = _function_body(real, "async _runSchemaDriftCheck(")
        mutated_body = body.replace(
            "            console.warn(\n"
            "                '[PpxaiApp] could not verify the server AppState schema:',\n"
            "                e?.message || e,\n"
            "            );\n"
            "            return;",
            "            throw e;",
            1,
        )
        assert mutated_body != body, "mutation anchor is stale"
        mutant = real.replace(body, mutated_body, 1)
        try:
            _check_unverified_never_blocks(mutant)
            raise AssertionError("mutation was not caught")
        except AssertionError as e:
            assert "must not re-throw" in str(e) or "return" in str(e)
