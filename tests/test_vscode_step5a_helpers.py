"""Static structural tests for VSCode Step 5a helpers (v1.18.1).

The VSCode dispatcher rewrite ships in three sub-commits:

  5a (this commit) — typed envelope + two helper modules
                     (sideEffectsHandler.ts, commandRenderer.ts).
                     chatPanel.ts is otherwise untouched.
  5b — chatPanel.ts dispatcher rewrite using the helpers.
  5c — REST piggyback consumer (Phase B) + cwd_anchor (Phase D).

These tests pin the helper contracts so 5b can be a clean drop-in:
  - executeCommand returns CommandEnvelope, not the legacy result
    shape.
  - SideEffectsHandler.apply is async and handles every v1.18.1 kind.
  - CommandRenderer.render is sync (post-only, no awaits) and covers
    the seven core result types.
  - Both modules use a SideEffectHost / RendererHost interface so
    they don't import ChatViewProvider directly (compileable in
    isolation).
"""

from __future__ import annotations

import re
from pathlib import Path

EXT_DIR = Path(__file__).resolve().parents[1] / "vscode-extension" / "src"


def _read(rel: str) -> str:
    return (EXT_DIR / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# httpClient.ts envelope
# ---------------------------------------------------------------------------

class TestHttpClientEnvelope:
    def test_command_envelope_interface_exported(self):
        src = _read("httpClient.ts")
        assert "interface CommandEnvelope" in src

    def test_envelope_has_v1_fields(self):
        src = _read("httpClient.ts")
        match = re.search(
            r"interface\s+CommandEnvelope\s*\{[\s\S]*?\}",
            src,
        )
        assert match
        body = match.group(0)
        for field in ("ok", "result", "side_effects", "version"):
            assert field in body, f"CommandEnvelope missing {field!r}"
        assert "events" in body, (
            "CommandEnvelope must include events[] for Phase B piggyback"
        )

    def test_executeCommand_returns_envelope(self):
        """The TS signature must use the typed envelope so callers
        get compile-time errors when they reach for the old fields
        (`.message`, `.type`) directly on the response."""
        src = _read("httpClient.ts")
        # Find the executeCommand declaration
        match = re.search(
            r"async\s+executeCommand\([^\)]*\):\s*Promise<([^>]+)>",
            src,
        )
        assert match, "could not find executeCommand signature"
        return_type = match.group(1)
        assert "CommandEnvelope" in return_type, (
            f"executeCommand return type should be CommandEnvelope, "
            f"got: {return_type}"
        )

    def test_unknown_command_carries_status_404(self):
        """The 404 path attaches err.status so the dispatcher can
        show a friendly 'Unknown command' instead of a raw failure."""
        src = _read("httpClient.ts")
        # Find the executeCommand body
        match = re.search(
            r"async\s+executeCommand[\s\S]*?\n\s{4}\}",
            src,
        )
        assert match
        body = match.group(0)
        assert "404" in body or "status" in body, (
            "executeCommand must surface 404 specifically"
        )


# ---------------------------------------------------------------------------
# sideEffectsHandler.ts
# ---------------------------------------------------------------------------

class TestSideEffectsHandlerModule:
    def test_module_file_exists(self):
        assert (EXT_DIR / "sideEffectsHandler.ts").exists()

    def test_class_defined(self):
        src = _read("sideEffectsHandler.ts")
        assert "export class SideEffectsHandler" in src

    def test_apply_method_is_async(self):
        src = _read("sideEffectsHandler.ts")
        assert re.search(
            r"async\s+apply\s*\(\s*sideEffects",
            src,
        ), "apply() must be async (vscode.* APIs are async)"

    def test_handles_every_v18_1_kind(self):
        """Drift fence: every kind in the v1.18.1 SideEffectKind
        constants must have a case in the VSCode dispatcher,
        EXCEPT for kinds the spec marks as web-only / no-op."""
        src = _read("sideEffectsHandler.ts")
        for kind in (
            "open_editor",
            "open_viewer",
            "show_image",
            "show_pdf",
            "reveal_in_explorer",
            "open_terminal",
            "run_shell",
            "open_html_preview",
            "refresh_file_tree",
            "set_theme",
            "copy_to_clipboard",
            "attach_file",
            "prompt_quick_pick",
            "prompt_text",
            "notify",
            "vscode_delegate",
        ):
            assert kind in src, (
                f"sideEffectsHandler.ts missing handler for kind: {kind}"
            )

    def test_uses_sideeffect_host_interface(self):
        """The handler must take a SideEffectHost interface, not
        the full ChatViewProvider — so it's testable in isolation
        and 5a doesn't depend on chatPanel.ts changes."""
        src = _read("sideEffectsHandler.ts")
        assert "export interface SideEffectHost" in src
        assert "import type { ChatViewProvider }" not in src, (
            "Should not import ChatViewProvider directly — use SideEffectHost"
        )

    def test_open_editor_uses_showtextdocument_primary_column(self):
        """Per the audit table in
        docs/TODO-v1.18.1-command-unification.md: open_editor opens
        in the PRIMARY editor column with preview=False so it
        survives subsequent clicks."""
        src = _read("sideEffectsHandler.ts")
        # Find the OPEN_EDITOR case
        match = re.search(
            r"case KIND\.OPEN_EDITOR\s*:[\s\S]*?return;",
            src,
        )
        assert match
        body = match.group(0)
        assert "showTextDocument" in body
        assert "preview" in body and "false" in body, (
            "open_editor must use preview: false to survive clicks"
        )
        assert "ViewColumn.One" in body or "viewColumn" in body

    def test_open_viewer_uses_vscode_open_with_preview(self):
        src = _read("sideEffectsHandler.ts")
        match = re.search(
            r"case KIND\.OPEN_VIEWER\s*:[\s\S]*?return;",
            src,
        )
        assert match
        body = match.group(0)
        assert "vscode.open" in body
        assert "preview" in body and "true" in body, (
            "open_viewer must use preview: true (peek mode)"
        )

    def test_open_terminal_uses_createterminal(self):
        src = _read("sideEffectsHandler.ts")
        match = re.search(
            r"case KIND\.OPEN_TERMINAL\s*:[\s\S]*?return;",
            src,
        )
        assert match
        body = match.group(0)
        assert "createTerminal" in body, (
            "open_terminal must use vscode.window.createTerminal"
        )

    def test_run_shell_pre_types_command(self):
        src = _read("sideEffectsHandler.ts")
        # Match the whole case block — start at `case KIND.RUN_SHELL`,
        # stop at the next `case KIND.` (or `default:`). The simple
        # `*?return;` pattern stops at the first early-return guard
        # which doesn't include the meat of the handler.
        match = re.search(
            r"case KIND\.RUN_SHELL\s*:[\s\S]*?(?=\n\s+case KIND\.|\n\s+default:)",
            src,
        )
        assert match
        body = match.group(0)
        assert "createTerminal" in body
        assert "sendText" in body, (
            "run_shell must call terminal.sendText to pre-type the command"
        )

    def test_copy_to_clipboard_uses_vscode_clipboard(self):
        src = _read("sideEffectsHandler.ts")
        match = re.search(
            r"case KIND\.COPY_TO_CLIPBOARD\s*:[\s\S]*?return;",
            src,
        )
        assert match
        body = match.group(0)
        assert "vscode.env.clipboard.writeText" in body, (
            "copy_to_clipboard must use vscode.env.clipboard, not "
            "any web/server-side fallback"
        )

    def test_prompt_quick_pick_uses_native_quickpick(self):
        src = _read("sideEffectsHandler.ts")
        match = re.search(
            r"case KIND\.PROMPT_QUICK_PICK\s*:[\s\S]*?(?=\n\s+case KIND\.|\n\s+default:)",
            src,
        )
        assert match
        body = match.group(0)
        assert "showQuickPick" in body, (
            "prompt_quick_pick must use vscode.window.showQuickPick"
        )

    def test_vscode_delegate_dispatches_executeCommand(self):
        src = _read("sideEffectsHandler.ts")
        # vscode_delegate is the LAST case; stop at `default:`.
        match = re.search(
            r"case KIND\.VSCODE_DELEGATE\s*:[\s\S]*?(?=\n\s+default:)",
            src,
        )
        assert match
        body = match.group(0)
        assert "executeCommand" in body

    def test_per_handler_errors_are_caught(self):
        """One bad side-effect must not break the rest of the
        batch (e.g. clipboard denied shouldn't prevent terminal
        from opening)."""
        src = _read("sideEffectsHandler.ts")
        # apply() body has try/catch around each handler call
        match = re.search(
            r"async\s+apply\s*\([\s\S]*?\}\s*\}\s*\}",
            src,
        )
        assert match, "could not extract apply() body"
        body = match.group(0)
        assert "try" in body and "catch" in body


# ---------------------------------------------------------------------------
# commandRenderer.ts
# ---------------------------------------------------------------------------

class TestCommandRendererModule:
    def test_module_file_exists(self):
        assert (EXT_DIR / "commandRenderer.ts").exists()

    def test_class_defined(self):
        src = _read("commandRenderer.ts")
        assert "export class CommandRenderer" in src

    def test_render_method_exists(self):
        src = _read("commandRenderer.ts")
        assert re.search(r"\brender\s*\(\s*result", src), (
            "CommandRenderer.render(result) not found"
        )

    def test_handles_seven_core_result_types(self):
        src = _read("commandRenderer.ts")
        for type_name in (
            "NotificationResult",
            "ConfirmationResult",
            "ErrorResult",
            "MarkdownResult",
            "TableResult",
            "TreeResult",
            "KeyValueResult",
        ):
            assert type_name in src, (
                f"CommandRenderer missing case for {type_name}"
            )

    def test_uses_renderer_host_interface(self):
        src = _read("commandRenderer.ts")
        assert "export interface RendererHost" in src

    def test_unknown_type_falls_through_to_message(self):
        src = _read("commandRenderer.ts")
        # The default branch posts result.message
        assert "default" in src
        # No throw — the renderer is best-effort
        assert "throw" not in src or src.count("throw") == 0, (
            "Renderer should not throw — unknown types fall through"
        )

    def test_table_result_emits_markdown_table(self):
        """Web's renderer uses SharedFormatters.formatTableResult.
        VSCode-side reimplements it — but the output should be
        parseable as a markdown table (so the webview's marked.js
        renders it as an actual table)."""
        src = _read("commandRenderer.ts")
        # Match `private _formatTable(...)` body specifically
        match = re.search(
            r"private\s+_formatTable\s*\([^\)]*\)\s*:\s*\w+\s*\{[\s\S]*?\n    \}",
            src,
        )
        assert match, "could not find private _formatTable method"
        body = match.group(0)
        # Markdown table needs the pipe characters and the
        # `|---|---|` separator row
        assert "|" in body
        assert "---" in body, "missing markdown table header separator"


# ---------------------------------------------------------------------------
# Cross-client parity (web ↔ VSCode side-effects)
# ---------------------------------------------------------------------------

class TestCrossClientParity:
    """Both clients must handle the same kinds. Drift between web's
    side-effects.js and VSCode's sideEffectsHandler.ts produces the
    exact "rare misalignment" bug the determinism plan was written
    to prevent."""

    def test_web_and_vscode_handle_same_kind_set(self):
        web_src = (
            Path(__file__).resolve().parents[1]
            / "ppxai" / "web" / "shared" / "side-effects.js"
        ).read_text(encoding="utf-8")
        vscode_src = _read("sideEffectsHandler.ts")
        for kind in (
            "open_editor", "open_viewer", "show_image", "show_pdf",
            "reveal_in_explorer", "open_terminal", "run_shell",
            "open_html_preview", "refresh_file_tree", "set_theme",
            "copy_to_clipboard", "attach_file", "prompt_quick_pick",
            "prompt_text", "notify", "vscode_delegate",
        ):
            assert kind in web_src, f"web missing kind: {kind}"
            assert kind in vscode_src, f"VSCode missing kind: {kind}"
