# Documentation Consolidation

Review, consolidate, and clean up project documentation. Archives stale docs, fixes broken cross-references, and updates files to reflect current repo state.

## Arguments
- `$ARGUMENTS` - Optional scope: `all` (full review), `archive` (archive stale docs only), `links` (fix broken links only), `top-level` (review root .md files only). Default: `all`

## Usage

Full documentation review and consolidation:
```
/docs-consolidate
/docs-consolidate all
```

Archive completed/stale docs only:
```
/docs-consolidate archive
```

Fix broken cross-references only:
```
/docs-consolidate links
```

Review and update top-level .md files only:
```
/docs-consolidate top-level
```

## Workflow

### Phase 1: Inventory (all scopes)

1. **List all documentation files:**
   ```bash
   ls *.md
   ls docs/*.md
   ls docs/archive/
   ```

2. **Check git branch and version context:**
   ```bash
   git branch --show-current
   git log --oneline -5
   ```

3. **Read key state files** to understand current version and goals:
   - `ROADMAP.md` — current release status
   - `CHANGELOG.md` — what's been released
   - `docs/TODO-v*.md` — active work items (if any)

### Phase 2: Archive Stale Docs (scopes: `all`, `archive`)

**Criteria for archiving:**
- TODO files for completed/released versions (e.g., `TODO-v1.15.3.md` after v1.15.3 is released)
- Debug session logs that have been consolidated into summary docs
- Design/planning docs whose proposals have been fully implemented
- Release plans for completed releases
- Implementation quick-refs superseded by consolidated TODO docs

**Archive procedure:**
1. Move with `git mv <file> docs/archive/`
2. Use descriptive names if needed (e.g., `TODO-v1.16.0-file-navigation.md` instead of generic name)
3. For files with many inbound references, consider replacing with a redirect stub instead of moving
4. Check for and update all cross-references (see Phase 3)

**Do NOT archive:**
- Active TODO/planning docs
- User-facing guides (AGENT_MODE_GUIDE, CHECKPOINT_GUIDE, etc.)
- Architecture docs still relevant to current codebase
- Release notes (keep in `docs/`, archive only very old ones if needed)

### Phase 3: Fix Broken Links (scopes: `all`, `links`)

1. **Scan for broken references** across all non-archive `.md` files:
   - Check relative links like `[text](path/to/file.md)` against actual file existence
   - Check inline references like `See \`path/to/file.md\``
   - Focus on non-archive files first, then fix archive-internal references

2. **Common breakage patterns:**
   - Files moved to `docs/archive/` but references not updated
   - Files renamed but old name still referenced
   - Relative path depth wrong (e.g., `../` vs `./` after file moved)
   - Archive files referencing siblings that moved to same directory (path depth changes)

3. **Fix procedure:**
   - Update links in non-archive files to point to new locations
   - Update archive-internal links where files became siblings
   - Verify fixes with a second scan

### Phase 4: Update Top-Level Files (scopes: `all`, `top-level`)

**Files to review** (root `*.md` files):

| File | What to check |
|------|---------------|
| `README.md` | Version numbers, model lists, project structure tree, test count, install flags |
| `ROADMAP.md` | Current release status, version references, TODO links |
| `CHANGELOG.md` | Latest entry matches current release, links to release notes |
| `CLAUDE.md` | Version alignment section, highlights for current version |
| `AGENTS.md` | References to docs, active TODO file |
| `BUILD.md` | Entry points, build commands still valid |
| `CONTRIBUTING.md` | Entry points, setup instructions still valid |
| `RELATED-PROJECTS.md` | Timeline estimates, status |
| `SPECIFICATIONS.md` | Version-neutral, usually no changes |
| `CODE_OF_CONDUCT.md` | Standard, no changes |
| `SECURITY.md` | Consent system docs, usually no changes |

**Key things to update:**
- Stale version numbers (check install flags, badge text)
- Outdated model/provider lists (especially OpenAI model names)
- Project structure tree missing new files (e.g., new providers, new modules)
- Test count badges/references
- Links to archived/moved files
- Redirect stubs for root-level TODO files that conflict with `docs/` versions

### Phase 5: Report

Provide a summary of all changes:
- Files archived (with reasons)
- Broken links fixed (count and files affected)
- Top-level files updated (what changed)
- Files reviewed but unchanged (with brief reason)

## Key Conventions

### Archive Structure
```
docs/archive/
├── v1.15.1-completed/     # Grouped by release
├── v1.15.2-completed/
├── v1.15.3/
├── v1.15.4/
├── benchmarks/            # Benchmark results
├── design/                # Design docs
├── release-notes/         # Old release notes
├── ARCHIVE-*.md           # Consolidated archives
├── RELEASE-PLAN-*.md      # Completed release plans
└── TODO-*.md              # Completed TODOs
```

### Single Source of Truth
- Active TODO/planning lives in `docs/TODO-v{version}.md`
- If a root-level `TODO-v{version}.md` exists and conflicts, replace it with a redirect stub pointing to the `docs/` version
- `AGENTS.md` should reference the active TODO file

### Redirect Stub Format
When a root-level file has many inbound references but its content has moved:
```markdown
# Title

> **This file is a redirect.** The single source of truth is:
>
> **[docs/TARGET.md](docs/TARGET.md)**
>
> The original content has been archived to
> [docs/archive/DESCRIPTIVE-NAME.md](docs/archive/DESCRIPTIVE-NAME.md).
```

### Commit Message Format
```
docs: <brief description of consolidation work>

- Archive <file> (<reason>)
- Fix N broken links across M files
- Update <file>: <what changed>
```

## Notes

- Always use `git mv` for moves (preserves history)
- Read files before editing — never guess at content
- Fix non-archive references first, then archive-internal ones
- When in doubt about archiving, keep the file and note it in the report
- Run `git diff --stat` before committing to verify scope of changes
- Do NOT push unless explicitly asked
