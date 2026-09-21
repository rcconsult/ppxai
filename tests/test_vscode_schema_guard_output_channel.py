"""Source fence: SchemaGuard logs go to the ppxai output channel, not the
Extension Host console (owner decision 10, 2026-09-21,
`docs/plan-adr-0007-completion-service.md`).

`schemaGuard.ts` stays vscode-free by design (its four host capabilities —
`adopt`, `resetAdopted`, `log`, `warnUser` — are injected;
`tests/test_app_state_generated_types.py` and
`tests/test_vscode_schema_guard_behavior.py` pin that module import-free of
`vscode`), so the wiring this decision changes lives entirely in
`chatPanel.ts` (which callback `log` is bound to) and `httpClient.ts`
(where the extension's one output channel — `vscode.window.createOutputChannel
('ppxai HTTP')` — actually lives). Both are exercised here as source
fences, since driving a real Extension Host output channel needs a real
VSCode process.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
VSCODE = ROOT / "vscode-extension"
CHAT_PANEL_TS = VSCODE / "src" / "chatPanel.ts"
HTTP_CLIENT_TS = VSCODE / "src" / "httpClient.ts"
SCHEMA_GUARD_TS = VSCODE / "src" / "schemaGuard.ts"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_log_routed_to_output_channel(source: str) -> None:
    m = re.search(r"log:\s*\(message\)\s*=>\s*(.+?),\n", source)
    assert m, "no `log: (message) => ...` callback found in chatPanel.ts SchemaGuard wiring"
    callback_body = m.group(1)
    assert "console.warn" not in callback_body, (
        f"SchemaGuard's log callback still goes to console.warn: {callback_body!r}"
    )
    assert "logToOutputChannel" in callback_body, (
        f"SchemaGuard's log callback does not route through logToOutputChannel: {callback_body!r}"
    )


def _assert_http_client_owns_output_channel_method(source: str) -> None:
    assert "createOutputChannel(" in source, "no vscode.window.createOutputChannel(...) call found"
    m = re.search(
        r"logToOutputChannel\(message: string\): void \{([^}]*)\}",
        source,
    )
    assert m, "HttpClient does not declare a logToOutputChannel(message) method"
    assert "outputChannel.appendLine" in m.group(1), (
        "logToOutputChannel does not write through the output channel"
    )


def _assert_schema_guard_stays_vscode_free() -> None:
    source = _read(SCHEMA_GUARD_TS)
    assert "from 'vscode'" not in source and 'from "vscode"' not in source, (
        "schemaGuard.ts must stay vscode-free (tests/test_app_state_generated_types.py pins this)"
    )


class TestSchemaGuardLogsGoToOutputChannel:
    def test_chat_panel_wires_log_to_output_channel(self):
        _assert_log_routed_to_output_channel(_read(CHAT_PANEL_TS))

    def test_http_client_exposes_output_channel_method(self):
        _assert_http_client_owns_output_channel_method(_read(HTTP_CLIENT_TS))

    def test_schema_guard_module_itself_is_untouched_and_vscode_free(self):
        _assert_schema_guard_stays_vscode_free()


class TestMutationVerification:
    def test_fence_catches_revert_to_console_warn(self):
        source = _read(CHAT_PANEL_TS)
        mutated = source.replace(
            "log: (message) => this._backend.logToOutputChannel(message),",
            "log: (message) => console.warn(message),",
        )
        assert mutated != source
        try:
            _assert_log_routed_to_output_channel(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("fence did not catch a revert to console.warn")

    def test_fence_catches_removed_output_channel_method(self):
        source = _read(HTTP_CLIENT_TS)
        mutated = source.replace(
            "    logToOutputChannel(message: string): void {\n"
            "        this.outputChannel.appendLine(message);\n"
            "    }\n",
            "",
        )
        assert mutated != source
        try:
            _assert_http_client_owns_output_channel_method(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("fence did not catch a removed logToOutputChannel method")
