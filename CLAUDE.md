# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ppxai is a terminal-based UI application for interacting with multiple AI providers (Perplexity, OpenAI, OpenRouter, local models). Interactive chat with model selection, conversation history, streaming, and AI-powered tools.

**Current version:** see [pyproject.toml](pyproject.toml) (single source of truth) or [the latest release](https://github.com/rcconsult/ppxai/releases/latest).

**Release state:** **v1.19.0 is released** (2026-07-12) — agent platform Stage 2 as a PREVIEW surface. v1.18.8 (2026-06-14) and v1.18.7 (2026-06-13) precede it. The `POST /v1/oneshot` gateway shape (bearer auth) that ppxai-sre's outlook-monitor agent consumes stays **byte-identical** across all of these, including the unreleased work below. See [docs/release-notes-v1.19.0.md](docs/release-notes-v1.19.0.md).

**Active branch:** `bugfix/v1.19.1` (**not yet released**). Opened for tool-loop transcript integrity; it now also carries three implemented ADRs (0009, 0010, 0011). See [CHANGELOG.md](CHANGELOG.md) `[1.19.1]` for the full list and [docs/release-notes-v1.19.1-DRAFT.md](docs/release-notes-v1.19.1-DRAFT.md) for the migration detail.

⚠️ **The command surface was renamed with NO aliases** (ADR 0011). If you see `/agent`, `/agentrun`, `/agentruns`, `/tools agent`, or `/task run` in older docs or comments, they are **gone**:

| Removed | Now |
|---|---|
| `/agent <task>`, `/agent on\|off` | **`/auto`** — the in-session autonomous loop (`ppxai/commands/agent.py`, `name="auto"`) |
| `/tools agent` | **`/tools auto`** (`ppxai/commands/tools.py`) |
| `/agentrun`, `/agentruns` | **`/run`** — async one-off, `kind=oneshot` on the run registry |
| `/task run "<desc>"` | **`/task "<desc>"`** — direct launch |
| `task show` / `task ack` | **`task get`** / **`task collect`** (old names still accepted as aliases) |

"agent" now names only the `/v1/agent/*` platform. Verbs: `/task ls·get·watch·respond·collect·resume·cancel·help`, `/run ls·get·watch·collect·cancel·help` (no `respond`/`resume` — oneshot runs can't park). **All four client families have `/run` and `/task`** since T8b (2026-08-08): they register client-agnostically in `ppxai/commands/factory.py` (`"task"` in `COMMAND_MODULES`) plus `ppxai/web/shared/commands.js`. **One nuance:** `launch` and `resume` need a live asyncio loop (`_NEEDS_LOOP` in `ppxai/commands/task.py:52`), so the **Rich TUI rejects those two verbs** with an actionable error — every read verb (`ls`, `get`, `watch`, `collect`, …) works everywhere. Textual, web and VSCode have full parity.

**`execution.*` is the third top-level config axis** (ADR 0010/0011), read via `ppxai/config/execution.py`: `execution.run.{grounding,web_search}` (oneshot enrichment, both default off), `execution.task.*` (the tool-capable tier — `enabled`, `sandbox`, `consent.*`, `budgets.*`), `execution.profiles` (named reusable task grants), `execution.egress_ceiling` (deployment-wide egress cap), `execution.collect` (`auto|yes|no`, default `yes`). **Dual-read is the exception, not the rule:** only `execution.run.grounding` falls back to a legacy key (`tools.web_search.oneshot_grounding`, `ppxai/config/execution.py:56-79`). ADR 0010's `execution.task.*` move was a **clean break** — the old `tools.agent.*` tier keys are silently ignored, which is why `/doctor` grew a config-shape file scan. `execution.oneshot.*` was renamed to `execution.run.*` before implementation — **no code reads `execution.oneshot`**.

**Agent platform (ADR 0003 Stage 2)** shipped in v1.19.0: `/v1/agent/*` run registry, tool-capable sandboxed tier, Increments 1–9 + hardening §A–§K, and the `/task` family T1–T7 (web) + T8a (VSCode). **T8b (TUI port) shipped on this branch** (unparked 2026-08-08): the transport question resolved in favour of embedding the registry+runner **in-process** — `ppxai/engine/task_runner.py` builds the runner and the TUIs never grow an HTTP client. See [docs/plan-task-command-sequencing.md](docs/plan-task-command-sequencing.md) §T8b. T9 (container tier-d) stays deferred.

Design docs: [docs/agent-task-command-design.html](docs/agent-task-command-design.html) and [docs/agent-task-lifecycle.html](docs/agent-task-lifecycle.html) (run-state machine). Plans: [docs/plan-run-taxonomy-sequencing.md](docs/plan-run-taxonomy-sequencing.md) (ADR 0011 phases F/U — all complete), [docs/plan-task-command-sequencing.md](docs/plan-task-command-sequencing.md) (T1–T9), [docs/plan-v1.19.0-sequencing.md](docs/plan-v1.19.0-sequencing.md). Call graphs: [docs/agent-platform-call-graphs.md](docs/agent-platform-call-graphs.md). Open deferred work lives in the rolling [docs/debt-inventory.md](docs/debt-inventory.md); closed items are archived to [docs/archive/DEBT-INVENTORY-CLOSED.md](docs/archive/DEBT-INVENTORY-CLOSED.md).

For per-version release notes, see [CHANGELOG.md](CHANGELOG.md) and `docs/release-notes-v*.md`. For architecture decisions, see `docs/decisions/`.

## Major Architectural Patterns

Each has a dedicated doc — read it before changing code in that area.

- **AppState** (v1.17.x) — observable state across all 4 clients (Python, JS, TS); SSE `state_sync` push; engine-owned invalidation. → [docs/patterns/appstate.md](docs/patterns/appstate.md)
- **Engine ops decomposition** (v1.17.x) — `EngineClient` is a ~1,264 LoC facade over 6 ops modules in `engine/*_ops.py` (`bootstrap`, `checkpoint`, `consent`, `multimodal`, `provider`, `session`; ~1,775 LoC between them). Same pattern in `tui/session_restore_ops.py`.
- **Server modularization** (v1.17.x) — `http.py` 606 lines + 21 route modules under `server/routes/`. DI via `Depends(get_session)`.
- **Command Dispatch via Envelope** (v1.18.1) — every slash command flows through `POST /command/<name>` returning `{ok, result, side_effects, events, version}`. → [docs/patterns/command-envelope.md](docs/patterns/command-envelope.md)
- **State-Sync Determinism** (v1.18.1) — `/state` snapshot + visibility/focus re-anchor + REST event piggyback + `cwd_anchor` 409. → [docs/patterns/state-sync-determinism.md](docs/patterns/state-sync-determinism.md)
- **Agent Heartbeat Primitives** (v1.18.0) — `EventType.AGENT_BEAT` / `AGENT_RUN_*` / `AGENT_ZOMBIE`; zombie circuit-breaker via `tools.agent.zombie_threshold`. → [docs/architecture.md] §"Agent Heartbeat Primitives".
- **Transactional State Management** (v1.15.0) — checkpoint/commit/rollback for atomic multi-step operations. → [docs/patterns/transactional-state.md](docs/patterns/transactional-state.md)
- **Protocol-based dependency inversion** (v1.17.0) — define `Protocol` in leaf modules to break circular imports. No `TYPE_CHECKING`. → [docs/patterns/protocol-dependency-inversion.md](docs/patterns/protocol-dependency-inversion.md)
- **EngineClientProtocol** (v1.18.2) — commands type against the protocol, not the concrete `EngineClient`. See [ppxai/engine/types.py].
- **CommandContext three-pattern split** (v1.18.2) — Rich uses Pattern A proxy, Textual passes `self`, Server uses Pattern B explicit. **Don't unify on speculation.** See [docs/decisions/0002-command-context-three-pattern-split.md].

**Capability surface:**
- AppState schema DTO (`engine/app_state_schema.json`) — single source of truth for 4 clients; mirrors in `web/shared/app-state.js` + `vscode-extension/src/appState.ts`; cross-language sentinel tests.
- CompletionProvider engine layer (`engine/completion.py`) — single source of truth for autocomplete; clients are thin glue.
- File upload + multimodal — `/attach` command, `SessionFileStore`, file preprocessing, image validation, VL sidecar, PDF/Excel/PPTX/DOCX tools.
- `/doctor` config advisor — deprecation table, dead/deprecated/new/recommended model scanning.
- VSCode extension bundled via esbuild (v1.18.2) — 128 KB VSIX (was 1.1 MB), 15 files (was 804); CI has 500 KB size-budget gate.
- **v1 API gateway** (v1.18.3) — `POST /v1/oneshot` is the first stable, semver-versioned external surface; its request/response shape is **byte-identical since v1.18.4**. Internal endpoints (`/chat`, `/command/*`, etc.) and the whole in-development `/v1/agent/*` surface keep evolving. Enrichment is opt-in via `execution.run.grounding` (provider-native search) and `execution.run.web_search` (model-triggered `web_search` tool loop), both default off; `tools.web_search.oneshot_grounding` is the superseded key, still dual-read. On v1.19.1 every oneshot — plain or enriched — executes as a `kind=oneshot` registry run; the direct provider path is deleted, but the wire contract is unchanged. See [docs/api-gateway.md](docs/api-gateway.md).

## Test-count expectations

Tests: **5,097 collected** on macOS/Unix with `uv sync --all-extras` (verified 2026-08-15 on `bugfix/v1.19.1` @ `421e381c`). The count is environment-dependent: a base venv without the `[data]`/multipart extras skips the office + upload suites, and the release script's own run reports whatever its env yields — so the README badge routinely trails this number. On Windows the 7 `TestKillPreviewBackend` cases also skip (`os.getpgid`/`os.killpg` can't be `patch()`-ed).

The Playwright specs under `tests/e2e/` are **not** in that count. Most drive a static `file://` harness; `live-app.spec.ts` drives the real web UI against a real `ppxai-server` and is opt-in via `npm run test:live`.

## Installation Locations (CRITICAL)

**IMPORTANT: Follow these exact paths. NEVER use `AppData\Local\ppxai` on Windows.**

| Item | Linux | macOS | Windows |
|------|-------|-------|---------|
| **Binaries** | `~/.local/bin/` | `~/.local/bin/` | `~/.ppxai/bin/` |
| **App bundle** | – | `/Applications/ppxai.app` | – |
| **Config** | `~/.ppxai/ppxai-config.json` | `~/.ppxai/ppxai-config.json` | `~/.ppxai/ppxai-config.json` |
| **API keys** | `~/.ppxai/.env` | `~/.ppxai/.env` | `~/.ppxai/.env` |
| **Data** | `~/.ppxai/` | `~/.ppxai/` | `~/.ppxai/` |
| **Web UI** | `~/.ppxai/web/` | `~/.ppxai/web/` | `~/.ppxai/web/` |

**When deploying:** Windows uses `~/.ppxai/bin/` for binaries; Linux/macOS uses `~/.local/bin/`. The `AppData\Local\ppxai` path exists only as a **search path** for finding binaries, never as an install target.

`~/.ppxai/` subdirs: `bin/` (Windows only), `web/` (with `lib/` and `shared/`), `sessions/`, `exports/`, `checkpoints/`, `logs/`, `usage/`.

## Architecture

Layout is discoverable with `ls`: `ppxai/{engine,server,tui,commands,config}` + `vscode-extension/` (see the Key Design Decisions layering below).

**Configuration files:**

| File | Purpose | Git |
|------|---------|-----|
| `.env` | API keys (secrets) | ❌ Never commit |
| `ppxai-config.json` | Provider definitions | ✅ Can commit |

## Development Setup

For uv resolution, Quick Start, Windows Store Python recovery, corporate proxy/TLS, and PyInstaller details, see [docs/dev-setup.md](docs/dev-setup.md).

Quick reminder:
```bash
command -v uv >/dev/null 2>&1 || python scripts/bootstrap.py --all
export UV=$(command -v uv 2>/dev/null || echo ".uv/uv")
$UV sync --all-extras
$UV run ppxai           # Rich TUI
$UV run pytest tests/ -v
```

**File encoding:** UTF-8 **without** BOM. Avoid PowerShell `Out-File` (it adds BOM by default).

## Common Commands

```bash
export UV=$(command -v uv 2>/dev/null || echo ".uv/uv")

# Run
$UV run ppxai                    # Rich TUI
$UV run ppxaide                  # Textual TUI
$UV run ppxai-server             # HTTP server for VSCode
$UV run ppxai-desktop            # Desktop web app

# Test
$UV run pytest tests/ -v

# Build binaries (macOS/Linux)
$UV run pyinstaller ppxai.spec --noconfirm
$UV run pyinstaller ppxaide.spec --noconfirm
$UV run pyinstaller ppxai-server.spec --noconfirm
$UV run pyinstaller ppxai-desktop.spec --noconfirm

# Build VSCode extension
cd vscode-extension && npm run compile && npx vsce package --allow-missing-repository

# Create macOS DMG
bash scripts/create-macos-app.sh
```

If pytest collection fails with `No module named 'blinker'`, exclude TUI tests via the helper in [docs/dev-setup.md](docs/dev-setup.md).

## Release Process

**CRITICAL: Always use the `/release` skill.**

```bash
/release v1.x.x
```

**NEVER manually:** update version files, create git tags, run `gh release create`, or upload assets.

### Files updated by release script

Slimmed in 2026-05. Most files now read from `ppxai.__version__` at runtime, link to `releases/latest`, or use a `<version>` placeholder. `tests/test_version_consistency.py` enforces parity.

| File | Pattern |
|------|---------|
| `pyproject.toml` | `version = "X.Y.Z"` (canonical Python SoT) |
| `ppxai/version.py` | `__version__ = "X.Y.Z"` (runtime SoT) |
| `vscode-extension/package.json` | `"version": "X.Y.Z"` (npm SoT) |
| `vscode-extension/package-lock.json` | typed JSON edit |
| `README.md` | shields.io badge + tests-NNNN |
| `docs/index.md` | shields.io badge |

### Pre-release checklist

1. CHANGELOG entry: `## [X.Y.Z] - YYYY-MM-DD`
2. Release notes: `docs/release-notes-vX.Y.Z.md`
3. Merge feature branch to master
4. `python scripts/validate-release.py vX.Y.Z`

### Release assets (built by CI)

`ppxai-{version}.vsix`, `ppxai-{platform}` (TUI), `ppxai-server-{platform}`, `ppxai-desktop-{platform}`, `ppxai-{version}-macos-arm64.dmg`. Platforms: linux-amd64, macos-arm64, macos-intel, windows.exe.

## GitHub CLI Authentication

```bash
GH_TOKEN=$(cat .github/gh-token.env) gh release list
```

`.github/gh-token.env` is gitignored.

## Key Design Decisions

1. **Layered architecture** — Engine (no UI) → Server (HTTP/SSE) → Clients (TUI, VSCode, Web)
2. **Provider abstraction** — All providers implement `BaseProvider`
3. **Event-based communication** — Engine emits events; clients render them
4. **OpenAI SDK for all providers** — OpenAI-compatible API format
5. **Hybrid config** — Secrets (`.env`) separate from settings (`ppxai-config.json`)
6. **Built-in providers** — Perplexity and Gemini always available without config
7. **Transactional state management** — checkpoint/commit/rollback for atomic multi-step operations

## ppxaide / Terminal Images

For Textual TUI internals (theme synchronization, key bindings, kitty keyboard protocol, syntax highlighting requirements) and terminal image rendering details, see [docs/ppxaide-impl.md](docs/ppxaide-impl.md).

DO NOT BREAK: key registry in `ppxai/tui/keys.py`, theme sync chain (`watch_theme()` → `get_syntax_theme_for_app_theme()` → `CodeEditor.syntax_theme`), tree-sitter dependencies in `pyproject.toml`, language detection via `EXTENSION_TO_LANGUAGE`.

## vLLM Tool Calling

For Hermes vs Harmony parsers, GPT-OSS quirks, Qwen3/2.5 setup, and the "I'll use X tool" JSON-text issue, see [docs/vllm-notes.md](docs/vllm-notes.md), [docs/vllm-tool-calling-guide.md](docs/vllm-tool-calling-guide.md), [docs/prompt-based-tool-calling.md](docs/prompt-based-tool-calling.md).

## Known Issues

- Perplexity/Gemini may use shell commands for web data instead of native search when tools enabled (accepted behavior).

## Shell wrapper framework (v1.18.5)

Generic JSON-driven framework for transparent CLI wrappers (rtk, time, nice, perf profilers, etc.) on the shell tool. Two integration layers — engine-side rewrite + system-prompt hint — both gated on the wrapper's binary being on PATH. Adding a wrapper is a config-only operation when it fits the `probe` or `always` decision strategy. Code lives at `ppxai/engine/tools/wrappers/`; rtk ships as the canonical first wrapper in `DEFAULT_SHELL_WRAPPERS`. See [docs/shell-wrappers.md](docs/shell-wrappers.md) for the user-facing reference.

## Debug Logging

Default: **off** for fresh installs. Toggle with `/debug-log on|off` (Rich + Textual) or `POST /config/debug-log` (web/VSCode). Persisted to `ppxai-config.json → tui.debug_log` and restored inside `config.initialize()`, so logging is active **before** any client code runs — critical for diagnosing early-startup regressions like silent session-recovery failures.

See [docs/debug-logging.md](docs/debug-logging.md). (Per-host session-recovery-ordering notes live in agent memory, not the repo.)

## Verify, Don't Assume

**Before dismissing an anomaly (warning, error, unexpected output) as "pre-existing", "unrelated", "normal", or "expected to fail", run the actual check that proves it.** Confident-sounding assumptions on this project have repeatedly cost corrective iterations.

Concrete examples:
- v1.18.1 needed 4 retag cycles partly because Linux-vs-Windows test divergence was assumed-equivalent (HOME-includes-tmp_path fallback was Windows-only).
- v1.18.1 streaming felt sluggish — a 100ms tick from 6 weeks earlier *assumed* fine because unchanged.
- PyInstaller binaries shipped without `dotenv` because the build venv was *assumed* to have every `hiddenimport` installed.
- `monkeypatch HOME` was *assumed* to redirect a path that was actually module-load-resolved.

30-second verifications to run before dismissing:
- "Does this fail on master too?" → `git stash`, rerun, restore.
- "Is this output from my edit or pre-existing?" → check timestamps, `git blame`, run against a baseline.
- "Does the file parse?" → run the parser on JUST the section edited.
- "Is the binary actually working?" → `<binary> --version` after every PyInstaller rebuild.

If verification is genuinely impractical, say "I'm assuming X because Y, but haven't confirmed" — make the uncertainty explicit. Trust-but-verify especially applies to: PyInstaller builds, cross-platform test failures, encoding/CRLF behavior, Windows-specific path code, YAML parsing, and anything to do with releases.

**Verify both directions, not just "is there a problem".** When a signal flags X as broken AND when someone pushes back saying the signal is wrong, both readings need the same Tier-2-style verification (production-code-only inbound counts, channel-ratio inspection, source-code grep). Heuristic for graphify-flagged "god classes":

```bash
# Production-code-only inbound count
grep -rc "ClassName" ppxai/ --include="*.py" | grep -v ":0$"

# Channel ratio in the suspect file
grep -cE 'event_bus\.(emit|subscribe)|state\.(on|set|get)' file.py
```

If textual references are <30 across production code AND bus/state/protocol channels carry communication, the class is NOT a god class regardless of whole-repo graphify edge count.

## Shared lessons

`docs/lessons/` holds cross-host, grep-verifiable engineering hazards
and architectural facts that any agent (AI or human) should know
before re-deriving them. Per-host AI memory
(`~/.claude/projects/<repo>/memory/`) does NOT sync; lessons that
belong to the codebase belong in the repo.

**Read [docs/lessons/README.md](docs/lessons/README.md) first** for
the format + promotion criteria. Examples: "MCP is not integrated
despite filename evidence", "ADR 0006 wire validator catches in-block
key regressions".

**When you discover a cross-host engineering hazard during a session**
— meaning the lesson is true on any machine running this repo AND a
reader can `grep`/open-a-file to confirm it — propose adding a
`docs/lessons/<topic>.md` file in your turn summary. Don't auto-commit;
the user decides whether the lesson is worth the repo's permanent
attention. Per-host preferences and ephemeral session state stay in
per-host memory only.

## Commit Guidelines

- Do NOT include Claude credits or co-authored-by lines.
- **Never commit sensitive information:** tokens, API keys, passwords, hostnames, usernames, file paths with usernames, environment-specific details.
- In PRs and docs, use generic placeholders (e.g. `your-token`, `/path/to/project`).

## graphify

Knowledge graph at `graphify-out/`.

Rules:
- Before answering architecture/codebase questions, read `graphify-out/GRAPH_REPORT.md` for god nodes and community structure.
- If `graphify-out/wiki/index.md` exists, navigate it instead of reading raw files.
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — they traverse EXTRACTED + INFERRED edges.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

**Whole-repo god-node ranking is biased by test coverage.** `.graphifyignore` excludes `tests/`, `benchmarks/`, `scripts/`, `examples/`, `docs/archive/` (added 2026-04-29). Without exclusions, `tests/test_tui.py` (4,788 LoC) drove 71-79% of the "god class" edges on `PPXAIDEApp`/`MessageBox`/`ChatView`. With exclusions: 11.6k → 4.5k nodes (-61%); top hubs reflect actual architectural hubs (`EventType`, `CommandResult`, `SessionManager`, `BaseTool`, `BaseProvider`, `ToolManagerProtocol`).

**Subtree-build pattern for subsystem analysis.** When the whole-repo graph is too coarse, build a per-subtree graph with `c:\tmp\subtree_build.py <input_path> <output_dir>`. Used in v1.18.2 (`engine`, `server`, `commands`, `vscode`, `tui`) to surface subsystem-internal structure the whole-repo graph hides.

**Don't read whole-repo "god class" rank as architectural smell without verifying.** Apply the production-code-only inbound count heuristic above before concluding. The same trap caught `EngineClient`, `ChatViewProvider`, and `PPXAIDEApp` on `bugfix/v1.18.2`.
