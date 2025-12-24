# Release Process Improvements

## Problem

The current `/release` skill doesn't update all documentation files when creating a new release, leading to outdated version references across the codebase.

**Example from v1.11.4 release:**
- ✅ Updated: `pyproject.toml`, `ppxai/__init__.py`, `vscode-extension/package.json`
- ❌ Missed: `ROADMAP.md` (still showed v1.11.3 as "Current Release")
- ✅ Already updated: `CLAUDE.md` (had v1.11.4 - likely from manual update during development)

## Files That Need Version Updates

### Critical (Version Numbers)
1. **pyproject.toml** - Line 3: `version = "X.Y.Z"`
2. **ppxai/__init__.py** - Line 98: `__version__ = "X.Y.Z"`
3. **vscode-extension/package.json** - Lines 5, 86: `"version": "X.Y.Z"` and `"title": "PPXAI vX.Y.Z"`

### Documentation (Release Notes & Status)
4. **ROADMAP.md**
   - Line 11: `## Current Release: vX.Y.Z`
   - Line 13: Status description
   - Line 15: Release date
   - Lines 17+: Features, bug fixes, files changed, testing, performance
   - Move previous "Current Release" to "Previous Release" section

5. **CLAUDE.md**
   - Line 9: `**Current Version:** vX.Y.Z (Feature Name)`
   - Lines 11+: What's New section describing latest release

6. **README.md** (optional)
   - May have version-specific feature descriptions
   - Generally less critical as it's more evergreen

## Proposed Solutions

### Option A: Extend `/release` Skill (Recommended)

Update the release skill to include a documentation update step:

```python
# scripts/release.py or .claude/skills/release.md

def release_workflow(version):
    # 1. Validate version format
    validate_version(version)

    # 2. Check git status
    check_git_clean()

    # 3. Update version numbers
    update_version_files(version)  # pyproject.toml, __init__.py, package.json

    # 4. Update documentation  # ← NEW STEP
    update_documentation(version)  # ROADMAP.md, CLAUDE.md

    # 5. Commit version changes
    git_commit_version_bump(version)

    # 6. Run benchmarks
    run_latency_benchmark()

    # 7. Create and push tag
    create_git_tag(version)
    push_git_tag(version)

    # 8. Monitor CI/CD
    monitor_github_actions(version)

    # 9. Build Intel Mac binaries (if applicable)
    build_intel_mac(version)

    # 10. Verify release assets
    verify_release(version)

    # 11. Update release notes  # ← NEW STEP
    update_github_release_notes(version)

def update_documentation(version):
    """Update ROADMAP.md and CLAUDE.md for new release."""
    # Prompt user for:
    # - Release status/tagline (e.g., "@git and @tree Context Injection")
    # - Key features (bullet list)
    # - Bug fixes (bullet list)
    # - Performance metrics (from benchmark)

    # Update ROADMAP.md:
    # - Replace "Current Release: vX.Y.Z" with new version
    # - Move old current release to "Previous Release" section
    # - Add new features, bug fixes, files changed

    # Update CLAUDE.md:
    # - Replace "Current Version: vX.Y.Z" with new version
    # - Add/update "What's New" section
```

**Pros:**
- Single command handles everything
- No manual steps, reduces human error
- Consistent documentation across releases

**Cons:**
- More complex script
- Requires structured input (features, bug fixes, etc.)
- May need interactive prompts

### Option B: Pre-Release Checklist

Create a mandatory checklist that must be completed before `/release`:

```markdown
# .claude/skills/pre-release-checklist.md

## Pre-Release Checklist for vX.Y.Z

Run this before `/release vX.Y.Z`:

### Version Files
- [ ] Updated pyproject.toml version
- [ ] Updated ppxai/__init__.py version
- [ ] Updated vscode-extension/package.json version (2 places)

### Documentation
- [ ] Updated ROADMAP.md "Current Release" section
- [ ] Moved previous release to "Previous Release" section
- [ ] Updated CLAUDE.md "Current Version" and "What's New"
- [ ] Verified README.md doesn't have outdated version references

### Testing
- [ ] All tests passing (uv run pytest tests/ -v)
- [ ] Manual TUI testing completed
- [ ] VSCode extension tested (if applicable)

### Git
- [ ] All changes committed
- [ ] Working directory clean (git status)
- [ ] On correct branch (usually master)

Once all checked, run: `/release vX.Y.Z`
```

**Pros:**
- Simple, no code changes needed
- Explicit visibility into what needs updating
- Can be run manually or via skill

**Cons:**
- Relies on human discipline
- Easy to skip steps
- Not automated

### Option C: Post-Release Validation

Add validation after release to detect missing updates:

```python
def post_release_validation(version):
    """Validate all files have been updated to the release version."""
    errors = []

    # Check version files
    if not check_file_version("pyproject.toml", version):
        errors.append("pyproject.toml version mismatch")

    if not check_file_version("ppxai/__init__.py", version):
        errors.append("ppxai/__init__.py version mismatch")

    # Check documentation
    if not check_roadmap_current_version("ROADMAP.md", version):
        errors.append("ROADMAP.md 'Current Release' not updated")

    if not check_claude_md_version("CLAUDE.md", version):
        errors.append("CLAUDE.md 'Current Version' not updated")

    if errors:
        print("⚠️ Release validation failed:")
        for error in errors:
            print(f"  - {error}")
        print("\nPlease update these files and re-run /release")
        return False

    print("✅ All files updated correctly")
    return True
```

**Pros:**
- Catches mistakes before they reach production
- Can be added to existing workflow
- Lightweight, low complexity

**Cons:**
- Detects issues but doesn't fix them
- Still requires manual correction
- Adds validation overhead

### Option D: Hybrid Approach (Best Practice) ⭐

Combine automated updates with validation:

1. **Pre-release:** Script updates version numbers in code files (pyproject.toml, __init__.py, package.json)
2. **Interactive prompts:** Ask user for release notes content (features, bug fixes)
3. **Auto-generate docs:** Update ROADMAP.md and CLAUDE.md using templates
4. **Validate:** Check all files before creating git tag
5. **Commit:** Single commit with all version + doc updates

```bash
# Example workflow
./scripts/prepare-release.py v1.11.4
# Prompts:
#   - Release tagline: "@git and @tree Context Injection"
#   - Key features (paste from notes or type interactively)
#   - Bug fixes (optional)
#   - Performance improvements (from benchmark)
#
# Updates:
#   - pyproject.toml, __init__.py, package.json (version)
#   - ROADMAP.md (current release section)
#   - CLAUDE.md (current version, what's new)
#
# Validates:
#   - All version numbers match
#   - Documentation updated
#   - Git clean
#
# Creates commit:
#   - "chore: Prepare v1.11.4 release"
#
# Then run:
/release v1.11.4
# Runs benchmarks, creates tag, triggers CI/CD
```

**Pros:**
- Best of all approaches
- Automated where possible, interactive where needed
- Validation prevents mistakes
- Clear separation: prepare vs. execute

**Cons:**
- Two-step process (prepare, then release)
- More initial development effort

## Recommendation

**Implement Option D (Hybrid Approach)** in phases:

### Phase 1: Quick Win (This Release Cycle)
- Add post-release validation (Option C) to detect missing updates
- Create pre-release checklist document (Option B)
- Use checklist manually for v1.11.5+

### Phase 2: Automation (Next Sprint)
- Create `scripts/prepare-release.py` script
- Interactive prompts for release notes
- Auto-update ROADMAP.md and CLAUDE.md using templates
- Integrate validation

### Phase 3: Full Integration (Future)
- Merge prepare-release into /release skill
- Single command handles everything
- Optional: Add GitHub API integration for release notes

## Implementation Plan

### Phase 1 Tasks (Immediate)
1. ✅ Fix ROADMAP.md for v1.11.4 (done)
2. Create `docs/RELEASE-CHECKLIST-TEMPLATE.md`
3. Add validation script `scripts/validate-release.py`
4. Update `/release` skill to call validation script

### Phase 2 Tasks (v1.11.5)
1. Create `scripts/prepare-release.py`
2. Add ROADMAP.md template generation
3. Add CLAUDE.md template generation
4. Integrate with /release skill

### Phase 3 Tasks (v1.12.0+)
1. Add GitHub API integration
2. Auto-generate release notes from commits
3. Fully automated release workflow

## Files to Create/Modify

### New Files
- `docs/RELEASE-CHECKLIST-TEMPLATE.md` - Manual checklist
- `scripts/validate-release.py` - Validation script
- `scripts/prepare-release.py` - Release preparation script (Phase 2)
- `scripts/templates/ROADMAP_RELEASE_TEMPLATE.md` - Template for ROADMAP sections
- `scripts/templates/CLAUDE_MD_RELEASE_TEMPLATE.md` - Template for CLAUDE.md updates

### Existing Files to Modify
- `.claude/skills/release.md` - Add validation step
- `AGENT.md` - Document new release process

## Example Templates

### ROADMAP Release Template
```markdown
## Current Release: v{{VERSION}}

**Status**: ✅ {{STATUS_TAGLINE}}

Released: {{RELEASE_DATE}}

**Goal**: {{GOAL_DESCRIPTION}}

**New Features**:
{{#FEATURES}}
- ✅ **{{FEATURE_NAME}}** - {{FEATURE_DESCRIPTION}}
  {{#FEATURE_DETAILS}}
  - {{DETAIL}}
  {{/FEATURE_DETAILS}}
{{/FEATURES}}

**Architecture Changes**:
{{#ARCHITECTURE_CHANGES}}
- ✅ **{{CHANGE_NAME}}** - {{CHANGE_DESCRIPTION}}
{{/ARCHITECTURE_CHANGES}}

**Files Changed**:
{{#FILES_CHANGED}}
- `{{FILE_PATH}}` - {{CHANGE_DESCRIPTION}}
{{/FILES_CHANGED}}

**Testing**:
{{#TEST_STATS}}
- {{STAT_DESCRIPTION}}
{{/TEST_STATS}}

**Performance**:
- TTFT: {{TTFT}}ms ({{TTFT_RATIO}}x baseline - {{TTFT_CHANGE}})
- Total: {{TOTAL}}ms ({{TOTAL_RATIO}}x baseline - {{TOTAL_CHANGE}})
- Throughput: {{THROUGHPUT}} tokens/sec
- Status: {{PERFORMANCE_STATUS}}

**Bug Fixes**:
{{#BUG_FIXES}}
- ✅ {{BUG_DESCRIPTION}}
{{/BUG_FIXES}}

**Branch**: `{{BRANCH_NAME}}` → `master`

**Documentation**: See [{{DOC_LINK_TEXT}}]({{DOC_LINK_URL}})
```

### CLAUDE.md Release Template
```markdown
**Current Version:** v{{VERSION}} ({{TAGLINE}})

**What's New in v{{VERSION}} (Released {{RELEASE_DATE}}):**
{{#FEATURES}}
- **{{FEATURE_TYPE}}:** {{FEATURE_DESCRIPTION}}
{{/FEATURES}}

**Previous Release (v{{PREVIOUS_VERSION}} - {{PREVIOUS_DATE}}):**
- {{PREVIOUS_SUMMARY}}
```

## Conclusion

The hybrid approach (Option D) provides the best balance of automation and control:
- **Immediate:** Add validation to prevent future issues
- **Short-term:** Create preparation script for v1.11.5
- **Long-term:** Fully automated release workflow

This ensures:
1. ✅ No outdated documentation in releases
2. ✅ Consistent release notes format
3. ✅ Reduced manual effort
4. ✅ Validation catches mistakes early
