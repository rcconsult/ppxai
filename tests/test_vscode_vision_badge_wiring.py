"""Source fences for VSCode vision-badge/gate wiring that cannot be driven
under pytest without a real webview + extension host (owner decision 8,
2026-09-21, `docs/plan-adr-0007-completion-service.md`).

Four wiring facts are pinned here by reading the real source, each
mutation-verified (delete the call, assert the fence fails, restore):

  1. The webview's `stateSync` handler updates `activeModelSupportsVision`
     from the `modelSupportsVision` FIELD (never a command name) and
     drives the attach-button badge from it.
  2. `stageFile()` calls the pure `shouldBlockImageAttach` decision
     (tested in isolation in `tests/test_vscode_vision_gate_behavior.py`)
     rather than re-implementing the condition inline.
  3. `_reanchorFromServer()` forwards the re-anchored AppState to the
     webview (`postMessage({ type: 'stateSync', ... })`) — without this,
     the extension-host AppState re-anchors but the webview's own mirror
     never learns about it.
  4. The command-palette provider/model switch handlers in `extension.ts`
     call the new `reanchorState()` after a successful switch — mirrors
     web's `handleProviderChange`/`handleModelChange` calling
     `_reanchorFromServer()` directly instead of waiting for the next SSE
     push to drain from the engine queue.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
VSCODE = ROOT / "vscode-extension"
MAIN_JS = VSCODE / "media" / "webview" / "main.js"
CHAT_PANEL_TS = VSCODE / "src" / "chatPanel.ts"
EXTENSION_TS = VSCODE / "src" / "extension.ts"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_state_sync_drives_badge(source: str) -> None:
    # The stateSync case must react to the modelSupportsVision FIELD
    # (camelCase, as mapped from the Python `model_supports_vision` field)
    # and feed it into both the tracked flag and the badge updater.
    m = re.search(
        r"if\s*\(\s*c\.modelSupportsVision\s*!==\s*undefined\s*\)\s*\{([^}]*)\}",
        source,
    )
    assert m, "no `c.modelSupportsVision !== undefined` guard found in main.js stateSync handling"
    body = m.group(1)
    assert "activeModelSupportsVision" in body, "guard does not update activeModelSupportsVision"
    assert "updateAttachBadge" in body, "guard does not call updateAttachBadge"


def _assert_stage_file_calls_gate(source: str) -> None:
    assert "shouldBlockImageAttach(isImage, activeModelSupportsVision)" in source, (
        "stageFile() no longer calls the pure shouldBlockImageAttach gate"
    )


def _assert_reanchor_forwards_state_sync(source: str) -> None:
    m = re.search(
        r"private async _reanchorFromServer\(\): Promise<void> \{(.*?)\n    \}",
        source,
        re.DOTALL,
    )
    assert m, "_reanchorFromServer method not found in chatPanel.ts"
    body = m.group(1)
    assert "updateFromPython" in body, "_reanchorFromServer no longer re-anchors AppState"
    assert re.search(r"postMessage\(\s*\{\s*type:\s*'stateSync'", body), (
        "_reanchorFromServer does not forward the re-anchored state to the webview "
        "(postMessage({ type: 'stateSync', ... }))"
    )


def _assert_switch_handlers_reanchor(source: str) -> None:
    provider_block_match = re.search(
        r"registerCommand\('ppxai\.switchProvider'.*?\n\s*\}\)\s*\n\s*\);",
        source,
        re.DOTALL,
    )
    model_block_match = re.search(
        r"registerCommand\('ppxai\.switchModel'.*?\n\s*\}\)\s*\n\s*\);",
        source,
        re.DOTALL,
    )
    assert provider_block_match, "ppxai.switchProvider command registration not found"
    assert model_block_match, "ppxai.switchModel command registration not found"
    assert "chatViewProvider.reanchorState()" in provider_block_match.group(0), (
        "ppxai.switchProvider does not re-anchor AppState after a successful switch"
    )
    assert "chatViewProvider.reanchorState()" in model_block_match.group(0), (
        "ppxai.switchModel does not re-anchor AppState after a successful switch"
    )


class TestVisionBadgeWiringIsPresent:
    def test_state_sync_drives_badge(self):
        _assert_state_sync_drives_badge(_read(MAIN_JS))

    def test_stage_file_calls_gate(self):
        _assert_stage_file_calls_gate(_read(MAIN_JS))

    def test_reanchor_forwards_state_sync(self):
        _assert_reanchor_forwards_state_sync(_read(CHAT_PANEL_TS))

    def test_switch_handlers_reanchor(self):
        _assert_switch_handlers_reanchor(_read(EXTENSION_TS))


class TestMutationVerification:
    """Each fence must actually fail when the wiring it pins is removed."""

    def test_state_sync_fence_catches_removed_badge_call(self):
        source = _read(MAIN_JS)
        mutated = source.replace(
            "activeModelSupportsVision = !!c.modelSupportsVision;\n"
            "                    updateAttachBadge(activeModelSupportsVision);",
            "activeModelSupportsVision = !!c.modelSupportsVision;",
        )
        assert mutated != source
        try:
            _assert_state_sync_drives_badge(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("fence did not catch a removed updateAttachBadge call")

    def test_stage_file_fence_catches_inline_condition(self):
        source = _read(MAIN_JS)
        mutated = source.replace(
            "shouldBlockImageAttach(isImage, activeModelSupportsVision)",
            "isImage && activeModelSupportsVision === false",
        )
        assert mutated != source
        try:
            _assert_stage_file_calls_gate(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("fence did not catch reverting to the inline condition")

    def test_reanchor_fence_catches_missing_forward(self):
        source = _read(CHAT_PANEL_TS)
        mutated = source.replace(
            "const mapped = this._appState.updateFromPython(snapshot);\n"
            "            this._view?.webview.postMessage({ type: 'stateSync', changes: mapped });",
            "this._appState.updateFromPython(snapshot);",
        )
        assert mutated != source
        try:
            _assert_reanchor_forwards_state_sync(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("fence did not catch a dropped webview postMessage forward")

    def test_switch_handlers_fence_catches_missing_reanchor(self):
        source = _read(EXTENSION_TS)
        mutated = source.replace(
            "void chatViewProvider.reanchorState();\n",
            "",
        )
        assert mutated != source
        try:
            _assert_switch_handlers_reanchor(mutated)
        except AssertionError:
            pass
        else:
            raise AssertionError("fence did not catch removed reanchorState() calls")
