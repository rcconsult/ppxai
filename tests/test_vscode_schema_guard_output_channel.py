"""Source fence: SchemaGuard logs go to the extension's general-purpose
"ppxai" output channel — not "ppxai HTTP" (HttpClient's private
session/SSE/consent tracing channel) and not the Extension Host console.

Owner decision 2026-09-22: yesterday's fix (owner decision 10, 2026-09-21)
routed SchemaGuard's diagnostics into "ppxai HTTP", which is a semantic
mismatch the agent that made that change flagged itself — a compatibility
diagnostic is not HTTP tracing. This module's fences now pin the corrected
wiring: a dedicated `vscode-extension/src/outputChannel.ts` module owns a
single, lazily-created, disposable "ppxai" channel; `chatPanel.ts`'s
`SchemaGuard` host routes `log` through it; `extension.ts` registers the
channel for disposal via `context.subscriptions`.

`schemaGuard.ts` stays vscode-free by design (its four host capabilities —
`adopt`, `resetAdopted`, `log`, `warnUser` — are injected;
`tests/test_app_state_generated_types.py` and
`tests/test_vscode_schema_guard_behavior.py` pin that module import-free of
`vscode`), so the wiring these decisions change lives entirely in
`chatPanel.ts` (which callback `log` is bound to), `outputChannel.ts` (where
the channel actually lives) and `extension.ts` (where it is registered for
disposal). All three are exercised here as source fences, since driving a
real Extension Host output channel needs a real VSCode process.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
VSCODE = ROOT / "vscode-extension"
CHAT_PANEL_TS = VSCODE / "src" / "chatPanel.ts"
HTTP_CLIENT_TS = VSCODE / "src" / "httpClient.ts"
SCHEMA_GUARD_TS = VSCODE / "src" / "schemaGuard.ts"
OUTPUT_CHANNEL_TS = VSCODE / "src" / "outputChannel.ts"
EXTENSION_TS = VSCODE / "src" / "extension.ts"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_log_routed_to_ppxai_channel(chat_panel_source: str) -> None:
    m = re.search(r"log:\s*\(message\)\s*=>\s*(.+?),\n", chat_panel_source)
    assert m, "no `log: (message) => ...` callback found in chatPanel.ts SchemaGuard wiring"
    callback_body = m.group(1)
    assert "console.warn" not in callback_body, (
        f"SchemaGuard's log callback still goes to console.warn: {callback_body!r}"
    )
    assert "logToOutputChannel" not in callback_body, (
        "SchemaGuard's log callback still routes through HttpClient.logToOutputChannel "
        f"(the 'ppxai HTTP' channel): {callback_body!r}"
    )
    assert "logToPpxaiChannel" in callback_body, (
        f"SchemaGuard's log callback does not route through the 'ppxai' output "
        f"channel module: {callback_body!r}"
    )
    assert re.search(
        r"import\s*\{\s*log as logToPpxaiChannel\s*\}\s*from\s*['\"]\./outputChannel['\"]",
        chat_panel_source,
    ), "chatPanel.ts does not import `log` from './outputChannel' as `logToPpxaiChannel`"


def _assert_output_channel_module_owns_one_ppxai_channel(source: str) -> None:
    # Only ONE createOutputChannel call in this module — a second channel
    # was explicitly out of scope for this fix.
    assert source.count("createOutputChannel(") == 1, (
        "outputChannel.ts creates more than one output channel"
    )
    call = re.search(r"createOutputChannel\(\s*(\w+|['\"][^'\"]*['\"])\s*\)", source)
    assert call, "outputChannel.ts has no createOutputChannel(...) call"
    arg = call.group(1)
    if arg.startswith("'") or arg.startswith('"'):
        # Exact name "ppxai" — NOT "ppxai HTTP" or anything else. The
        # quoted literal must contain nothing but "ppxai".
        assert re.fullmatch(r"['\"]ppxai['\"]", arg), (
            f"outputChannel.ts creates a channel named {arg!r}, not exactly 'ppxai'"
        )
    else:
        # Passed as a named constant — resolve it and check ITS value is
        # exactly "ppxai" (not "ppxai HTTP" or anything else).
        const = re.search(rf"\b{re.escape(arg)}\s*=\s*(['\"][^'\"]*['\"])", source)
        assert const, (
            f"outputChannel.ts passes createOutputChannel a name from `{arg}`, "
            "but no `{arg} = '...'` assignment was found to resolve it"
        )
        assert re.fullmatch(r"['\"]ppxai['\"]", const.group(1)), (
            f"outputChannel.ts's channel-name constant `{arg}` resolves to "
            f"{const.group(1)!r}, not exactly 'ppxai'"
        )
    assert re.search(r"export function log\(message: string\): void \{", source), (
        "outputChannel.ts does not export a log(message) helper"
    )


def _assert_channel_registered_for_disposal(extension_source: str) -> None:
    assert re.search(
        r"context\.subscriptions\.push\(\s*getOutputChannel\(\)\s*\)",
        extension_source,
    ), "extension.ts does not register the 'ppxai' output channel for disposal via context.subscriptions"
    assert re.search(
        r"import\s*\{\s*getOutputChannel\s*\}\s*from\s*['\"]\./outputChannel['\"]",
        extension_source,
    ), "extension.ts does not import getOutputChannel from './outputChannel'"


def _assert_http_channel_untouched(source: str) -> None:
    # The pre-existing "ppxai HTTP" channel and its callers stay exactly
    # where they are — this fix must not rename or repurpose it.
    assert "createOutputChannel('ppxai HTTP')" in source, (
        "HttpClient no longer creates its own 'ppxai HTTP' channel — it must stay untouched"
    )
    assert "logToOutputChannel" not in source, (
        "HttpClient.logToOutputChannel has no callers left (SchemaGuard now routes "
        "through outputChannel.ts) and should have been removed as dead code, not left behind"
    )


def _assert_schema_guard_stays_vscode_free() -> None:
    source = _read(SCHEMA_GUARD_TS)
    assert "from 'vscode'" not in source and 'from "vscode"' not in source, (
        "schemaGuard.ts must stay vscode-free (tests/test_app_state_generated_types.py pins this)"
    )


class TestSchemaGuardLogsGoToPpxaiChannel:
    def test_chat_panel_wires_log_to_ppxai_channel(self):
        _assert_log_routed_to_ppxai_channel(_read(CHAT_PANEL_TS))

    def test_output_channel_module_owns_one_ppxai_channel(self):
        _assert_output_channel_module_owns_one_ppxai_channel(_read(OUTPUT_CHANNEL_TS))

    def test_extension_registers_channel_for_disposal(self):
        _assert_channel_registered_for_disposal(_read(EXTENSION_TS))

    def test_http_channel_untouched_and_dead_code_removed(self):
        _assert_http_channel_untouched(_read(HTTP_CLIENT_TS))

    def test_schema_guard_module_itself_is_untouched_and_vscode_free(self):
        _assert_schema_guard_stays_vscode_free()


class TestMutationVerification:
    def test_fence_catches_revert_to_console_warn(self):
        source = _read(CHAT_PANEL_TS)
        mutated = source.replace(
            "log: (message) => logToPpxaiChannel(message),",
            "log: (message) => console.warn(message),",
        )
        assert mutated != source
        try:
            _assert_log_routed_to_ppxai_channel(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("fence did not catch a revert to console.warn")

    def test_fence_catches_reroute_to_http_channel(self):
        source = _read(CHAT_PANEL_TS)
        mutated = source.replace(
            "log: (message) => logToPpxaiChannel(message),",
            "log: (message) => this._backend.logToOutputChannel(message),",
        )
        assert mutated != source
        try:
            _assert_log_routed_to_ppxai_channel(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("fence did not catch a reroute to the 'ppxai HTTP' channel")

    def test_fence_catches_dropped_disposal_registration(self):
        source = _read(EXTENSION_TS)
        mutated = source.replace(
            "    context.subscriptions.push(getOutputChannel());\n",
            "",
        )
        assert mutated != source
        try:
            _assert_channel_registered_for_disposal(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("fence did not catch a dropped context.subscriptions.push registration")

    def test_fence_catches_renamed_channel(self):
        source = _read(OUTPUT_CHANNEL_TS)
        mutated = source.replace(
            "createOutputChannel(CHANNEL_NAME)",
            "createOutputChannel('ppxai HTTP')",
        )
        assert mutated != source
        try:
            _assert_output_channel_module_owns_one_ppxai_channel(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("fence did not catch the channel name changing away from 'ppxai'")

    def test_fence_catches_orphaned_dead_code_left_behind(self):
        source = _read(HTTP_CLIENT_TS)
        mutated = source.replace(
            "    }\n}\n\n/**\n * Singleton instance management\n */",
            (
                "    }\n\n    logToOutputChannel(message: string): void {\n"
                "        this.outputChannel.appendLine(message);\n"
                "    }\n}\n\n/**\n * Singleton instance management\n */"
            ),
        )
        assert mutated != source, "test fixture text did not match httpClient.ts — update the anchor"
        try:
            _assert_http_channel_untouched(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("fence did not catch dead logToOutputChannel being left behind")
