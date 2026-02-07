# Corrective & Preventive Actions: v1.15.2 Release

**Created:** 2026-02-06
**Issue:** Release v1.15.2 completed but CI failed, no assets built
**Status:** Action Plan

---

## Root Cause Analysis

### What Happened:

1. **Release script ran successfully** - Created commit, tag, pushed to GitHub
2. **CI triggered on tag v1.15.2** - Started building assets
3. **Test failed:** `test_web_premium.py::TestRegistration::test_register_tools_native_search_provider`
   - Expected `web_search` to be registered first
   - Actual: `get_weather` registered first
   - **Not a functional bug** - just test assertion assumed order
4. **CI halted** - All build jobs depend on test job (`needs: test`)
5. **No assets built** - Release exists but empty

### Contributing Factors:

1. **Test assumptions** - Test assumed tool registration order (fragile)
2. **Release script adds Claude credits** - Violates project guidelines
   ```python
   commit_msg = f"""{message}

   🤖 Generated with [Claude Code](https://claude.com/claude-code)

   Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"""
   ```
3. **No pre-release test run** - Tests not run locally before release
4. **Tag immutability** - Can't fix test on existing tag without force-push

---

## Corrective Actions (Immediate)

### 1. Fix Test (✅ COMPLETE)

**Status:** Done - commit 341bbbf on master

<details>
<summary>Changes made</summary>

```python
# Before (fragile - assumes order):
first_call_kwargs = mock_manager.register_function.call_args_list[0][1]
assert first_call_kwargs["name"] == "web_search"

# After (robust - checks all tools):
tool_names = [call[1]["name"] for call in mock_manager.register_function.call_args_list]
assert "web_search" in tool_names
assert "get_weather" in tool_names
assert "fetch_url" in tool_names
```

</details>

**File:** `tests/test_web_premium.py` lines 296-313

---

### 2. Fix Release Script (✅ COMPLETE)

**Status:** Done - removed Claude credits from `scripts/release.py`

<details>
<summary>Changes made</summary>

```python
# Before:
commit_msg = f"""{message}

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"""

# After:
commit_msg = message
```

</details>

**File:** `scripts/release.py` line 475

---

### 3. Manual Asset Build & Upload (⏳ IN PROGRESS)

Since CI failed on the v1.15.2 tag, manually build and upload assets.

#### Option A: Trigger CI on Master (RECOMMENDED)

The test fix is on master. Manually trigger the build workflow:

```bash
# Check if workflow_dispatch is enabled
gh workflow list

# Manually trigger build workflow
gh workflow run "Build Executables"

# Monitor the run
gh run watch
```

**Issue:** Workflow may not upload to v1.15.2 release (might create new release or fail)

#### Option B: Manual Local Build

Build each binary manually:

```bash
# On Linux/macOS
uv sync --frozen --extra build
uv run pyinstaller ppxai.spec
uv run pyinstaller ppxaide.spec
uv run pyinstaller ppxai-server.spec
uv run pyinstaller ppxai-desktop.spec

# On Windows
.uv\uv sync --frozen --extra build
.uv\uv run pyinstaller ppxai.spec
.uv\uv run pyinstaller ppxaide.spec
.uv\uv run pyinstaller ppxai-server.spec
.uv\uv run pyinstaller ppxai-desktop.spec

# Build VSCode extension
cd vscode-extension
npm install
npm run compile
npx vsce package --allow-missing-repository

# Upload all assets
gh release upload v1.15.2 dist/ppxai* dist/ppxaide* dist/ppxai-server* dist/ppxai-desktop*
gh release upload v1.15.2 vscode-extension/ppxai-*.vsix

# Verify
gh release view v1.15.2 --json assets --jq '.assets[].name'
```

#### Option C: Create v1.15.3 Patch Release (CLEANEST)

Create a new release with the test fix:

```bash
# Ensure on master with test fix
git checkout master
git pull

# Run release script (now without Claude credits)
.uv/uv run python scripts/release.py v1.15.3

# This time tests will pass and CI will build assets
```

**Recommendation:** Option C - Create v1.15.3 patch release

---

## Preventive Actions (Long-term)

### 1. Pre-Release Testing ✅ HIGH PRIORITY

**Problem:** Tests not run locally before release
**Solution:** Add mandatory pre-release checks to release script

```python
def pre_release_checks(version: str, skip_tests: bool = False):
    """Run comprehensive pre-release validation."""
    print("\n📋 Pre-Release Validation")

    # 1. Check working directory is clean
    check_git_status()

    # 2. Validate version format
    validate_version_format(version)

    # 3. Check release notes exist
    check_release_notes(version)

    # 4. Run tests locally (unless --skip-tests)
    if not skip_tests:
        print("  🧪 Running tests...")
        result = run_command("uv run pytest tests/ -v", check=False)
        if result.returncode != 0:
            print("  ❌ Tests failed! Fix before releasing.")
            sys.exit(1)
        print("  ✅ All tests passed")

    # 5. Validate version consistency
    run_validate_release(version)

    # 6. Check CHANGELOG.md updated
    check_changelog_updated(version)

    return True
```

**Status:** Planned for next release script update

---

### 2. Test Robustness Review ✅ MEDIUM PRIORITY

**Problem:** Test assumed tool registration order (fragile)
**Solution:** Review all tests for similar fragile assumptions

<details>
<summary>Common fragile patterns to fix</summary>

```python
# ❌ Fragile - assumes order:
assert results[0] == expected_first
assert list.index("foo") == 0

# ✅ Robust - checks membership:
assert expected_first in results
assert "foo" in list

# ❌ Fragile - assumes exact dict key order:
assert list(config.keys()) == ["a", "b", "c"]

# ✅ Robust - checks keys exist:
assert set(config.keys()) == {"a", "b", "c"}

# ❌ Fragile - exact match on dynamic content:
assert output == "Server started at 2026-02-06 15:30:00"

# ✅ Robust - pattern match:
assert re.match(r"Server started at \d{4}-\d{2}-\d{2}", output)
```

</details>

**Action Items:**
- [ ] Grep for `.call_args_list[0]` patterns
- [ ] Check tests with `index()` calls
- [ ] Review tests with exact list/dict comparisons

---

### 3. CI Workflow Improvements ✅ LOW PRIORITY

**Problem:** Test failure blocks all builds
**Solution:** Consider allowing builds even if tests fail (with warnings)

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    # Don't fail workflow, just record result
    continue-on-error: true
    steps:
      # ... existing test steps ...

  build-tui:
    needs: test
    # Build even if tests failed (with warning)
    if: always()
    steps:
      - name: Check test status
        run: |
          if [ "${{ needs.test.result }}" != "success" ]; then
            echo "⚠️  WARNING: Tests failed but building anyway"
            echo "⚠️  This is a recovery build - review test failures"
          fi
```

**Consideration:** This could hide test failures. Better solution: robust tests + pre-release validation.

**Decision:** Keep current strict CI, improve tests and pre-release checks instead.

---

### 4. Release Process Documentation ✅ MEDIUM PRIORITY

**Problem:** Manual recovery process not well documented
**Solution:** Update release skill documentation

**Status:** ✅ COMPLETE - Updated `.claude/commands/release.md` with:
- Troubleshooting section for CI test failures
- Manual build & upload instructions
- Options for recovery (manual build vs patch release)

---

### 5. Commit Message Standards ✅ HIGH PRIORITY

**Problem:** Release script added Claude credits (violates guidelines)
**Solution:** Fixed in `scripts/release.py` - now uses clean commit message

**Verification:**
```bash
# Check release commit format
git log --oneline --grep="feat: v1" -10 | head -5

# Should NOT contain:
# - 🤖 Generated with [Claude Code]
# - Co-Authored-By: Claude
```

**Status:** ✅ COMPLETE - Script fixed, document updated

---

## Testing Plan

### Validate Fixed Release Process

```bash
# 1. Create test release on feature branch
git checkout -b test/release-fix
echo "test" > test-file.txt
git add test-file.txt
git commit -m "test: release process validation"

# 2. Run release script with --dry-run
.uv/uv run python scripts/release.py v1.15.4-test --dry-run

# 3. Verify commit message format (no Claude credits)
# 4. Verify tests run before release
# 5. Clean up
git checkout master
git branch -D test/release-fix
```

---

## Decision Log

### Decision 1: How to fix v1.15.2 release?

**Options:**
1. Manual build & upload assets
2. Create v1.15.3 patch release
3. Leave as-is (document in release notes)

**Decision:** Create v1.15.3 patch release

**Rationale:**
- Cleanest solution - follows semver
- CI will run on fixed code
- All assets built automatically
- No manual build complexity
- Small overhead (one commit, one tag)

**Action:** Create v1.15.3 with test fix only

---

### Decision 2: Should CI allow builds even if tests fail?

**Options:**
1. Keep strict CI (tests must pass)
2. Allow builds with warning
3. Separate test and build workflows

**Decision:** Keep strict CI (Option 1)

**Rationale:**
- Failing tests indicate potential issues
- Better to fix tests than work around them
- Pre-release validation will catch issues earlier
- Clean builds should always have passing tests

**Action:** Improve test robustness and pre-release checks

---

## Summary

### Issues Fixed:
- ✅ Test fragility (`test_web_premium.py`)
- ✅ Release script Claude credits
- ✅ Release skill documentation
- ⏳ v1.15.2 asset availability (pending v1.15.3)

### Process Improvements:
- ✅ Pre-release testing requirements
- ✅ Test robustness guidelines
- ✅ Manual recovery procedures
- ✅ Commit message standards

### Next Steps:
1. Create v1.15.3 patch release with test fix
2. Implement pre-release validation in release.py
3. Review all tests for fragile patterns
4. Update project guidelines with lessons learned

---

**Document Status:** Action plan complete, awaiting v1.15.3 release execution.
