# Documentation Audit & Update Plan

**Audit Date:** 2025-12-18
**Current Versions:**
- Python Package: v1.10.2 (pyproject.toml)
- VSCode Extension: v1.10.3 (package.json)
- Latest Git Tag: v1.10.3 (Released 2025-12-18)

**v1.10.3 Focus:** Pre-built ppxai-server binaries for VSCode extension (no functional changes to Python package)

---

## Critical Issues (Fix Immediately)

### 1. **CLAUDE.md** - Outdated Version Reference
**Current:** Line 9 says "Current Version: v1.10.2 (URL Citations & System Prompts Fix)"
**Should Be:** "Current Version: v1.10.3 (Pre-built Server Binaries)"
**Impact:** High - This is the primary developer reference document
**Fix:**
```markdown
**Current Version:** v1.10.3 (Pre-built Server Binaries for VSCode Extension)
- Python package: v1.10.2
- VSCode extension: v1.10.3
- Pre-built ppxai-server binaries for all platforms
- GitHub Actions CI/CD for automated builds
```

### 2. **ROADMAP.md** - Severely Outdated
**Current:** Line 3 says "Current Release: v1.8.0"
**Should Be:** Updated to reflect v1.10.3
**Impact:** Critical - Users think project is 5 versions behind
**Fix:** Add v1.9.x, v1.10.x releases to the top of the file

### 3. **GEMINI.md** - Outdated Version
**Current:** Line 66 says "Version: ~v1.8.0"
**Should Be:** "Version: v1.10.3"
**Impact:** Medium - This is Gemini-specific setup documentation
**Consider:** This file might be obsolete since Gemini is now a built-in provider

---

## Medium Priority Issues

### 4. **README.md** - Missing v1.10.3 Release Notes
**Current:** Option 2 mentions standalone server but doesn't emphasize it's new in v1.10.3
**Should Add:** Clear callout that v1.10.3 introduced standalone server binaries
**Impact:** Medium - Users might not know this is a recent improvement

### 5. **RELEASE.md** - Incomplete Server Binary Instructions
**Current:** Mentions server binaries briefly (lines 40-43)
**Should Add:** More detail about:
- Server binary build process in CI/CD
- Naming convention (`ppxai-server-{platform}`)
- Test procedure for server binaries
**Impact:** Medium - Important for future releases

---

## Low Priority / Documentation Cleanup

### 6. **Obsolete/Legacy Files** - Consider Archiving

| File | Issue | Recommendation |
|:-----|:------|:---------------|
| **INTEGRATION_COMPLETE.md** | Legacy tool integration docs | Move to `docs/archive/` |
| **SHELL_COMMAND_FEATURE.md** | Feature-specific doc from Nov 29 | Move to `docs/archive/` or remove (feature is documented elsewhere) |
| **SSL_FIX_SUMMARY.md** | One-time SSL fix documentation | Move to `docs/archive/` |
| **TESTING_RESULTS.md** | Historical test results | Move to `docs/archive/` |
| **TEST_FIXES_SUMMARY.md** | Historical test fix notes | Move to `docs/archive/` |
| **docs/TOOL_INTEGRATION_COMPLETE.md** | Duplicate of root file | Remove |
| **docs/INTEGRATION_SUMMARY.md** | Legacy integration docs | Archive or consolidate into main tool docs |

### 7. **pyproject.toml** - Python Package Version
**Current:** version = "1.10.2"
**Should Consider:** Bump to v1.10.3 to align with git tag, OR
**Alternative:** Keep at v1.10.2 since no functional Python package changes
**Recommendation:** Keep at v1.10.2 for now, but document the version strategy

---

## Documentation Strategy Alignment

### Version Numbering Strategy (Needs Clarification)

Currently there's confusion between:
- **Git tags** (v1.10.3 - for releases)
- **Python package version** (v1.10.2 in pyproject.toml)
- **VSCode extension version** (v1.10.3 in package.json)

**Recommended Strategy:**
1. **Python package** (pyproject.toml): Bump only for functional changes to ppxai TUI/engine
2. **VSCode extension** (package.json): Bump for extension changes
3. **Git tags**: Bump for any release (extension OR package changes)

**Document this in RELEASE.md** under a "Version Strategy" section.

---

## Roadmap Document Conflicts

### Current Situation
We have **three** roadmap documents with overlapping content:

| File | Focus | Status | Version Range |
|:-----|:------|:-------|:--------------|
| **ROADMAP.md** | Historical releases | ❌ Outdated (v1.8.0) | v1.0.0 - v1.8.0 |
| **gemini3-features-roadmap.md** | Agentic features | ✅ Updated (v1.10.3) | v1.10.4 - v1.13.0 |
| **sonar-features-proposal.md** | Competitive analysis | ✅ Updated (v1.10.3) | Current + future |
| **docs/tui-markdown-rendering.md** | TUI workspace vision | ✅ Updated (v1.10.3) | v1.10.4 - v1.15.0 |

### Recommendation: Consolidate Roadmap Strategy

**Option 1: Keep Separate (Recommended)**
- `ROADMAP.md` → Historical changelog (rename to `CHANGELOG.md`?)
- `gemini3-features-roadmap.md` → Agentic features (v1.11.0+)
- `docs/tui-markdown-rendering.md` → TUI/Workspace roadmap
- Add a **master roadmap index** at the top of README.md

**Option 2: Consolidate**
- Merge all into one `ROADMAP.md`
- Risk: Document becomes too large and unfocused

---

## Action Plan (Prioritized)

### Immediate (Before Next Release)

1. **✅ Update CLAUDE.md**
   - Change version to v1.10.3
   - Add clarification about Python package vs extension versioning
   - Estimated time: 5 minutes

2. **✅ Update ROADMAP.md**
   - Add v1.9.0, v1.10.0, v1.10.1, v1.10.2, v1.10.3 sections
   - Link to detailed roadmaps for future (gemini3-features-roadmap.md, tui-markdown-rendering.md)
   - Estimated time: 20 minutes

3. **✅ Update or Archive GEMINI.md**
   - Either update to v1.10.3, OR
   - Archive if Gemini setup is now handled by standard multi-provider docs
   - Estimated time: 10 minutes

4. **✅ Update README.md**
   - Add "NEW in v1.10.3" callout for server binaries
   - Add link to roadmap documents
   - Estimated time: 10 minutes

### Near-Term (Next 1-2 Weeks)

5. **Create docs/archive/ directory**
   - Move legacy documents
   - Add archive/README.md explaining what's archived
   - Estimated time: 15 minutes

6. **Update RELEASE.md**
   - Add "Version Strategy" section
   - Expand server binary release instructions
   - Add checklist for v1.10.4 specific to server+extension combo
   - Estimated time: 30 minutes

7. **Create CONTRIBUTING.md improvements**
   - Link to all relevant docs
   - Explain which roadmap to consult for which topic
   - Estimated time: 20 minutes

### Long-Term (Next Month)

8. **Version Alignment Discussion**
   - Decide whether to align pyproject.toml with git tags
   - Document decision in RELEASE.md
   - Update all docs to reflect decision
   - Estimated time: 1-2 hours (includes team discussion)

---

## Files That Are Correct (No Action Needed)

✅ **vscode-extension/README.md** - Already updated to v1.10.3
✅ **gemini3-features-roadmap.md** - Updated to v1.10.3
✅ **sonar-features-proposal.md** - Updated to v1.10.3
✅ **docs/tui-markdown-rendering.md** - Updated to v1.10.3
✅ **BUILD.md** - Up to date
✅ **docs/README.md** - Tool docs are current
✅ **SECURITY.md** - Version-agnostic, still valid
✅ **CODE_OF_CONDUCT.md** - Version-agnostic

---

## Summary of Recommended Changes

**Immediate fixes (< 1 hour):**
- Update CLAUDE.md, ROADMAP.md, GEMINI.md, README.md with v1.10.3 info

**Cleanup (< 1 hour):**
- Archive 6 legacy files to docs/archive/
- Add archive/README.md

**Strategy documentation (2 hours):**
- Document version numbering strategy in RELEASE.md
- Create roadmap index in README.md
- Update CONTRIBUTING.md

**Total estimated effort:** 4 hours

---

## Proposed File Structure After Cleanup

```
ppxai/
├── README.md                          [✅ Updated] Main entry point
├── CLAUDE.md                          [✅ Updated] Developer guide
├── BUILD.md                           [✅ Current] Build instructions
├── RELEASE.md                         [✅ Updated] Release process + version strategy
├── ROADMAP.md                         [✅ Updated] Historical + links to future roadmaps
├── CONTRIBUTING.md                    [✅ Updated] Contribution guide
├── SECURITY.md                        [✅ Current] Security policy
├── CODE_OF_CONDUCT.md                 [✅ Current] Code of conduct
├── SPECIFICATIONS.md                  [✅ Current] Spec writing guide
├── GEMINI.md                          [❓ Review] Gemini setup (might be obsolete)
│
├── gemini3-features-roadmap.md        [✅ Updated] Agentic roadmap (v1.11.0-v1.13.0)
├── sonar-features-proposal.md         [✅ Updated] Competitive analysis
│
├── docs/
│   ├── README.md                      [✅ Current] Tool documentation index
│   ├── tui-markdown-rendering.md      [✅ Updated] TUI workspace vision (v1.10.4-v1.15.0)
│   ├── PROVIDER_SETUP.md              [✅ Current] Provider configuration
│   ├── TOOL_CREATION_GUIDE.md         [✅ Current] Creating custom tools
│   ├── ... [other current docs]
│   │
│   └── archive/                       [🆕 NEW] Historical documentation
│       ├── README.md                  [🆕 NEW] Explains archived docs
│       ├── INTEGRATION_COMPLETE.md
│       ├── SHELL_COMMAND_FEATURE.md
│       ├── SSL_FIX_SUMMARY.md
│       ├── TESTING_RESULTS.md
│       ├── TEST_FIXES_SUMMARY.md
│       └── TOOL_INTEGRATION_COMPLETE.md
│
└── tests/
    └── TEST_SUMMARY.md                [✅ Current] Test documentation
```

---

## Next Steps

1. Review this audit
2. Approve action plan
3. Execute immediate fixes
4. Schedule cleanup and strategy work
5. Update this audit document with completion status
