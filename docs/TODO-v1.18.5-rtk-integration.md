# TODO: v1.18.5 — Optional rtk integration

**Status:** Planning (planning landed 2026-05-10; implementation not started)
**Target:** v1.18.5 point release
**Branch:** `feature/v1.18.5`
**Supersedes / refines:** [ROADMAP.md §"v1.18.5 - Optional rtk wrapping in `execute_shell_command`"](../ROADMAP.md#v1185---optional-rtk-wrapping-in-execute_shell_command-planned).
The original entry assumed we'd encode per-platform allow/deny lists
derived from `~/.claude/RTK.md` "verified working" tables. Discovery
during planning (2026-05-10): rtk ships its own dry-run
(`rtk hook check <cmd>`) that returns the rewritten command on exit 0
or `No rewrite for: <cmd>` on exit 1. That collapses Phase 2 to a
thin shell-out and removes the list-maintenance burden entirely.

## Approach: hybrid — engine-side rewrite + prompt-side hint

Two independent layers, both gated on rtk being available on PATH:

**Layer A — engine-side rewrite (the safety net, always-on when enabled).**
Before `execute_shell_command` spawns its subprocess, ppxai calls
`rtk hook check <command>`. If exit 0, run the rewritten form
(`rtk git status` instead of `git status`). If exit 1, run raw.
The LLM is unaware: it asks for `git status`, gets compact rtk
output back, no behavior change visible at the wire.

**Layer B — prompt-side hint (lets the model anticipate compact formats).**
When rtk is detected, ppxai's system prompt gets a short `<RTK.md>`
block: "rtk is a CLI proxy that compresses common dev-tool outputs.
Output you see from shell tools may already be rtk-compressed. Idioms
like `rtk grep` and `rtk read` produce structurally different output
than raw `grep`/`cat` — don't pattern-match on raw formats." The
model emits commands as before; the engine wraps them via Layer A.
This is purely informational — it does NOT instruct the model to
emit `rtk <cmd>` directly (because the engine already does that).

The two layers are idempotent: if the model emits `rtk git status`
directly, `rtk hook check` returns the same string, no double-wrapping.

## Why not just one layer?

- **Layer A alone:** the LLM sees compressed output but doesn't know
  the format. Shell-tool reasoning that pattern-matches on raw output
  (e.g., "if the diff has more than 10 lines, summarize") may misbehave
  on rtk's compressed shape.
- **Layer B alone:** model compliance is per-model (gpt-5.5 reliable;
  smaller models won't always wrap correctly). On compliant models
  it's redundant with Layer A; on non-compliant models we get nothing.
- **Together:** Layer A guarantees compression regardless of model;
  Layer B helps the model interpret what it sees.

## Phases

| Phase | Scope | Effort | Tests |
|---|---|---|---|
| **Phase 1: detection + config** | `rtk_is_available()` cached at module load (single PATH lookup via `shutil.which`). New config field `tools.shell.use_rtk: Literal["auto","always","never"]` (default `"auto"`); a parallel `tools.shell.use_rtk_prompt_hint: bool` (default `True`). `auto` = wrap when rtk present, skip when not; `always` = wrap, error if rtk missing; `never` = no wrap, no hint. | ~30 LoC | ~10 |
| **Phase 2: engine-side rewrite (Layer A)** | At the existing `asyncio.create_subprocess_shell` call site (`engine/tools/shell.py:319` per current state), pre-process the command via `rtk hook check`. New helper `_rtk_rewrite(command: str) -> str | None` returns the rewritten command or `None`. Single touch point; preserves all existing cancellation, cwd, and grounding behavior including the `[cwd: /path]` header from v1.18.4. | ~25 LoC | ~12 |
| **Phase 3: prompt-side hint (Layer B)** | When `use_rtk_prompt_hint` is True AND rtk is available, `engine/tools/manager.py::get_tools_prompt` appends an `<rtk_context>` block to the system prompt. New file `docs/RTK-PROMPT-BLOCK.md` is the canonical text; the prompt builder reads it from `importlib.resources` so it ships in the PyInstaller bundle. | ~20 LoC + 1 doc | ~8 |
| **Phase 4: graceful fallback** | If the rewritten command exits with a code that suggests rtk-side breakage (rtk's documented "fallback" exit codes — confirm via `rtk --help` / source) OR stderr contains the canonical `rtk: error:` prefix, retry once with the raw command and log the fallback at INFO. Avoids breaking the user when a particular rtk wrapper has a bug. | ~20 LoC | ~6 |
| **Phase 5: docs + opt-out** | New `docs/RTK-INTEGRATION.md` covering install (`brew install rtk`, `winget install rtk-ai.rtk`, manual), the two config knobs, name-collision warning ("Rust Type Kit" vs "Rust Token Killer"), how to disable. Update `CLAUDE.md` "Architecture" or "Tools" section with a one-liner pointer. Update `ROADMAP.md` v1.18.5 row to reflect this plan. | docs only | — |

**Total:** ~95 LoC + ~36 tests + 2 new docs + 1 doc update. About 1.5 days.

## Concrete file touch points

| File | Change |
|---|---|
| `ppxai/config/tools.py` | Add `use_rtk` and `use_rtk_prompt_hint` fields to shell-tool config schema |
| `ppxai/engine/tools/shell.py` | Add `_rtk_is_available()` (cached), `_rtk_rewrite()`, fallback retry; wire pre-spawn |
| `ppxai/engine/tools/manager.py` | In `get_tools_prompt`, append `<rtk_context>` block when applicable |
| `docs/RTK-PROMPT-BLOCK.md` | New — the canonical prompt text |
| `docs/RTK-INTEGRATION.md` | New — user-facing install and config doc |
| `CLAUDE.md` | One-liner pointing at `docs/RTK-INTEGRATION.md` |
| `tests/test_rtk_integration.py` | New — detection cache, rewrite path, no-rewrite passthrough, fallback-on-error, prompt injection presence/absence |
| `ROADMAP.md` | Replace the v1.18.5 entry's 5-phase table with a pointer to this TODO + a 1-paragraph summary |
| `CHANGELOG.md` | New `## [1.18.5] - unreleased` section |

## Settled decisions (from planning conversation 2026-05-10)

- **Default behavior when rtk is on PATH:** `auto` = wrap silently.
  Users who installed rtk likely want the savings; engine-side rewrite
  is invisible. Explicit opt-out via `use_rtk: never`.
- **Approach:** hybrid (A+B), not either alone.
- **Branch name:** `feature/v1.18.5` (broader scope umbrella; rtk is
  the only theme today but the branch name doesn't lock that in).
- **List maintenance:** zero. Delegate to `rtk hook check`; rtk owns
  the platform knowledge. Significant departure from the original
  ROADMAP entry's "encode the lists" plan.

## Open questions (defer until implementation begins)

1. **Fallback exit-code shape.** `rtk hook check`'s contract is clean
   (0 = rewrite, 1 = no rewrite). But the executed `rtk <cmd>` itself
   has its own exit codes — same as the underlying tool, in most
   cases. We need to identify rtk-specific failure modes (binary not
   found mid-run, unknown subcommand fallback) before Phase 4.
2. **Prompt block size budget.** ~1-3 KB on every system prompt has
   measurable cost on smaller models. If benchmark regressions show
   up after Phase 3, gate the prompt block more aggressively
   (e.g., only when `tools.shell.enabled = true`).
3. **Telemetry.** Should ppxai emit `EventType.RTK_REWRITE` for `/usage`
   visibility? Decision: skip for v1.18.5. Users can run `rtk gain`
   directly and the engine-side rewrite is a hot path; adding events
   per shell call has its own cost.
4. **Caching the detection.** `shutil.which("rtk")` at module load
   is fast but happens once. If rtk is installed mid-session, the
   user has to restart ppxai to pick it up. Acceptable tradeoff.
5. **Interaction with `[cwd: /path]` header.** v1.18.4's cwd-grounding
   pass added `[cwd: /path]` headers to shell tool output. rtk's
   wrapped output may or may not preserve user-added prefixes. Verify
   in Phase 2 testing that the v1.18.4 cwd-grounding sentinel test
   suite (`tests/test_cwd_grounding.py`) still passes with rtk in
   the loop.

## Caveats pinned (carry over from ROADMAP entry)

- DO NOT bundle rtk in the install (~63 MB for 99% of users who won't
  notice). Optional dependency, period.
- DO NOT reimplement rtk's filters in Python — the existing tool
  has 26+ wrapper categories and is actively developed.
- DO NOT enable rtk wrapping for commands rtk itself declines to
  rewrite. `rtk hook check` is the source of truth; trust it.
- The output format the model sees changes when rtk wraps. Prompt
  block (Layer B) is the mitigation. Existing prompts/tests that
  pattern-match on raw `git status` output may need adjustment;
  flagged for sentinel-test authors.
- `rtk gain` analytics aggregate user + agent calls. Separating "what
  the user ran" from "what ppxai's agent ran" is a future rtk-side
  feature, not ppxai's problem.

## Acceptance criteria

1. `rtk_is_available()` returns `True` on hosts with rtk on PATH and
   `False` otherwise; cached after first call.
2. With `use_rtk: auto` and rtk installed, `execute_shell_command("git status")`
   spawns `rtk git status`, model receives compact output.
3. With `use_rtk: auto` and rtk NOT installed, behavior is byte-identical
   to v1.18.4 (no errors, no warnings, no prompt-block injection).
4. With `use_rtk: never`, behavior is byte-identical to v1.18.4 even
   if rtk is installed.
5. `rtk hook check`'s "no rewrite" verdict produces a raw subprocess
   spawn with no fallback retry (raw is the path).
6. The v1.18.4 cwd-grounding tests (13 cases in
   `tests/test_cwd_grounding.py`) all pass with rtk in the loop on
   a host where rtk is installed.
7. The CommandResult serialization tests (87 cases in
   `tests/test_command_result_serialization.py`) all pass.
8. New `tests/test_rtk_integration.py` covers detection, rewrite,
   passthrough, fallback, and prompt-block presence/absence.
9. `docs/RTK-INTEGRATION.md` documents the install, the config, the
   opt-out, and the troubleshooting surface.
10. `CHANGELOG.md` `[1.18.5]` section names the rtk integration as
    the only theme.

## Cross-references

- [ROADMAP.md §"v1.18.5 - Optional rtk wrapping in `execute_shell_command`"](../ROADMAP.md) — to be updated to reflect this plan
- [`~/.claude/RTK.md`](https://github.com/rtk-ai/rtk) — global RTK pointer (29 lines, references CLAUDE.md for command details)
- [reference_rtk_install.md](../../.claude/projects/-Users-rado-git-utils-ppxai/memory/reference_rtk_install.md) — host install state on rado's machine (memory file)
- rtk upstream: https://github.com/rtk-ai/rtk
