# Release Notes — v1.18.5

> **Scope:** A feature release that bundles two themes around a
> single architectural concern: making background activity in ppxai
> observable and uniform across all clients.
>
> **Theme 1 — Shell wrapper framework + rtk as the first concrete
> wrapper.** ppxai gains a generic, JSON-driven framework for
> transparent CLI wrappers (rtk, time, nice, perf profilers, etc.) on
> the shell tool. Two integration layers: engine-side rewrite at
> `engine/tools/builtin/shell.py:319` consults each wrapper before
> spawning the subprocess; system-prompt hint via
> `manager.py::get_tools_prompt` injects per-wrapper markdown blocks
> so the model interprets transformed output formats. Two generic
> decision strategies cover every realistic case: `probe` (wrapper
> ships a dry-run command like `rtk hook check <cmd>` and decides
> per-call) and `always` (wrapper has no dry-run; wrap every command
> with a fixed prefix — for `time`, `nice`, profilers). rtk ships as
> the canonical first wrapper via a `type: "probe"` entry in
> `DEFAULT_SHELL_WRAPPERS` — identical schema to anything a user
> adds. Real-world reference numbers: 47% savings on Windows manual
> mode (1355 cmds), 66% on Unix bash hook (4338 cmds). Adding a new
> wrapper that fits one of the two patterns requires **zero ppxai
> code changes** — write the JSON config entry, drop the prompt
> hint markdown file, restart ppxai.
>
> **Theme 2 — Preview backend observability + universal `/preview
> --serve` behavior.** v1.17.1 wired the `--serve` flag through
> `commands/display.py::handle_preview` and the web client's
> side-effects dispatcher, but the TUI side was never finished:
> Rich and Textual renderers ignored `result.metadata["mode"]` and
> silently ran static-file-only PreviewServer regardless of flags.
> Slash help advertised "autostart backend" but TUI sessions did
> nothing of the sort. v1.18.5 closes that gap. Spawn-and-drain
> logic lives in a new transport-agnostic helper
> (`ppxai/engine/preview_backend.py`) that both the HTTP route and
> the TUI renderers call into. The backend's stdout/stderr now
> drains continuously to a per-pid JSONL log under
> `~/.ppxai/logs/preview-backend-<pid>.log` (fixes a PIPE-backpressure
> hang from prior versions — same bug class as v1.18.3's async-shell
> fix, but in the preview path). A new AI-callable
> `read_preview_log` tool and `/preview logs [N]` slash (with
> `/preview-log` / `/preview-logs` aliases) expose the log to both
> the model and the user — no more "Gemini chases the wrong target
> because it can't see what the backend is logging."
>
> **Side themes.** rtk meta-commands (`rtk gain`, `rtk --help`,
> `rtk hook check`, `rtk discover`) are auto-approved via a
> dual-target consent classifier that strips transparent wrapper
> prefixes before pattern-matching — so safety verdicts are
> invariant under wrapping. Read-only git/gh verbs (`git status`,
> `git log`, `gh pr view`, etc.) join the default
> `allowed_commands` list — the consent prompt no longer fires on
> common diagnostic commands. A session-validator bug that orphaned
> assistant.tool_calls messages and caused HTTP 400 errors from
> OpenAI is fixed. ADR 0005 (filed same day) names the
> "Inspection Triplet" pattern that runs through several of these
> changes — `state.json` + `events.jsonl` + optional `admin/` —
> as a project-wide observability primitive that scales to
> ppxai-sre's planned autonomous SRE agents.
>
> **Tests:** 3273 pass, 2 skipped, zero regressions on prior
> sentinel suites (`test_cwd_grounding` 13/13,
> `test_command_result_serialization` 87/87). New: 49 cases in
> `test_wrapper_framework.py`, 82 in `test_consent_classification.py`,
> 21 in `test_preview_log_tool.py`, 10 in
> `test_preview_tui_renderer_gap.py`, 6 in
> `test_session_persistence.py::TestOrphanToolCallsCleanup`.

## Summary

v1.18.5 is structured around two architectural themes that emerged
in parallel from the same week of dogfooding. Every code-affecting
commit is also documented in `CHANGELOG.md` for the same date —
these notes provide the connective narrative.

1. **Shell wrapper framework + rtk as first wrapper** (`ccaa1522`).
   New package `ppxai/engine/tools/wrappers/` with `Wrapper` ABC +
   `ProbeWrapper` / `AlwaysWrapper` generics + factory dispatching
   on a `type` field. rtk ships as a default config entry, not a
   privileged Python class — adding wrappers is JSON-only when they
   fit one of the two patterns. Three integration sites: shell tool
   pre-spawn (`find_first_rewrite`), system prompt
   (`compose_prompt_blocks`), consent classifier
   (`strip_transparent_prefixes`). Thread-safe lazy init via
   `threading.Lock` on the singleton + each wrapper's
   PATH-resolution cache, so future sub-agent worker threads don't
   race. Back-compat shim for `use_rtk` / `use_rtk_prompt_hint`
   config fields. +49 tests.

2. **rtk meta-commands SAFE + dual-target consent classifier**
   (`a1747fbe`). `rtk gain` / `rtk --help` / `rtk hook check` /
   `rtk discover` auto-approved via a new allowed-list regex.
   Discovered by a side-effect of the wrapper framework: the
   transparent-prefix strip naively reduced `rtk gain` to `gain`
   (unknown → DANGEROUS). Fix: classify under **two targets** — the
   original command AND the wrapper-stripped form — taking
   worst-of-original NEVER/DANGEROUS plus best-of-either allowed
   match. `rtk init` and `rtk proxy <cmd>` stay DANGEROUS (writes
   config / bypasses filtering, respectively). Plus read-only git/gh
   verbs (28 git, 13 gh) added to `DEFAULT_ALLOWED_COMMANDS` because
   they were every-session-prompt friction. +82 tests.

3. **Preview backend PIPE-backpressure fix** (`4040b98c`). The
   `/preview --serve` subprocess spawn with `stdout=PIPE` read only
   the first 5 seconds for port detection, then left the PIPE
   undrained while the backend kept logging. After ~64 KB the
   backend blocked on writes → preview hung indefinitely. Same bug
   class as v1.18.3 commit `a746a7c6` fixed for the shell tool. Fix:
   spawn an asyncio drain task that runs for the backend's lifetime,
   writes JSONL records to `~/.ppxai/logs/preview-backend-<pid>.log`.
   Drain task is cancelled before process termination so it doesn't
   observe a closing PIPE as a spurious ConnectionResetError. +9
   tests.

4. **JSONL drain promotion + `read_preview_log` tool** (`a93fab4c`).
   Drain output went from plain text to one JSON object per line
   (`drain_start` / `stdout` / `drain_end` event types). New
   `read_preview_log` AI-callable tool reads the most recent
   backend log, supports `lines` / `since` / `filter` / `pid`
   params, returns human-readable summary + structured payload with
   a `next_since` cursor for incremental tailing. `/preview logs [N]`
   slash wraps the same function for user-driven inspection. +21
   tests.

5. **Session alternation cascading-orphan fix** (`b20cb1b0`).
   Surfaced 2026-05-10 from a real OpenAI session that ended on a
   zombie circuit-breaker (apply_patch fail×2). The user got
   repeated "An assistant message with 'tool_calls' must be
   followed by tool messages responding to each 'tool_call_id'"
   HTTP 400 errors on every `/continue` retry, with the orphan
   position moving earlier (21 → 19 → 9 → ...). Root cause:
   `validate_and_fix_alternation`'s step 3 "strip trailing tool"
   unconditionally popped a trailing tool message even when its
   parent assistant.tool_calls had all IDs covered — orphaning the
   parent (the new tail). Each `/continue` made it worse. Fix:
   keep a trailing tool when paired; only drop when truly orphaned
   (no parent or parent missing IDs). +1 regression test pinning
   the exact shape of the bug.

6. **TUI clients honor `--serve` and `--proxy`** (`71aaac92` —
   correctness gap close). Pre-v1.18.5, both Rich and Textual
   renderers ignored `result.metadata["mode"]` and unconditionally
   started static-file-only `PreviewServer` regardless of the
   `--serve` / `--proxy` flags. Slash help advertised "autostart
   backend" but TUI sessions did nothing of the sort — the v1.17.1
   "wire --serve through /preview" commit finished the web side
   but not the TUI side. v1.18.5 closes it: spawn-and-drain logic
   lives in a new transport-agnostic helper
   (`ppxai/engine/preview_backend.py`) called by HTTP route AND
   both TUI renderers. Backend lifecycle, drain task, log file
   location, error handling all share one source of truth.
   `/preview close` now stops both the static server AND the
   backend (no orphaned uvicorn after TUI exit). +10 tests pinning
   the post-fix contract for both renderers.

7. **`/preview-log` + `/preview-logs` aliases** (`7a854230`). User
   feedback from dogfooding: `/preview log` (singular, no hyphen)
   parses "log" as a filepath → "File not found: log".
   `/read_preview_log` (the underlying tool name) is not a slash.
   Add top-level `/preview-log` slash with `aliases=["preview-logs"]`
   that delegates to `handle_preview` with the `logs` subcommand.
   Three spellings now route to the same handler. +4 tests.

8. **ADR 0005 — Inspection Triplet pattern** (`040fa578`). Names a
   project-wide pattern that's already half-implemented across
   ppxai (sessions, preview log, ADR 0003 Stage 2's
   `runs/<run_id>/agent-<n>/` namespace) but was never formalized.
   Three layers per inspectable component: `state.json` (atomic
   snapshot) + `events.jsonl` (append-only log) + optional
   `admin/` (control surface). Events flow ONE WAY into the
   filesystem; multiple consumers read with their preferred
   transport. Event-bus-equipped clients (Textual / Web / VSCode
   SSE) become caching layers ON TOP of the filesystem; bus-free
   clients (Rich TUI direct read, ppxai-sre k8s pods, `kubectl
   exec`) read the same files. Status: Proposed; retroactive
   migration plan documented. Companion: caveat C5 ("agent-served
   services routing") filed in
   `ppxai-sre-repo/docs/PPXAI-INTEGRATION-V1.19.md` (commit
   `a604b0c` in that repo).

## Themes in detail

### Theme 1: shell wrapper framework

Why a framework, not just "rtk integration": the user explicitly
called for it once the original rtk-only plan was scoped. The
factory pattern + JSON config means a future `time`, `nice`, or
custom `myperf` wrapper is config-only (assuming probe/always shape
fits). Per-wrapper Python is only needed for genuinely bespoke
behavior (e.g., an IPC-based dry-run that doesn't follow the
stdout-line contract).

The transparent-prefix safety stripping in the consent classifier
is the load-bearing piece for `rtk git status` → `git status`
equivalence. The dual-target classification (original + stripped)
is what makes `rtk gain` map to its own meta-command pattern while
`rtk git status` strips to the inner git verb. Same code path, two
intents, no ambiguity.

Future wrappers (deferred to v1.18.x+ or v1.19.x depending on
demand): `time` (always-wrap, transparent), `nice` (always-wrap,
transparent), `perf record` (always-wrap with output dir,
transparent), `sandbox-exec` on macOS (probe-wrap, **NOT** marked
transparent — sandboxing should INTENTIONALLY change the consent
verdict).

### Theme 2: preview backend observability

The Inspection Triplet pattern (ADR 0005) was named in the same
session as the v1.18.5 preview work because the work IS that
pattern in action:

- The preview backend writes events to
  `~/.ppxai/logs/preview-backend-<pid>.log` (the `events.jsonl`
  layer).
- The `read_preview_log` tool reads them (PULL consumer for AI).
- `/preview logs [N]` reads them (PULL consumer for user).
- A future SSE channel (caveat C3 in
  `PPXAI-INTEGRATION-V1.19.md`) will be the PUSH consumer for
  Web/VSCode UIs.
- Each consumer is first-class; the file is the single source of
  truth.

The TUI gap-fix (theme 6 in the summary above) is the most visible
correctness improvement: pre-fix, `/preview --serve` in ppxaide was
a lie. Post-fix, it does what the help text says. The fix also
enables `read_preview_log` in TUI sessions for free — same engine
helper, same log file, same tool.

## v1 API gateway stability commitment

`POST /v1/oneshot` and the bearer-token auth middleware ship in
v1.18.5 byte-identical to v1.18.4. No fields added, no fields
removed, no status-code changes, no header changes. The v1
stability commitment per
[ADR 0004](decisions/0004-llm-gateway-features.md) is upheld.

ppxai-sre's outlook-monitor agent should consume v1.18.5 as a
drop-in replacement for v1.18.4. The new `/v1/agent/run` endpoint
(consumer-side asks C1-C5) is NOT in v1.18.5 — it remains v1.19.x
Stage 2 scope. v1.18.5 does NOT change the v1 wire shape.

## Upgrade notes

- **For ppxai users:** drop-in upgrade. Default behavior changes
  only when rtk is on PATH (then commands auto-wrap) or when a
  `/preview --serve` is invoked from a TUI (then the backend
  actually spawns). Both are opt-out via `tools.shell.use_rtk:
  never` or by not using `--serve` respectively.
- **For ppxai-sre / external `/v1/oneshot` consumers:** no changes
  required. v1 surface preserved byte-identical.
- **For users with custom `tools.shell.use_rtk` / `use_rtk_prompt_hint`
  in their ppxai-config.json (from earlier v1.18.5 branch testing):**
  back-compat shim translates them automatically. Migration to the
  new `tools.shell.wrappers: [...]` form is optional but cleaner.
  Plan to retire the shim in v1.20.x.

## Internal

- 11 commits between v1.18.4 release (`6e8d4848`) and the v1.18.5
  tag, on `feature/v1.18.5`. Branch was reset once during a major
  refactor (rtk-only → wrapper-framework) — clean linear history
  achieved via force-push to the feature branch.
- Local install validation done on macOS Intel via the
  `/build-install` skill end-to-end, plus interactive testing in
  both ppxaide (TUI) and the web app against the
  `/Users/rado/git/exps/ppxai_demo/` test target. Both `--serve`
  paths verified to spawn the backend and produce JSONL logs.
- `uv.lock` refreshed via `uv sync` at the version bump.
- ADR 0005 status is **Proposed** — retroactive naming of an
  existing pattern. Migration of existing artifacts (sessions
  layout, preview log file location, etc.) is incremental;
  v1.18.5 does NOT do the rename pass — that lands as artifacts
  are touched in v1.19.x+.
