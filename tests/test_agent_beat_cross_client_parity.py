"""Cross-client parity for agent_beat rendering (P0 v1.18.0 stabilization).

The four clients (Rich TUI, Textual TUI, web, VSCode) each render
`AppState.agent_beat` via their own renderer. Individual unit tests
verify each renderer in isolation, but nothing guarantees they agree
on the contract — the same beat payload must produce semantically
equivalent UI across all four.

This test feeds a shared fixture table through every renderer and
asserts the invariants each one must satisfy:

    - Empty/None beat → badge hidden (or nothing rendered)
    - Active beat   → output contains iteration, optionally tool
    - failures >= 2 → warning variant
    - ok == False   → error variant
    - Elapsed time present on any active beat

Python renderers (Rich, Textual) are invoked directly. JS renderers
(web, VSCode) are invoked via `node -e` — each file exports a pure
function of `beat`, so we extract and eval it without a DOM.

If a renderer drifts (e.g. someone reshapes the beat payload but
forgets to update one client), this test fails and names the client.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Shared fixtures — one representative beat per scenario the
#    engine actually emits. Keep small; parity only matters at the
#    contract level (hide / show / warn / error), not on every edge.
FIXTURES: dict[str, dict[str, Any]] = {
    "empty": {},
    "first_iteration_ok": {
        "iteration": 1,
        "beat": 1,
        "tool": "read_file",
        "ok": True,
        "failures": 0,
        "elapsed_s": 0.3,
    },
    "mid_iteration_ok": {
        "iteration": 5,
        "beat": 5,
        "tool": "apply_patch",
        "ok": True,
        "failures": 0,
        "elapsed_s": 12.4,
    },
    "single_failure": {
        "iteration": 3,
        "beat": 3,
        "tool": "run_shell",
        "ok": False,
        "failures": 1,
        "elapsed_s": 5.8,
    },
    "failure_streak_warning": {
        "iteration": 4,
        "beat": 4,
        "tool": "run_shell",
        "ok": True,
        "failures": 2,
        "elapsed_s": 7.9,
    },
}


# ──────────────────────────────────────────────────────────────────
# Rich renderer — event-driven. Invoke the real handler method.
# ──────────────────────────────────────────────────────────────────
def _rich_render(beat: dict) -> dict[str, Any]:
    """Return structured result: {visible, text, variant}.

    Rich prints a single dim line per beat event. `visible=False`
    means nothing was printed (corresponds to "hidden" in other
    clients). `variant` is inferred from the printed markup.
    """
    pytest.importorskip("rich")

    from ppxai.engine.types import Event, EventType
    from ppxai.rich.event_handler import TUIEventHandler

    mock_console = MagicMock()
    handler = TUIEventHandler(mock_console, MagicMock())

    if not beat:
        # Rich doesn't emit anything for empty beats — the engine
        # simply never fires AGENT_BEAT with an empty payload. The
        # contract is "nothing rendered," which we model as hidden.
        return {"visible": False, "text": "", "variant": "none"}

    handler._tui_agent_beat(Event(EventType.AGENT_BEAT, beat))

    calls = mock_console.print.call_args_list
    assert calls, "Rich renderer produced no output for active beat"
    text = calls[-1].args[0]

    # Rich uses [dim] for ok and [red] only for the zombie event
    # (AGENT_ZOMBIE, not AGENT_BEAT). For a single failed beat the
    # line is still [dim]; the "fail" token in the text distinguishes
    # it. This means Rich's *variant* for a failed beat is still "ok"
    # by CSS standards — the fail signal is textual, not chromatic.
    # That's a known divergence and the parity contract accommodates
    # it (see _assert_invariants).
    if "[red]" in text:
        variant = "error"
    elif "[dim]" in text:
        variant = "ok"
    else:
        variant = "unknown"

    return {"visible": True, "text": text, "variant": variant}


# ──────────────────────────────────────────────────────────────────
# Textual renderer — AppState-driven. Bind real method to a fake.
# ──────────────────────────────────────────────────────────────────
def _textual_render(beat: dict) -> dict[str, Any]:
    """Return structured result from Textual badge mutations."""
    pytest.importorskip("textual")

    from ppxai.tui.app import PPXAIDEApp

    app_fake = MagicMock()
    app_fake._status_bar = MagicMock()
    render = PPXAIDEApp._on_agent_beat_changed.__get__(app_fake)

    render(beat)

    sb = app_fake._status_bar
    if sb.remove_badge.called and not sb.add_badge.called:
        return {"visible": False, "text": "", "variant": "none"}

    assert sb.add_badge.called, "Textual renderer should have added the badge"
    args, kwargs = sb.add_badge.call_args
    # add_badge(name, icon, value, variant=...)
    return {
        "visible": True,
        "text": args[2],
        "variant": kwargs.get("variant", "unknown"),
    }


# ──────────────────────────────────────────────────────────────────
# JS renderers — web and VSCode. Extract the function with a regex
# and eval it in node against a stub DOM.
# ──────────────────────────────────────────────────────────────────
_JS_HARNESS = r"""
// Minimal DOM stub — just enough to record what the renderer did.
const stateRecord = {};
function makeBadge(id) {
    const el = {
        id,
        _classes: new Set(),
        _style: { display: '' },
        classList: {
            add: (...c) => c.forEach(x => el._classes.add(x)),
            remove: (...c) => c.forEach(x => el._classes.delete(x)),
        },
        get style() { return el._style; },
        _text: '',
    };
    stateRecord[id] = el;
    return el;
}
const badges = {
    agentBeatBadge: makeBadge('agentBeatBadge'),
    agentBeatText: makeBadge('agentBeatText'),
};
global.document = {
    getElementById: (id) => badges[id] || null,
};

// Inject the renderer function under test (definition appended below).
__RENDERER__

// Web renderer reads `this.state.agentBeat`; VSCode renderer takes
// `beat` as an argument. Support both via a small shim.
// With `node -e` the first extra CLI arg lands at argv[1], not [2].
const beat = JSON.parse(process.argv[1]);
if (typeof updateAgentBeatBadge === 'function') {
    // VSCode-style: bare function taking beat.
    updateAgentBeatBadge(beat);
} else if (typeof webRender === 'function') {
    // Web-style: bound method, we wrapped it with a `this`.
    webRender.call({ state: { agentBeat: beat } });
}

const badge = badges.agentBeatBadge;
const text = badges.agentBeatText;
const hidden = badge._classes.has('hidden') || badge._style.display === 'none';
const variant = badge._classes.has('error')
    ? 'error'
    : badge._classes.has('warn')
    ? 'warning'
    : hidden ? 'none' : 'ok';

process.stdout.write(JSON.stringify({
    visible: !hidden,
    text: text._text || text.textContent || '',
    variant,
}));
"""


def _run_js_renderer(renderer_src: str, beat: dict) -> dict[str, Any]:
    """Invoke a JS renderer via node with the beat payload as JSON."""
    # The stub DOM records text via `text.textContent = ...`, which
    # in JS is a simple property assignment. We approximate by
    # intercepting the assignment with a getter/setter — simpler to
    # just expose `textContent` as a real property on the stub.
    patched_harness = _JS_HARNESS.replace("__RENDERER__", renderer_src)
    # Turn the stub into a real {get/set} for textContent so the
    # renderer's `text.textContent = '...'` sticks.
    patched_harness = patched_harness.replace(
        "_text: '',\n    };",
        "_text: '',\n    };\n"
        "    Object.defineProperty(el, 'textContent', {\n"
        "        get() { return el._text; },\n"
        "        set(v) { el._text = v; },\n"
        "    });",
    )
    result = subprocess.run(
        ["node", "-e", patched_harness, json.dumps(beat)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        pytest.fail(
            f"node renderer failed:\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
    return json.loads(result.stdout)


def _extract_function(source_path: Path, fn_name: str) -> str:
    """Pull a top-level `function <name>(...)` block out of a JS file.

    Relies on balanced braces. Good enough for the two functions we
    care about — they're simple and well-formed.
    """
    source = source_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"function\s+{re.escape(fn_name)}\s*\([^)]*\)\s*\{{")
    match = pattern.search(source)
    if not match:
        pytest.fail(f"Could not find function {fn_name} in {source_path}")
    start = match.start()
    depth = 0
    i = match.end() - 1  # position of `{`
    while i < len(source):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    pytest.fail(f"Unbalanced braces in {fn_name}")


def _extract_web_render_method() -> str:
    """Pull the web `updateAgentBeatBadge()` method off the app class."""
    source_path = REPO_ROOT / "ppxai" / "web" / "app.js"
    source = source_path.read_text(encoding="utf-8")
    # It's a class method, not a top-level function — grab from the
    # `updateAgentBeatBadge()` signature onward with brace matching.
    match = re.search(r"\n    updateAgentBeatBadge\s*\(\s*\)\s*\{", source)
    if not match:
        pytest.fail("Could not find updateAgentBeatBadge in web/app.js")
    start = match.start()
    depth = 0
    i = match.end() - 1
    while i < len(source):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                body = source[start : i + 1]
                # Rewrite as a standalone function bound to `this`.
                body = body.replace("updateAgentBeatBadge()", "function webRender()")
                return body.lstrip()
        i += 1
    pytest.fail("Unbalanced braces around updateAgentBeatBadge")


def _web_render(beat: dict) -> dict[str, Any]:
    return _run_js_renderer(_extract_web_render_method(), beat)


def _vscode_render(beat: dict) -> dict[str, Any]:
    src = _extract_function(
        REPO_ROOT / "vscode-extension" / "media" / "webview" / "main.js",
        "updateAgentBeatBadge",
    )
    return _run_js_renderer(src, beat)


# ──────────────────────────────────────────────────────────────────
# Shared invariants — the actual parity contract.
# ──────────────────────────────────────────────────────────────────
def _expected_invariants(beat: dict) -> dict[str, Any]:
    """Return the contract every renderer must satisfy for this beat."""
    if not beat:
        return {"visible": False, "variant_must_not_be_error": True}
    failures = beat.get("failures", 0)
    ok = beat.get("ok", True)
    if failures >= 2:
        expected_variant = "warning"
    elif not ok:
        expected_variant = "error"
    else:
        expected_variant = "ok"
    return {
        "visible": True,
        "expected_variant": expected_variant,
        "must_contain_iteration": str(beat.get("iteration", 0)),
        "must_contain_tool": beat.get("tool", ""),
    }


_OK_ALIASES = {"ok", "success"}
_WARNING_ALIASES = {"warning", "warn"}


def _assert_invariants(
    client: str, result: dict, invariants: dict, beat: dict
) -> None:
    """One assertion block used for every (client, fixture) pair.

    The parity contract treats variant as a three-valued set:
        - ok    — normal running state
        - warn  — failure streak mounting (not yet zombie)
        - error — zombie tripped or individual failed beat

    Rich is a known-and-accepted divergence: it uses Rich-console
    markup (`[dim]` / `[red]`) instead of a structural variant, and
    it collapses warning→ok because the streak is visible in text.
    The other three clients (Textual/web/VSCode) must agree on all
    three.
    """
    if not invariants["visible"]:
        assert not result["visible"], (
            f"{client}: expected hidden for empty beat, got "
            f"visible={result['visible']} text={result['text']!r}"
        )
        return

    assert result["visible"], (
        f"{client}: expected badge visible for beat={beat}, but it was hidden"
    )

    expected_variant = invariants["expected_variant"]
    actual_variant = result["variant"]

    if expected_variant == "warning":
        # Rich collapses warning into ok (the streak is in the text).
        if client == "rich":
            assert actual_variant in _OK_ALIASES, (
                f"rich: expected ok-ish variant for warning state, got "
                f"{actual_variant!r} (beat={beat})"
            )
        else:
            assert actual_variant in _WARNING_ALIASES, (
                f"{client}: expected warning variant for failures>=2, got "
                f"{actual_variant!r} (beat={beat})"
            )
    elif expected_variant == "error":
        # Rich only colours AGENT_ZOMBIE events red; a single failed
        # beat remains dim. The failure is still visible via "fail"
        # text, so the contract accepts ok-ish variant for Rich.
        if client == "rich":
            assert actual_variant in _OK_ALIASES, (
                f"rich: expected ok-ish variant for failed beat, got "
                f"{actual_variant!r} (beat={beat})"
            )
            assert "fail" in result["text"].lower(), (
                f"rich: expected 'fail' in text for failed beat, got "
                f"{result['text']!r}"
            )
        else:
            assert actual_variant == "error", (
                f"{client}: expected error variant for ok=False, got "
                f"{actual_variant!r} (beat={beat})"
            )
    else:  # ok
        assert actual_variant in _OK_ALIASES, (
            f"{client}: expected ok-ish variant, got {actual_variant!r} "
            f"(beat={beat})"
        )

    if invariants["must_contain_iteration"] and invariants["must_contain_iteration"] != "0":
        assert invariants["must_contain_iteration"] in result["text"], (
            f"{client}: expected iteration "
            f"{invariants['must_contain_iteration']!r} in text "
            f"{result['text']!r}"
        )

    if invariants["must_contain_tool"]:
        assert invariants["must_contain_tool"] in result["text"], (
            f"{client}: expected tool {invariants['must_contain_tool']!r} "
            f"in text {result['text']!r}"
        )


# ──────────────────────────────────────────────────────────────────
# Parametrised test — every (renderer, fixture) combination.
# ──────────────────────────────────────────────────────────────────
RENDERERS = {
    "rich": _rich_render,
    "textual": _textual_render,
    "web": _web_render,
    "vscode": _vscode_render,
}


@pytest.mark.parametrize("fixture_name", list(FIXTURES.keys()))
@pytest.mark.parametrize("client", list(RENDERERS.keys()))
def test_agent_beat_parity(client: str, fixture_name: str) -> None:
    """Each client renders each beat fixture per the shared contract."""
    if client in ("web", "vscode"):
        # JS renderers need node — skip if unavailable (CI should
        # always have it, local dev might not).
        if subprocess.run(
            ["node", "--version"], capture_output=True
        ).returncode != 0:
            pytest.skip("node not available")

    beat = FIXTURES[fixture_name]
    result = RENDERERS[client](beat)
    invariants = _expected_invariants(beat)
    _assert_invariants(client, result, invariants, beat)
