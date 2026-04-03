# Release Notes — v1.17.3

**Release Date:** 2026-04-03
**Focus:** CodeMirror modular architecture, VSCode extension parity, web editor expansion

## Highlights

- **CodeMirror modular architecture** — replaced 5 monolithic bundles (6.3 MB) with a shared core (411 KB) + 30 per-language addons. Disk usage down 67%, languages up from 5 to 30. Each language loads on demand — only the first file of a given language triggers a network fetch.

- **VSCode extension parity** — wired the `state_sync` SSE event (was emitted but never consumed), expanded `EngineStatus` with 7 new fields, added Verbose Tools toggle and Hints badge to the webview, and fixed config reload to re-sync state.

- **30 editor languages** — native CodeMirror 6: Python, JavaScript, JSON, YAML, Markdown, HTML, CSS, SQL, Rust, Go, Java, C/C++, XML, PHP. Legacy StreamLanguage modes: Shell/Bash/Zsh, TOML, Dockerfile, Ruby, Perl, Lua, Swift, R, Kotlin, Scala, PowerShell, Diff, Protobuf, Nginx, CMake, Properties/INI.

## Added

- **Verbose Tools toggle** — menu indicator in web app and VSCode `⋮` menu with green-dot active state
- **SSE `state_sync` indicators** — `tools_verbose` and `debug_log` changes now update UI indicators in both web app and VSCode
- **Hints badge (VSCode)** — shows active AGENTS.md hint count in webview header
- **Filename-based language detection** — `Makefile` → shell, `Dockerfile` → dockerfile, `CMakeLists.txt` → cmake, `Rakefile`/`Gemfile` → ruby
- **Language selector dropdown** — expanded from 5 to 28 options in the web editor

## Fixed

- **VSCode `state_sync` dead event** — `stream.ts` emitted `state:sync` on EventBus but `chatPanel.ts` had no subscriber; now updates AppState + webview UI
- **VSCode `EngineStatus` incomplete** — added `tools_verbose`, `agent_mode`, `working_dir`, `debug_log`, `session_name`, `auto_route` to the interface and `getStatus()` return
- **VSCode config reload stale UI** — `updateStatus()` now called after `reloadConfig()` to re-sync provider/model/tools state
- **DataFileView edit mode** — updated to new modular `cm6.newEditor()` API with language parameter; JSON/YAML/TOML edit mode now gets syntax highlighting
- **MarkdownFileView edit mode** — same fix; markdown edit mode now loads language addon correctly
- **CodeMirror multi-language cache** — each language addon self-registers into `cm6.langs` registry; switching between files in different languages preserves correct syntax

## Changed

- **CodeMirror architecture** — monolithic per-language bundles → shared `core.min.js` + `lang-{name}.min.js` addons; core exports `cm6.modules` for `@codemirror/*` package sharing; lang addons use `require` shim to resolve shared packages at runtime
- **TODO consolidation** — 11 TODO files → 2 active (`TODO-appstate-codegen.md`, `TODO-routing.md`) + 4 archived; all open items retargeted to v1.18.x
- **ROADMAP updated** — added v1.17.0/v1.17.1/v1.17.2 completed sections, v1.18.x planned section
- **Codebase stats** — 250 files, ~95,700 lines (up from 123 files, ~51,400 lines at v1.16.0)

## Benchmark

- K8s benchmark jobs with `--agents-md` toggle and delta test results
- New models benchmarked: Qwen3.5-122B-A10B-NVFP4, Qwen3.5-27B-FP8, Qwen3-Coder-Next-NVFP4-GB10
- Tool failure hints improved in AGENTS.md

## Infrastructure

- Helm fixes: ingress field manager conflict, session-manager raw REST API for server-side apply, re-add ingress rule on existing session login
- Preview: relative URLs for K8s ingress compatibility
- Coder: AppState sync, heartbeat stream abort during streaming, pod probes, hints badge
