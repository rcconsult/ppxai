# Documentation Sync-Up Plan for v1.11.7

**Created:** 2025-12-26
**Status:** Proposed - Awaiting Approval
**Branch:** refactor/maintenance-no-legacy-code

## Versioning Context

| Version | Status | Content |
|---------|--------|---------|
| v1.11.6 | ✅ Current | Legacy code removed, clean codebase |
| **v1.11.7** | 🎯 Next | `/agent` command + documentation sync |
| v1.11.8-10 | Planned | Agent loop bug fixes |
| v1.12.0 | Future | Per-provider tool config, code quality |

## Overview

This plan synchronizes all markdown documentation with the v1.11.7 codebase state (legacy code removed, EngineClient is now the primary interface, preparing for `/agent` feature).

## Phase 1: Archive Obsolete Files (14 files → docs/archive/)

These files document completed work or superseded approaches:

| File | Reason |
|------|--------|
| `docs/400_ERROR_ROOT_CAUSE.md` | Issue fixed in v1.11.0 |
| `docs/400-ERROR-INVESTIGATION.md` | Investigation complete |
| `docs/uv-migration-plan.md` | Migration complete (v1.9.0) |
| `docs/sse-migration-plan.md` | Migration complete (v1.9.0) |
| `docs/PHASE1-TOOL-CALLING-FIXES.md` | Phase complete |
| `docs/PHASE1-TUI-RESPONSE-FIX.md` | Fixed in v1.11.1 |
| `docs/REFACTORING-PLAN-SHARED-MODULES.md` | Refactoring complete |
| `docs/TUI_VSCODE_CONSISTENCY_ANALYSIS.md` | Analysis complete, unified |
| `docs/workspace-context-injection.md` | Superseded by v1.11.4 context system |
| `docs/TOOL_APPROACHES.md` | Superseded by engine tools |
| `docs/TOOL_INTEGRATION.md` | Superseded by engine tools |
| `docs/BUGFIX-gemini-tool-calling.md` | Fix migrated to EngineClient |
| `docs/LEGACY-CODE-MODERNIZATION.md` | Legacy code removed |
| `docs/AGENT-READINESS-CLEANUP.md` | Cleanup complete |

## Phase 2: Delete Obsolete Files (3 files)

These files have no historical value:

| File | Reason |
|------|--------|
| `docs/benchmark.md` | Empty/placeholder |
| `docs/PROMPT-REFINEMENT-2.md` | Superseded by v1.10.x |
| `perplexity_tools_prompt_based.py.md` | If exists - artifact |

## Phase 3: Update High-Priority Files (6 files)

### 3.1 ROADMAP.md
- Add v1.11.5, v1.11.6 releases
- Mark legacy cleanup complete
- Update v1.12.0 status

### 3.2 README.md
- Update version to 1.12.0
- Remove legacy client references
- Update installation instructions

### 3.3 docs/architecture-refactoring.md
- Mark EngineClient as primary (not transitional)
- Remove "legacy support" sections
- Update architecture diagram

### 3.4 docs/v1.11.0-agentic-workflow-plan.md
- Mark phases 2-3 complete (git/tree context)
- Update phase 4 status
- Note legacy cleanup complete

### 3.5 CLAUDE.md
- Update version to 1.12.0
- Remove legacy code references
- Update architecture section

### 3.6 CHANGELOG.md
- Add v1.12.0 entry
- Document legacy code removal

## Phase 4: Create Missing Release Notes (3 files)

| File | Content |
|------|---------|
| `docs/releases/v1.11.4.md` | Git/tree context providers |
| `docs/releases/v1.11.5.md` | Tool improvements |
| `docs/releases/v1.11.6.md` | Pre-cleanup release |

## Phase 5: Verify Current Files (48 files)

These files are confirmed current and need no changes:
- All files in `docs/releases/` (except missing ones)
- `docs/AUTOROUTER-CONFIG.md`
- `docs/SHELL_CONSENT_GUIDE.md`
- `docs/CUSTOM-TOOLS-GUIDE.md`
- Test documentation
- API documentation

## Execution Commands

```bash
# Phase 1: Create archive directory and move files
mkdir -p docs/archive

# Move obsolete files
git mv docs/400_ERROR_ROOT_CAUSE.md docs/archive/
git mv docs/400-ERROR-INVESTIGATION.md docs/archive/
git mv docs/uv-migration-plan.md docs/archive/
git mv docs/sse-migration-plan.md docs/archive/
git mv docs/PHASE1-TOOL-CALLING-FIXES.md docs/archive/
git mv docs/PHASE1-TUI-RESPONSE-FIX.md docs/archive/
git mv docs/REFACTORING-PLAN-SHARED-MODULES.md docs/archive/
git mv docs/TUI_VSCODE_CONSISTENCY_ANALYSIS.md docs/archive/
git mv docs/workspace-context-injection.md docs/archive/
git mv docs/TOOL_APPROACHES.md docs/archive/
git mv docs/TOOL_INTEGRATION.md docs/archive/
git mv docs/BUGFIX-gemini-tool-calling.md docs/archive/
git mv docs/LEGACY-CODE-MODERNIZATION.md docs/archive/
git mv docs/AGENT-READINESS-CLEANUP.md docs/archive/

# Phase 2: Delete obsolete files
git rm docs/benchmark.md 2>/dev/null || true
git rm docs/PROMPT-REFINEMENT-2.md 2>/dev/null || true

# Phases 3-4: Manual edits required
```

## Validation

After execution:
```bash
# Count docs in archive
ls -la docs/archive/ | wc -l  # Should be ~14

# Verify no legacy references in main docs
grep -r "AIClient" docs/ --include="*.md" | grep -v archive/
grep -r "PerplexityClientPromptTools" docs/ --include="*.md" | grep -v archive/

# Check version references
grep -r "1.11" docs/*.md | head -20
```

## Estimated Impact

- **Lines archived:** ~2,500+ lines (14 files)
- **Lines deleted:** ~50 lines (2-3 files)
- **Lines updated:** ~200 lines (6 files)
- **Lines created:** ~300 lines (3 release notes)
- **Net reduction:** ~2,000+ lines of outdated documentation
