# AGENT.md - AI Assistant Context for ppxai

This file provides essential context for AI assistants working on the ppxai project.

## Project Overview

**ppxai** is a terminal-based UI and VSCode extension for interacting with multiple AI providers (Perplexity, OpenAI, Gemini, OpenRouter, Ollama). It provides an interactive chat interface with streaming responses, tool execution, and multi-provider support.

**Current Version:** v1.11.2.1 (Patch Release - 2025-12-23)
**Repository:** https://github.com/rcconsult/ppxai
**License:** MIT

## Current State (v1.11.2.1)

### Just Released
- **Critical Fix:** Autorouter provider mismatch bug (404 errors with non-Perplexity providers)
- **New Documentation:** Comprehensive autorouter configuration guide
- **All Tests Passing:** 308/308 tests passing
- **Assets:** macOS ARM/Intel, Linux, Windows binaries available

### Core Features
- Multi-provider AI chat (Perplexity, OpenAI, Gemini, OpenRouter, Ollama)
- Shell command consent system (v1.11.2) - user approval for dangerous commands
- File editing tools with user consent (v1.11.0) - apply_patch, replace_block, insert_text, delete_lines
- Autorouter - automatic model switching for coding tasks
- TUI with Rich rendering (tables, markdown, code blocks, inline code)
- VSCode extension with HTTP + SSE backend
- Standalone executables (no Python required for VSCode users)

## Architecture

### Layered Architecture
```
Engine Layer (ppxai/engine/)     - Core business logic, no UI dependencies
├── client.py                     - EngineClient facade
├── session.py                    - Session management
├── providers/                    - Provider implementations
│   ├── base.py                   - BaseProvider abstract class
│   ├── perplexity.py            - Perplexity native search
│   └── openai_compat.py         - OpenAI-compatible (OpenAI, Gemini, OpenRouter, Ollama)
└── tools/                        - Tool system
    ├── manager.py                - ToolManager with provider-aware filtering
    └── builtin/                  - Built-in tools (filesystem, shell, web, etc.)

Server Layer (ppxai/server/)      - IDE integration
└── jsonrpc.py                    - JSON-RPC over stdio using EngineClient

TUI Layer (ppxai/)                - Terminal UI
├── main.py                       - CLI entry point
├── ui.py                         - Rich console components
└── commands.py                   - Slash command handlers

Legacy Support                    - Backward compatibility during transition
├── client.py                     - Legacy AIClient (still used by TUI)
├── tool_manager.py              - Legacy tool manager
└── perplexity_tools_prompt_based.py
```

### Key Design Patterns

1. **Provider Abstraction** - All providers implement `BaseProvider` interface
2. **Tool Independence** - Tools register via `register_tools(manager)` pattern
3. **Event-Based Communication** - Engine emits events (STREAM_CHUNK, TOOL_CALL, CONSENT_REQUEST, etc.)
4. **Provider-Aware Routing** - Autorouter uses provider-specific coding models
5. **Consent System** - File/shell operations require user approval (session-scoped)

## Critical Patterns (Must Follow)

### 1. Autorouter Provider Parameter
**ALWAYS** pass the provider parameter to `send_coding_task()`:

```python
# ✅ CORRECT - Pass provider explicitly
send_coding_task(self.client, "convert", task_message, self.current_model, self.provider)

# ❌ WRONG - Missing provider (bug that caused v1.11.2.1 patch release)
send_coding_task(self.client, "convert", task_message, self.current_model)
```

**Why:** Without provider parameter, `get_coding_model()` falls back to stale global `MODEL_PROVIDER` variable, causing 404 errors when users switch providers mid-session.

**Affected Commands:** All coding commands in [ppxai/commands.py](ppxai/commands.py):
- handle_generate() (line 424)
- handle_test() (line 437)
- handle_docs() (line 450)
- handle_implement() (line 461)
- handle_debug() (line 471)
- handle_explain() (line 484)
- handle_convert() (line 512)

### 2. Tool Registration Pattern
Use the current ToolManager pattern, not legacy decorators:

```python
# ✅ CORRECT - Current pattern (v1.11.0+)
from ppxai.engine.tools.manager import ToolManager

def register_tools(manager: ToolManager):
    """Register tools with the manager."""
    manager.register(
        name="my_tool",
        description="Tool description",
        parameters={
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "Parameter"}
            },
            "required": ["param"]
        },
        function=my_tool_impl
    )

def my_tool_impl(param: str) -> str:
    """Tool implementation."""
    return f"Result: {param}"

# ❌ WRONG - Legacy decorator pattern (deprecated)
@tool(name="my_tool", description="...")
def my_tool(param: str) -> str:
    pass
```

### 3. Consent Handling
File and shell tools require user consent. Use the consent callback pattern:

```python
# Engine handles consent automatically
async for event in engine.chat("Delete old logs"):
    if event.type == EventType.CONSENT_REQUEST:
        # UI prompts user (y/n/always/never)
        decision = await prompt_user(event.data)
        engine.handle_consent(event.data['consent_id'], decision)
```

### 4. Test All Changes
**100% test pass rate required** before any commit:

```bash
# Run all tests
uv run pytest tests/ -v

# Expected: 308/308 passing (as of v1.11.2.1)
# Any failures MUST be fixed before committing
```

## Key Files and Their Roles

### Configuration
- **ppxai-config.json** - Provider definitions (can be committed)
- **.env** - API keys only (NEVER commit)
- **ppxai-config.example.json** - Example config with inline docs

### Core Engine
- **ppxai/engine/client.py** - EngineClient facade (primary API)
- **ppxai/engine/providers/base.py** - BaseProvider interface
- **ppxai/engine/tools/manager.py** - ToolManager (current tool system)
- **ppxai/config.py** - Configuration loader, get_coding_model()

### TUI
- **ppxai/commands.py** - Slash command handlers (⚠️ autorouter bug location)
- **ppxai/ui.py** - Rich console rendering
- **ppxai/main.py** - TUI entry point

### Server
- **ppxai/server/jsonrpc.py** - JSON-RPC server for VSCode extension
- **ppxai/server/http.py** - HTTP + SSE server (deprecated, being replaced)

### VSCode Extension
- **vscode-extension/src/extension.ts** - Extension entry point
- **vscode-extension/src/httpClient.ts** - HTTP + SSE client
- **vscode-extension/src/chatPanel.ts** - Webview chat UI

### Testing
- **tests/test_commands.py** - Command handler tests (includes autorouter regression tests)
- **tests/test_config.py** - Configuration system tests (48 tests)
- **tests/test_file_editing.py** - File editing tool tests (25 tests)
- **tests/test_shell_consent.py** - Shell consent system tests

### Documentation
- **CLAUDE.md** - AI assistant context (version history, features, setup)
- **AGENT.md** - This file (AI workflow guidance)
- **ROADMAP.md** - Release history and future plans
- **CHANGELOG.md** - User-facing changelog
- **docs/AUTOROUTER-CONFIG.md** - Autorouter configuration guide
- **docs/SHELL_CONSENT_GUIDE.md** - Shell consent system guide
- **docs/RELEASE-PLAN-v1.11.x.md** - Current release series planning

## Development Workflow

### Environment Setup
```bash
# Recommended: Bootstrap script (downloads uv if needed)
python scripts/bootstrap.py --all

# Or: Manual uv installation
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --all-extras

# Configure API keys
cp .env.example .env
# Edit .env and add API keys
```

### Branch Strategy
- **master** - Stable releases (v1.11.2.1)
- **feature/name** - New features (e.g., feature/agentic-workflow)
- **bugfix/name** - Bug fixes (e.g., bugfix/llm-autorouter-bug)
- **Always branch from master** for new work

### Testing Requirements
1. **Run tests before committing:**
   ```bash
   uv run pytest tests/ -v
   ```

2. **Expected pass rate:** 308/308 (100%)

3. **Add regression tests** for bugs:
   ```python
   # Example: Autorouter provider mismatch regression test
   def test_send_coding_task_gemini(self, mock_get_coding, mock_client):
       """Regression test for bug-tui-20251223."""
       mock_get_coding.return_value = "gemini-2.5-pro"

       result = send_coding_task(
           mock_client, "convert", "Convert R to Python",
           "gemini-2.0-flash-lite", "gemini"  # Pass provider!
       )

       # Verify correct provider's coding model used
       call_args = mock_client.chat.call_args
       assert call_args[0][1] == "gemini-2.5-pro"
       mock_get_coding.assert_called_once_with("gemini")
   ```

### Release Process

#### Semantic Versioning
- **Major (2.0.0)** - Breaking changes
- **Minor (1.11.0)** - New features, backward compatible
- **Patch (1.11.2.1)** - Bug fixes only

#### Complete Release Checklist

**CRITICAL:** Follow this checklist exactly to prevent version inconsistencies.

##### 1. Version Number Updates (MANDATORY - All files)

Update the version number in **ALL** of these files:

```bash
# Core package version
pyproject.toml                          # Line 3: version = "X.Y.Z"
ppxai/__init__.py                       # Line 98: __version__ = "X.Y.Z"

# VSCode extension version
vscode-extension/package.json           # Line 5: "version": "X.Y.Z"
vscode-extension/package.json           # Line 86: "title": "PPXAI vX.Y.Z" (activitybar)

# Documentation metadata
ROADMAP.md                              # Line 11: Current Release: vX.Y.Z
ROADMAP.md                              # Line 1875: Last Updated: YYYY-MM-DD
ROADMAP.md                              # Line 1876: Current Version: vX.Y.Z

# Installation instructions
README.md                               # Lines 114, 116: ppxai-X.Y.Z.vsix references
README.md                               # Lines 120-126: "What's New in vX.Y.Z" section
vscode-extension/README.md              # Lines 60, 105: ppxai-X.Y.Z.vsix installation commands
```

**Important:**
- In README.md "What's New" section, update the version number AND the feature list to reflect the current release
- In installation commands, update VSIX filename references (e.g., `ppxai-X.Y.Z.vsix`)
- Do NOT change feature-introduction tags like "NEW (v1.11.2)" in documentation - these document when features were first added

**Pro tip:** Use grep to verify all versions are consistent before committing:
```bash
# Should show same version in all files
grep -r "1\.11\.2" --include="*.py" --include="*.toml" --include="*.json" --include="*.md" . 2>/dev/null | grep -v ".git" | grep -v "uv.lock" | grep -v "node_modules"
```

##### 2. Documentation Updates (MANDATORY)

Create/update these documentation files:

```bash
# Release notes (create new file for each release)
docs/RELEASE-NOTES-vX.Y.Z.md            # Comprehensive release notes

# User-facing changelog
CHANGELOG.md                            # Add new entry at top with version, date, changes

# AI assistant context (update current version section)
CLAUDE.md                               # Lines 9-20: Update "Current Version" and "What's New"

# Optional: Update release plan if needed
docs/RELEASE-PLAN-v1.11.x.md           # Mark release as complete, update status
```

##### 3. Pre-Release Verification

Run these checks **BEFORE** committing:

```bash
# 1. All tests must pass (308/308 expected as of v1.11.2.1)
uv run pytest tests/ -v

# 2. Verify version consistency across all files
grep -h "version.*=" pyproject.toml ppxai/__init__.py | sort -u
# Should show only ONE version line

# 3. Check VSCode extension versions match
grep '"version"' vscode-extension/package.json
grep '"title".*PPXAI' vscode-extension/package.json
# Both should show same version

# 4. Verify ROADMAP.md is up to date
grep "Current Release\|Current Version\|Last Updated" ROADMAP.md
```

##### 4. Commit and Tag

```bash
# Stage all version and documentation changes
git add pyproject.toml \
        ppxai/__init__.py \
        vscode-extension/package.json \
        ROADMAP.md \
        CHANGELOG.md \
        CLAUDE.md \
        docs/RELEASE-NOTES-vX.Y.Z.md

# Commit with descriptive message
git commit -m "feat: vX.Y.Z - Brief description

- What changed
- Why it matters
- Any breaking changes"

# Tag the release
git tag vX.Y.Z

# Push to GitHub
git push origin master --tags
```

##### 5. GitHub Actions Build & Release

**IMPORTANT:** GitHub Actions automatically creates the release when you push the tag. You must add release notes manually after the build completes.

```bash
# 1. Monitor GitHub Actions build (triggered by git push --tags)
unset GITHUB_TOKEN && source .github/gh-tokenv.env && export GH_TOKEN
gh run watch --exit-status  # Wait for build to complete

# 2. Verify release was auto-created with assets
gh release view vX.Y.Z

# 3. Add comprehensive release notes to the GitHub release
# (GitHub Actions creates release with default changelog link only)
gh release edit vX.Y.Z --notes-file docs/RELEASE-NOTES-vX.Y.Z.md

# 4. Verify release notes were added
gh release view vX.Y.Z | head -50
```

**Critical:** Do NOT skip step 3! The auto-generated release only has a basic changelog link. You must add the comprehensive release notes from `docs/RELEASE-NOTES-vX.Y.Z.md`.

##### 6. Build and Upload Assets

```bash
# macOS Intel builds (from macOS ARM)
./scripts/build-intel.sh

# Verify binaries were created
ls -lh dist/ppxai-macos-intel dist/ppxai-server-macos-intel

# Upload to GitHub release
unset GITHUB_TOKEN && source .github/gh-tokenv.env && export GH_TOKEN
gh release upload vX.Y.Z dist/ppxai-macos-intel dist/ppxai-server-macos-intel

# Other platforms (macOS ARM, Linux, Windows) are built via GitHub Actions CI/CD
# Check workflow status at: https://github.com/rcconsult/ppxai/actions
```

##### 7. Post-Release Verification

```bash
# 1. Verify all assets are uploaded (should show 9 assets for v1.11.3+)
gh release view vX.Y.Z
# Expected assets:
# - ppxai-1.11.3.vsix (VSCode extension)
# - ppxai-linux-amd64, ppxai-macos-arm64, ppxai-macos-intel, ppxai-windows.exe
# - ppxai-server-linux-amd64, ppxai-server-macos-arm64, ppxai-server-macos-intel, ppxai-server-windows.exe

# 2. CRITICAL: Verify release notes are present on GitHub
# Visit https://github.com/rcconsult/ppxai/releases/tag/vX.Y.Z
# Should show comprehensive release notes, NOT just "Full Changelog" link
# If missing, run: gh release edit vX.Y.Z --notes-file docs/RELEASE-NOTES-vX.Y.Z.md

# 3. Check GitHub Actions CI/CD completed successfully
gh run list --limit 5

# 4. Test installation from release
# Download and test the binaries work
curl -L -o /tmp/ppxai-test https://github.com/rcconsult/ppxai/releases/download/vX.Y.Z/ppxai-macos-arm64
chmod +x /tmp/ppxai-test
/tmp/ppxai-test --version  # Should show vX.Y.Z

# 4. Verify PyPI package (if published)
pip install --upgrade ppxai
python -c "import ppxai; print(ppxai.__version__)"  # Should show X.Y.Z
```

##### Common Release Mistakes

❌ **DON'T:**
- Forget to update `ppxai/__init__.py` __version__ (caught in v1.11.2.1)
- Miss the VSCode activitybar title version (caught in v1.11.2.1)
- Leave ROADMAP.md with old version (caught in v1.11.2.1)
- Forget to update README.md "What's New" section (caught in v1.11.3)
- Forget to update vscode-extension/README.md VSIX commands (caught in v1.11.3)
- Skip adding release notes to GitHub release (caught in v1.11.3) ⚠️
- Skip the grep verification step
- Commit without running tests
- Use `GITHUB_TOKEN` directly (always unset first!)

✅ **DO:**
- Follow this checklist line by line
- Use grep to verify version consistency
- Run all tests before committing
- Update ALL version locations (pyproject.toml, __init__.py, package.json x2, ROADMAP.md x3, README.md x2, vscode-extension/README.md x2)
- Add comprehensive release notes to GitHub release with `gh release edit`
- Use the project token file for gh commands
- Verify release notes are visible on GitHub releases page
- Verify all assets uploaded (9 total for v1.11.3+)

### GitHub CLI Authentication Pattern
**ALWAYS** use this pattern for `gh` commands:

```bash
# ✅ CORRECT - Unset stale env var, source project token
unset GITHUB_TOKEN && source .github/gh-tokenv.env && export GH_TOKEN && gh <command>

# ❌ WRONG - Uses potentially stale GITHUB_TOKEN
gh <command>
```

**Why:** `gh` checks `GITHUB_TOKEN` first, then `GH_TOKEN`. Stale `GITHUB_TOKEN` values cause 401 errors.

## Common Tasks

### Adding a New Provider
1. Add provider definition to ppxai-config.json:
   ```json
   {
     "providers": {
       "my-provider": {
         "name": "My Provider",
         "base_url": "https://api.example.com/v1",
         "api_key_env": "MY_PROVIDER_API_KEY",
         "default_model": "model-id",
         "coding_model": "best-coding-model-id",
         "models": {
           "model-id": {
             "name": "Model Name",
             "description": "Description"
           }
         }
       }
     }
   }
   ```

2. Add API key to .env:
   ```bash
   MY_PROVIDER_API_KEY=your-key-here
   ```

3. Test with both TUI and VSCode extension

### Adding a New Tool
1. Create tool implementation in `ppxai/engine/tools/builtin/`:
   ```python
   from ppxai.engine.tools.manager import ToolManager

   def register_tools(manager: ToolManager):
       manager.register(
           name="my_tool",
           description="What the tool does",
           parameters={...},
           function=my_tool_impl
       )

   def my_tool_impl(**kwargs):
       """Tool implementation."""
       return {"result": "..."}
   ```

2. Import in `ppxai/engine/tools/builtin/__init__.py`

3. Add tests in `tests/test_tools.py`

4. Update [docs/TOOL_CREATION_GUIDE.md](docs/TOOL_CREATION_GUIDE.md) with example

### Fixing a Bug
1. **Create bugfix branch:**
   ```bash
   git checkout -b bugfix/descriptive-name
   ```

2. **Reproduce the bug** with a test that fails

3. **Fix the bug** and verify test passes

4. **Add regression test** to prevent recurrence

5. **Update documentation** if needed

6. **For critical bugs:**
   - Create patch release (e.g., v1.11.2 → v1.11.2.1)
   - Follow release process
   - Document in CHANGELOG.md and release notes

### Updating Documentation
**Documentation standards:**
- Keep CLAUDE.md current with version and features
- Update ROADMAP.md for completed/upcoming releases
- Add entries to CHANGELOG.md for user-facing changes
- Create comprehensive release notes in docs/RELEASE-NOTES-v{version}.md
- Update inline code comments for non-obvious logic

## Testing Philosophy

### Test Coverage Expectations
- **All new features** require tests
- **All bug fixes** require regression tests
- **100% pass rate** before any commit
- **No skipped tests** without documented reason

### Test Organization
- `tests/test_commands.py` - Command handlers (66 tests)
- `tests/test_config.py` - Configuration system (48 tests)
- `tests/test_file_editing.py` - File editing tools (25 tests)
- `tests/test_shell_consent.py` - Shell consent system
- `tests/test_tools.py` - Tool system
- `tests/test_custom_endpoint_integration.py` - Integration tests (requires local vLLM/Ollama)

### Running Tests
```bash
# All tests
uv run pytest tests/ -v

# Specific module
uv run pytest tests/test_commands.py -v

# Specific test
uv run pytest tests/test_commands.py::TestCommandHandlers::test_send_coding_task_gemini -v

# Skip integration tests
uv run pytest tests/ --ignore=tests/test_custom_endpoint_integration.py
```

## Known Gotchas

### 1. Autorouter Provider Mismatch
**Symptom:** 404 errors when using non-Perplexity providers with coding commands
**Cause:** Missing provider parameter in send_coding_task() calls
**Fix:** Always pass self.provider parameter (see Critical Patterns above)
**Reference:** [bug-tui-20251223.txt](bug-tui-20251223.txt), fixed in v1.11.2.1

### 2. GitHub Token Conflicts
**Symptom:** 401 Unauthorized when using gh commands
**Cause:** Stale GITHUB_TOKEN env var takes precedence over project token
**Fix:** Always unset GITHUB_TOKEN before sourcing project token
**Reference:** CLAUDE.md GitHub CLI Authentication section

### 3. Markdown Table Rendering
**Symptom:** Raw `|:---|:---|` in TUI output
**Cause:** Rich markdown renderer doesn't support tables by default
**Fix:** Custom table parsing in ppxai/ui.py (fixed in v1.10.4)
**Reference:** tests/test_markdown_tables.py

### 4. Message Alternation Errors
**Symptom:** "user or tool message(s) should alternate with assistant message(s)"
**Cause:** Interrupt during streaming or tools enabled without history sync
**Fix:** Conversation history cleanup on interrupt (fixed in v1.10.5, v1.11.1)
**Reference:** tests/test_interrupt.py

## Next Planned Features (v1.11.3+)

- **@git context provider** - Include git history/diffs in AI context
- **@tree context provider** - Include directory structure in context
- **/agent command** - Autonomous multi-step task execution
- **Enhanced tool discovery** - Dynamic tool loading from external packages

See [docs/v1.11.0-agentic-workflow-plan.md](docs/v1.11.0-agentic-workflow-plan.md) for details.

## Quick Reference

### Version Number Format

⚠️ **CRITICAL - VSCode Extension Constraint:** VSCode extensions only support 3-part semantic versioning.

**Format:**
- ✅ CORRECT: `1.11.3` (major.minor.patch)
- ❌ WRONG: `1.11.2.2` (4-part version breaks VSCode extension build with "Invalid extension version" error)

**Rule:** Always use 3-part versions. For multiple patch releases, increment the patch number:
- 1.11.2 → 1.11.3 → 1.11.4 (patches)
- 1.11.x → 1.12.0 (minor release)
- 1.x.x → 2.0.0 (major release)

**Historical Note:** v1.11.2.1 and v1.11.2.2 were consolidated into v1.11.3 after discovering this constraint.

### Version Files to Update (All Required!)
**Core Version (4 locations):**
- pyproject.toml (line 3) - `version = "X.Y.Z"`
- ppxai/__init__.py (line 98) - `__version__ = "X.Y.Z"`
- vscode-extension/package.json (line 5) - `"version": "X.Y.Z"`
- vscode-extension/package.json (line 86) - `"title": "PPXAI vX.Y.Z"`

**Documentation (4 files):**
- ROADMAP.md (lines 11, 1875, 1876) - Current Release, Last Updated, Current Version
- CLAUDE.md (lines 9-20) - Update "Current Version" and "What's New"
- README.md (lines 114, 116) - VSIX filename references only (not feature tags!)
- CHANGELOG.md (add new entry at top)
- docs/RELEASE-NOTES-v{version}.md (create new)

### Test Pass Rate Target
**308/308 tests passing** (as of v1.11.2.1)

### Build Commands
```bash
# TUI + Server (all platforms)
uv run pyinstaller ppxai.spec
uv run pyinstaller ppxai-server.spec

# macOS Intel (cross-compile from ARM)
./scripts/build-intel.sh

# VSCode extension
cd vscode-extension && npm run compile && npx vsce package
```

### Useful Commands
```bash
# Run TUI
uv run ppxai

# Run server (for VSCode extension)
uv run ppxai-server

# Run tests
uv run pytest tests/ -v

# Check configuration
uv run python -c "from ppxai.config import validate_config; print(validate_config())"

# Install VSCode extension
code --install-extension ppxai-{version}.vsix
```

## Contact

- **Repository:** https://github.com/rcconsult/ppxai
- **Issues:** https://github.com/rcconsult/ppxai/issues
- **Releases:** https://github.com/rcconsult/ppxai/releases

---

**Last Updated:** 2025-12-24 (v1.11.4 development)
**Maintained for:** AI assistants working on ppxai
