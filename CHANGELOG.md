# Changelog

All notable changes to ppxai will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.11.0] - 2025-12-21

### Added - File Editing Tools with User Consent 🎯

This release introduces **autonomous file editing** capabilities with a comprehensive consent system, transforming ppxai into the first phase of an agentic developer assistant.

#### Core Features
- **4 File Editing Tools** - AI can now modify files with user permission:
  - `apply_patch` - Apply unified diff patches (git-style)
  - `replace_block` - Search and replace exact text blocks
  - `insert_text` - Insert text at specific line numbers
  - `delete_lines` - Delete line ranges from files

- **Per-File Session Consent System** - Safety-first approach:
  - **y (yes)** - Allow editing this file (this session)
  - **n (no)** - Deny this edit
  - **always** - Auto-approve all files (this session)
  - **never** - Block all edits (this session)
  - Consent persists only for current session
  - Separate consent tracking per file path

- **TUI Consent Prompts** - Interactive validation using prompt_toolkit:
  - Clear file path display
  - Validated input (only y/n/always/never accepted)
  - Persistent consent state tracking

- **VSCode Consent Dialogs** - Event-driven SSE integration:
  - Modal dialogs with 4 consent options
  - Server-Sent Events for real-time communication
  - Non-blocking async consent flow

- **Atomic File Operations** - Robust and safe:
  - Write-to-temp + rename pattern
  - Automatic rollback on failure
  - File existence validation
  - Permission checks before edit

- **In-App Help System** - `/tools help editing` command:
  - Comprehensive markdown guide
  - Practical examples with chat flows
  - Consent system explanation
  - Troubleshooting tips
  - Available in both TUI and VSCode extension

#### Documentation
- **NEW:** [docs/FILE_EDITING_GUIDE.md](docs/FILE_EDITING_GUIDE.md) - 400+ lines comprehensive user guide
- **NEW:** [vscode-extension/TESTING.md](vscode-extension/TESTING.md) - Testing documentation for VSCode extension
- **Updated:** README.md with File Editing Tools section
- **Updated:** CLAUDE.md with v1.11.0 feature summary and version alignment

#### Testing
- **NEW:** 36 comprehensive tests for file editing features:
  - 25 tests for file editing tools ([tests/test_file_editing_tools.py](tests/test_file_editing_tools.py))
  - 11 tests for help commands and UI ([tests/test_ui.py](tests/test_ui.py), [tests/test_commands.py](tests/test_commands.py))
- **Total:** 273/278 tests passing (98.2%)
- 5 pre-existing custom endpoint integration test failures (unrelated)

#### Technical Implementation
- `ppxai/engine/tools/builtin/editor.py` - NEW, implements all 4 file editing tools
- `ppxai/engine/client.py` - Added `request_file_edit_consent()` async method
- `ppxai/engine/session.py` - Added consent state (`allowed_files`, `edit_consent_mode`)
- `ppxai/commands.py` - TUI consent handler with prompt_toolkit validation + `/tools help editing`
- `ppxai/ui.py` - Added `display_file_editing_help()` function and updated welcome message
- `vscode-extension/src/chatPanel.ts` - Added `getFileEditingHelp()` + help command handler

### Changed
- Version bumped to 1.11.0 in `pyproject.toml` and `vscode-extension/package.json`
- Updated ROADMAP.md to reflect Phase 1 completion
- Updated all version references throughout documentation

### Fixed
- VSCode extension `/tools help editing` command now displays formatted help content

---

## [1.10.8] - 2025-12-21

### Added
- Unified `/save` and `/export` commands across TUI and VSCode extension
- New `/export [filename]` command exports last answer to markdown (`~/.ppxai/exports/`)
- Clear separation between session persistence (JSON) and answer export (markdown)

### Changed
- `/save` now saves session to JSON (`~/.ppxai/sessions/`) for persistence
- VSCode extension "Save Answer" button now saves to exports folder with auto-generated filenames

### Improved
- VSCode extension interrupt UX - orange pulsing "⏹ Streaming..." badge in header
- Streaming interrupt no longer shows red error message on user-initiated stop

---

## [1.10.7] - 2025-12-20

### Fixed
- Perplexity API compatibility - removed deprecated `sonar-reasoning` model
- Model documentation updated to reflect current Perplexity API

### Changed
- Supported Perplexity models: sonar, sonar-pro, sonar-reasoning-pro, sonar-deep-research

---

## [1.10.6] - 2025-12-20

### Added
- Gemini 3 Flash Preview - Speed-optimized with frontier intelligence and 1M context
- Gemini 3 Pro Preview - Most powerful agentic model with code execution and search grounding
- Enhanced model descriptions with detailed capabilities
- Preview pricing estimates for Gemini 3 models

---

## [1.10.5] - 2025-12-20

### Added
- Status bar showing provider, model, and tools status
- VSCode extension interrupt support via Esc key and Command Palette
- TUI Ctrl-C double-press pattern (2s timeout) - first press warns, second exits
- 7 new interrupt handling tests

### Fixed
- Ctrl-C during streaming no longer causes message alternation errors
- Conversation history cleanup on interrupt maintains LLM message alternation
- Gemini tools None content handling
- FastAPI deprecation warnings (migrated to lifespan pattern)

### Testing
- 235/241 tests passing

---

## [1.10.4] - 2025-12-19

### Fixed
- Markdown tables now render properly in TUI (no more raw `|:---|:---|` syntax)
- Tables support left/center/right alignment (`:---`, `:---:`, `---:`)
- `/show` command renders markdown files with formatted tables
- All AI responses render tables correctly

### Added
- 27 new regression tests for table rendering

---

## [1.10.3] - 2025-12-18

### Added
- Standalone `ppxai-server` executables for all platforms (no Python required)
- Automated GitHub Actions CI/CD for multi-platform builds:
  - macOS ARM64 & Intel
  - Linux AMD64
  - Windows

---

## Earlier Versions

See [ROADMAP.md](ROADMAP.md) for historical release information.

---

## Versioning

ppxai follows [Semantic Versioning](https://semver.org/):
- **MAJOR** version for incompatible API changes
- **MINOR** version for new functionality in a backwards compatible manner
- **PATCH** version for backwards compatible bug fixes

## Release Process

1. Update version in `pyproject.toml` and `vscode-extension/package.json`
2. Update CHANGELOG.md with release notes
3. Update ROADMAP.md to move release from "Next" to "Current"
4. Create git tag: `git tag -a v1.x.x -m "Release v1.x.x"`
5. Push tag: `git push origin v1.x.x`
6. GitHub Actions automatically builds and creates release

[1.11.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.0
[1.10.8]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.8
[1.10.7]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.7
[1.10.6]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.6
[1.10.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.5
[1.10.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.4
[1.10.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.3
