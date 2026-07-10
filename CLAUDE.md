# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ppxai is a terminal-based UI application for interacting with multiple AI providers (Perplexity, OpenAI, OpenRouter, local models). Interactive chat with model selection, conversation history, streaming, and AI-powered tools.

**Current version:** see [pyproject.toml](pyproject.toml) (single source of truth) or [the latest release](https://github.com/rcconsult/ppxai/releases/latest).

**Release state:** v1.18.8 and v1.18.7 are both **released** (2026-06-14 / 2026-06-13). v1.18.7 is the surface ppxai-sre's outlook-monitor agent consumes — the `POST /v1/oneshot` gateway shape (bearer auth) stays byte-identical. See [docs/release-notes-v1.18.7.md](docs/release-notes-v1.18.7.md) and [docs/archive/release-notes/release-notes-v1.18.6.md](docs/archive/release-notes/release-notes-v1.18.6.md).

**Active branch:** `feature/v1.19.0` (**not yet released**) — building the **agent platform** (ADR 0003 Stage 2): a durable, addressable `/v1/agent/*` run registry with a tool-capable sandboxed tier. Increments 1–9 are committed + **live-trial-verified** (run lifecycle, background exec, events/SSE monitor channel, AC-1 tool allowlist, AC-2 egress allowlist, budgets/cancel, `spawn_subagent` N=1, `/v1/tokens` + pluggable secret sources, per-run authz, AppState `background_agents` mirror), plus post-Inc-9 hardening §A–§K (provider-agnostic v1 tier, agent system-prompt framing, event-loop offload, egress SSRF guard, loopback UI auth exemption + `/v1/agent/run` carve-out, oneshot native web search, web `/agentrun` fire-and-forget). The interactive **`/task`** command family is now being built per [docs/plan-task-command-sequencing.md](docs/plan-task-command-sequencing.md) (T1–T9, each live-trialable): **T1** (web launch/observe — `/task run·ls·show·watch·cancel`), **T2** (filesystem seal — `tools.agent.sandbox` read-path jail in `ScopedToolManager`, default-off), **T3** (spec files — `--spec <name>` under `sandbox.specs_dir`, `engine/agent_spec.py`), and **T4** (skills — `--skill <name>` under `sandbox.skills_dir`, `engine/agent_skill.py`; SKILL.md grant + `references/` mounted into read-scope) are **committed**; **T5** (interactive consent — `waiting` park + `POST /runs/{id}/respond`, consent card, `state.json` first write = debt (r)) is **committed** (trial recipe in the plan doc §T5); **T6** (two-phase termination — `completed_pending_ack` hold + `POST /runs/{id}/ack` → `finalized`, Collect button, lazy retention reaper) is **committed** (trial recipe in the plan doc §T6); **T7** (interrupted resume — `POST /runs/{id}/resume` conditional on the `resume_refusal` decision matrix, restart-orphan sweep at registry construction, Resume button; retires debt (r) — the `state.json` Triplet file now has producers T5/T6/T7 and its consumer) is **committed** (trial recipe in the plan doc §T7). **T8 is split**: **T8a** (VSCode port — `taskController.ts` with verb/endpoint/status **parity sentinels** against the web client, typed `/v1/agent/*` httpClient slice, consent QuickPick per VSCode idiom) is **committed** (trial recipe in the plan doc §T8a); **T8b** (TUI port) is **⏸️ PARKED (2026-07-07)** pending a transport decision — the TUIs are in-process with no server channel, so either the registry+runner embed in-process (retires debt (t), recommended) or the TUIs grow an HTTP client; resume checklist in plan §T8. The `/task` family ships in **web + VSCode**; T9 (container tier-d) stays deferred. Design: [docs/agent-task-command-design.html](docs/agent-task-command-design.html) (`/task` surface + spec/skill files + sandbox config) and [docs/agent-task-lifecycle.html](docs/agent-task-lifecycle.html) (run-state machine, `/respond`·`/ack`·`/resume`). See [docs/plan-v1.19.0-sequencing.md](docs/plan-v1.19.0-sequencing.md) for the Stage-2 increment plan + build contract, [docs/agent-platform-call-graphs.md](docs/agent-platform-call-graphs.md) for per-increment route→event call graphs (§A–§K = post-Inc-9 fixes; T1–T2 client + seal, T5–T7 lifecycle, and T8a VSCode-port graphs appended), and [docs/decisions/0003-agent-platform-architecture.md](docs/decisions/0003-agent-platform-architecture.md) for the architecture. Open deferred work lives in the rolling [docs/debt-inventory.md](docs/debt-inventory.md) (per-version snapshots archived under [docs/archive/](docs/archive/)).

For per-version release notes, see [CHANGELOG.md](CHANGELOG.md) and `docs/RELEASE-NOTES-v*.md`. For architecture decisions, see `docs/decisions/`.

## Major Architectural Patterns

Each has a dedicated doc — read it before changing code in that area.

- **AppState** (v1.17.x) — observable state across all 4 clients (Python, JS, TS); SSE `state_sync` push; engine-owned invalidation. → [docs/patterns/appstate.md](docs/patterns/appstate.md)
- **Engine ops decomposition** (v1.17.x) — `EngineClient` is a ~1058 LoC facade over 6 ops modules in `engine/*_ops.py`. Same pattern in `tui/session_restore_ops.py`.
- **Server modularization** (v1.17.x) — `http.py` 411 lines + 17 route modules under `server/routes/`. DI via `Depends(get_session)`.
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
- **v1 API gateway** (v1.18.3) — `POST /v1/oneshot` is the first stable, semver-versioned external surface. Internal endpoints (`/chat`, `/command/*`, etc.) keep evolving. v1.19.0: opt-in provider-side web search via `tools.web_search.oneshot_grounding` (default off; Option A — no tool exposed, perimeter unchanged). See [docs/api-gateway.md](docs/api-gateway.md).

## Codebase Statistics

Tests: **3,907 passing, 3 skipped** on Unix with `uv sync --all-extras` (the v1.18.7 canonical pre-tag count; 3,910 collected). The count is environment-dependent: a base venv without the `[data]`/multipart extras skips the office + upload suites (~3,841 passing), and the release script's own run reports whatever its env yields (v1.18.7's README badge shows `3844`). On Windows the 7 `TestKillPreviewBackend` cases also skip (`os.getpgid`/`os.killpg` can't be `patch()`-ed).

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
2. Release notes: `docs/RELEASE-NOTES-vX.Y.Z.md`
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

## VSCode Extension

Install:
```bash
code --install-extension ppxai-X.Y.Z.vsix
./ppxai-server-{platform}
```

Settings: `ppxai.serverUrl` (default `http://127.0.0.1:54320`), `ppxai.defaultProvider`, `ppxai.defaultModel`, `ppxai.enableTools`.

Commands: `ppxai.openChat`, `ppxai.explainSelection`, `ppxai.generateTests`, `ppxai.switchProvider`, `ppxai.switchModel`.

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
