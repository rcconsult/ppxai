# Release Workflow

Complete end-to-end release automation for ppxai. This command handles:
1. Version number updates across all files
2. Documentation updates (CHANGELOG, README, ROADMAP)
3. Test execution and validation
4. Git tagging and GitHub deployment
5. **Release notes publication** (the critical step!)
6. Asset verification

## Arguments
- `$ARGUMENTS` - Version number (e.g., v1.11.4)

## What This Command Does

When you run `/release v1.11.4`, the assistant will:

### Phase 1: Validation & Preparation
1. **Validate version format** - must be 3-part semantic version (e.g., v1.11.4)
   - ⚠️ VSCode extensions only support 3-part versions (not 4-part like v1.11.2.1)

2. **Check current versions** - read version from all files:
   - pyproject.toml
   - ppxai/__init__.py
   - vscode-extension/package.json (2 locations)
   - ROADMAP.md (3 locations)
   - README.md
   - vscode-extension/README.md

3. **Update version numbers** - if versions are outdated:
   - Show a diff of what will change
   - Ask for confirmation before making changes
   - Update all 12+ version locations automatically

4. **Update documentation**:
   - Check if docs/RELEASE-NOTES-<version>.md exists
     - If missing, offer to create a template based on AGENT.md guidelines
   - Check if CHANGELOG.md has entry for this version
     - If missing, ask user what changed and add entry
   - **CRITICAL: Update ROADMAP.md** (v1.11.4 fix):
     - Change "Current Release: v<old>" to "Current Release: v<new>"
     - Move old "Current Release" section to "Previous Release: v<old>"
     - Add new release details: features, bug fixes, testing, performance
   - **CRITICAL: Update README.md** (v1.11.6 fix):
     - Update "What's New in v<version>" section with new features/fixes
     - Update ALL VSCode extension version references (ppxai-X.Y.Z.vsix)
       - Line ~114: `ppxai-X.Y.Z.vsix` download reference
       - Line ~116: `code --install-extension ppxai-X.Y.Z.vsix` command
     - This step was repeatedly missed in v1.11.4, v1.11.5, v1.11.6!
   - **CRITICAL: Update vscode-extension/README.md**:
     - Update ALL `ppxai-X.Y.Z.vsix` references (typically 2 locations)
   - Update CLAUDE.md "Current Version" section

5. **Validate release** (v1.11.4 addition):
   ```bash
   python3 scripts/validate-release.py v<version>
   ```
   - ✅ Checks all version numbers are consistent across files
   - ✅ Verifies ROADMAP.md "Current Release" updated
   - ✅ Verifies CLAUDE.md "Current Version" updated
   - ✅ Ensures git working directory is clean
   - If validation fails, show errors and abort

6. **Run tests**:
   ```bash
   uv run pytest tests/ -v
   ```
   - If tests fail, abort and show failures
   - Require user confirmation to proceed if <296 tests pass

7. **Create release commit**:
   - Show git diff of all changes
   - Ask user to confirm commit message
   - Commit with proper format (feat: v<version> - <description>)

### Phase 2: Deployment
8. **Check git status** - ensure working directory is clean

9. **Run latency benchmark** (optional but recommended):
   ```bash
   uv run python scripts/benchmark.py --provider perplexity --iterations 3
   ```
   - Warn if >20% performance regression
   - Ask user whether to proceed

10. **Create and push tag**:
    ```bash
    git tag -a <version> -m "<version> release"
    git push origin master
    git push origin <version>
    ```

11. **Monitor GitHub Actions build**:
    ```bash
    unset GITHUB_TOKEN && source .github/gh-tokenv.env && export GH_TOKEN && gh run watch --exit-status
    ```
    - Wait for all jobs to complete
    - Show build status for each platform
    - If build fails, show error and abort

12. **🚨 CRITICAL: Add release notes to GitHub release**:
    ```bash
    unset GITHUB_TOKEN && source .github/gh-tokenv.env && export GH_TOKEN && gh release edit <version> --notes-file docs/RELEASE-NOTES-<version>.md
    ```
    - **This is MANDATORY!** GitHub Actions only creates a basic release
    - This was the missing step in v1.11.3
    - Verify release notes are visible after upload

13. **Build Intel Mac binaries locally**:
    ```bash
    ./scripts/build-intel.sh <version>
    ```
    - Only if running on macOS
    - Automatically uploads to GitHub release

14. **Verify release completion**:
    ```bash
    unset GITHUB_TOKEN && source .github/gh-tokenv.env && export GH_TOKEN && gh release view <version>
    ```

    **Must verify:**
    - ✅ 9 assets uploaded:
      - ppxai-1.11.4.vsix (VSCode extension)
      - ppxai-linux-amd64, ppxai-macos-arm64, ppxai-macos-intel, ppxai-windows.exe
      - ppxai-server-linux-amd64, ppxai-server-macos-arm64, ppxai-server-macos-intel, ppxai-server-windows.exe
    - ✅ Release notes visible (NOT just "Full Changelog" link)
    - ✅ All version numbers correct

15. **Final status report**:
    - Show release URL
    - Confirm all assets present
    - Confirm release notes published
    - Mark release as complete ✅

## Interactive Prompts

The assistant will pause and ask for confirmation at these points:

1. **Before updating version numbers** - "Update versions in 12 files to v1.11.4? [yes/show diff/no]"
2. **Before creating RELEASE-NOTES** - "Create release notes template? [yes/no]"
3. **Before updating CHANGELOG** - "Add CHANGELOG entry? What changed? [describe changes]"
4. **Before updating ROADMAP** - "Update ROADMAP.md 'Current Release' section? [yes/show template/no]"
5. **Before updating README** - "Update 'What's New' section? What are the key features? [describe]"
6. **After validation** - "Validation passed ✅. Continue? [yes/show details/no]"
7. **After tests run** - "Tests passed (296/308). Proceed with release? [yes/no]"
8. **Before commit** - "Commit all changes? [yes/show diff/edit message/no]"
9. **After benchmark** - "Benchmark complete (TTFT 1450ms). Performance OK? [yes/show details/no]"
10. **Before pushing tag** - "Push v1.11.4 tag to GitHub? This will trigger the build. [yes/no]"

## Error Handling

If any step fails, the assistant will:
- Show the error clearly
- Explain what went wrong
- Suggest remediation steps
- Ask whether to continue or abort

Common failure scenarios:
- **Git dirty state** → "Working directory not clean. Commit or stash changes first."
- **Validation fails** → "Version mismatch in ROADMAP.md. Update 'Current Release' section."
- **Tests fail** → "Tests failed. Review failures and fix before releasing."
- **Missing RELEASE-NOTES** → "Create docs/RELEASE-NOTES-v1.11.4.md first."
- **GitHub Actions build fails** → "Build failed. Check logs at [URL]. Abort release."
- **Missing assets** → "Only 7/9 assets uploaded. Intel Mac builds missing?"

## Usage Examples

### Simple release (assistant handles everything):
```
User: /release v1.11.4
Assistant: [Validates, updates versions, docs, tests, commits, deploys, verifies]
Assistant: ✅ Release v1.11.4 complete! https://github.com/rcconsult/ppxai/releases/tag/v1.11.4
```

### User provides release notes:
```
User: /release v1.11.4
Assistant: docs/RELEASE-NOTES-v1.11.4.md not found. Create template? [yes/no]
User: no, I'll write it myself
Assistant: [Pauses for user to create file]
User: done
Assistant: [Continues with release workflow]
```

### Performance regression detected:
```
User: /release v1.11.4
Assistant: [Runs benchmark]
Assistant: ⚠️ Performance regression: TTFT 2100ms (baseline 1450ms, +45% slower)
Assistant: Proceed anyway? [yes/no/re-run]
User: no
Assistant: Release aborted. Investigate performance regression.
```

## No Version Provided

If user runs `/release` without version:
- Show current version from pyproject.toml
- Show latest GitHub release
- Suggest next version based on semantic versioning
- Show usage instructions

## Reference

Full release checklist: See AGENT.md "Release Process" section
Version number format: AGENT.md "Version Number Format" (3-part only!)
Release process improvements: [docs/RELEASE-PROCESS-IMPROVEMENTS.md](docs/RELEASE-PROCESS-IMPROVEMENTS.md)
Validation script: [scripts/validate-release.py](scripts/validate-release.py)

## Validation Script Usage

Before releasing, you can manually validate that all files are updated:

```bash
python3 scripts/validate-release.py v1.11.4
```

This checks:
- ✅ pyproject.toml version
- ✅ ppxai/__init__.py version
- ✅ vscode-extension/package.json version
- ✅ ROADMAP.md "Current Release" section
- ✅ CLAUDE.md "Current Version" section
- ✅ Git working directory is clean

The `/release` command runs this automatically in step 5.
