# Release Plan: v1.11.x Series

**Date**: 2025-12-22
**Status**: In Progress
**Strategy**: Incremental releases with focused scope

---

## Overview

The v1.11.x series delivers critical bug fixes, refactoring for code sharing, and agentic workflow features through three focused releases.

---

## Release Schedule

### v1.11.1 - TUI Bugfix Release ✅ READY TO RELEASE

**Date**: 2025-12-22 (TODAY)
**Type**: Patch (Bugfix)
**Status**: Ready for release
**Priority**: High

**Scope**:
- ✅ Fix 400 message alternation error (critical TUI regression)
- ✅ TUI debug logging system (`/debug-log` command)
- ✅ Multi-turn conversations with tools work correctly
- ✅ 7 new tests for conversation history
- ✅ 303/308 tests passing (98.4%)

**Documentation**:
- [RELEASE-NOTES-v1.11.1.md](RELEASE-NOTES-v1.11.1.md)
- [400-ERROR-INVESTIGATION.md](400-ERROR-INVESTIGATION.md)
- [TUI-DEBUG-LOGGING.md](TUI-DEBUG-LOGGING.md)

**Upgrade Impact**: Drop-in replacement, no breaking changes

**Next Steps**:
1. ✅ Version bumped to 1.11.1
2. ⏳ Run final test suite
3. ⏳ Commit and tag
4. ⏳ Push to GitHub
5. ⏳ Create GitHub release
6. ⏳ Publish to PyPI

---

### v1.11.2 - Shared Modules Architecture ✅ RELEASED

**Date**: 2025-12-22
**Type**: Minor (Shell Consent Security + Refactoring)
**Status**: Released
**Priority**: High

**Scope**:
- Create `ppxai/common/` module with shared logic
- Implement `event_handler.py` - Shared event processing
- Implement `logger.py` - Unified logging (replaces `tui_logger.py`)
- Update TUI to use shared modules
- Update HTTP server to use shared logger (VSCode adapter)
- **Both TUI and VSCode extension work** with shared code

**Deliverables**:
- ✅ Event handler with tests (2-3h)
- ✅ Logger with tests (1-2h)
- ✅ VSCode server integration (1-2h)
- ✅ TUI integration (1-2h)
- ✅ Testing both clients (1h)
- **Total**: 6-9 hours

**Documentation**:
- [PHASE1-SHARED-MODULES-IMPLEMENTATION.md](PHASE1-SHARED-MODULES-IMPLEMENTATION.md)
- [PHASE1-VSCODE-ADAPTER.md](PHASE1-VSCODE-ADAPTER.md)
- [REFACTORING-PLAN-SHARED-MODULES.md](REFACTORING-PLAN-SHARED-MODULES.md)

**Upgrade Impact**: Drop-in replacement, backward compatible

**Success Criteria**:
- All existing tests pass (303/308 or better)
- TUI works with shared modules (no 400 errors)
- VSCode extension works with shared logger
- Consistent logging across both clients

**Dependencies**: None (v1.11.1 released)

---

### v1.11.3 - Agentic Workflow Phase 2 ⏳ PLANNED

**Date**: TBD (Target: Early January 2026)
**Type**: Minor (New Features)
**Status**: Design phase
**Priority**: Medium

**Scope**:
- Implement `@git` context provider (git diff injection)
- Implement `@tree` context provider (project structure awareness)
- Enhanced file awareness for AI
- Foundation for `/agent` command (multi-step tasks)

**Estimated Effort**: 4-6 hours for Phase 2 context providers

**Documentation**:
- [docs/v1.11.0-agentic-workflow-plan.md](v1.11.0-agentic-workflow-plan.md) - See Phases 2-3
- [gemini3-features-roadmap.md](../gemini3-features-roadmap.md)

**Upgrade Impact**: New features, backward compatible

**Dependencies**: v1.11.2 (shared modules provide foundation)

---

## Strategic Rationale

### Why Three Releases?

**Risk Mitigation**:
- Each release has focused, testable scope
- Easier to isolate and fix issues
- Users get critical fixes quickly

**Development Workflow**:
- v1.11.1: Immediate fix for broken TUI (1 hour)
- v1.11.2: Foundation for future (6-9 hours)
- v1.11.3: New capabilities (4-6 hours)

**User Impact**:
- v1.11.1: Fixes critical regression → Release immediately
- v1.11.2: Internal refactoring → No visible changes
- v1.11.3: New agentic features → Visible improvements

---

## Version Comparison

| Release | Type | Scope | Effort | User Impact | Tests |
|---------|------|-------|--------|-------------|-------|
| v1.11.1 | Patch | TUI bugfix + logging | 1h | High (fixes regression) | 303/308 |
| v1.11.2 | Minor | Shared modules | 6-9h | Low (internal) | 303+ |
| v1.11.3 | Minor | @git/@tree context | 4-6h | High (new features) | TBD |

---

## After v1.11.3

### v1.11.4+ - Future Agentic Features

**Potential Features**:
- `/agent` command (autonomous multi-step tasks)
- Enhanced tool orchestration
- Additional context providers
- MCP server integration improvements

**Timeline**: TBD based on user feedback and priorities

---

## Communication Plan

### For v1.11.1 (Immediate):

**GitHub Release**:
- Title: "v1.11.1 - Critical TUI Bugfix + Debug Logging"
- Body: [RELEASE-NOTES-v1.11.1.md](RELEASE-NOTES-v1.11.1.md)
- Assets: None (PyPI only)

**PyPI**:
- Publish as patch release
- Update project description

**Announcement**:
- Twitter/X: "v1.11.1 released - fixes TUI tools regression + adds debug logging"
- Discord: Post in #announcements

**Migration Guide**:
- Simple: `pip install --upgrade ppxai`
- No configuration changes needed

### For v1.11.2 (Future):

**Focus**: Internal improvements, code quality
**Message**: "Foundation for future agentic features"

### For v1.11.3 (Future):

**Focus**: New agentic capabilities
**Message**: "@git and @tree context providers - AI with project awareness"

---

## Quality Gates

### Before Each Release:

1. **Tests Pass**: All or >98% tests passing
2. **No Regressions**: Manual testing of core features
3. **Documentation**: Release notes + updated docs
4. **Version Alignment**: Python, VSCode, pyproject.toml all match
5. **Changelog**: Updated CHANGELOG.md

### Specific to v1.11.1:

- [x] 303/308 tests passing
- [x] TUI multi-turn conversations work
- [x] Debug logging works
- [x] Release notes written
- [ ] Final test run
- [ ] Git tag created
- [ ] GitHub release created
- [ ] PyPI published

---

## Rollback Plan

### If v1.11.1 Has Issues:

**Immediate**:
- Document issue in GitHub
- Users can downgrade: `pip install ppxai==1.11.0`

**Follow-up**:
- Fix in v1.11.1.1 (patch)
- Or roll forward to v1.11.2 with fix

### Prevention:

- Thorough testing before each release
- User feedback collection
- Monitor GitHub issues

---

## Success Metrics

### v1.11.1:

- ✅ No new GitHub issues about 400 errors
- ✅ Users report tools working in TUI
- ✅ Debug logging helps troubleshooting

### v1.11.2:

- Both TUI and VSCode work correctly
- No performance regression
- Code complexity reduced (shared modules)

### v1.11.3:

- Users use @git/@tree context providers
- Positive feedback on agentic features
- Foundation for more advanced features

---

**Last Updated**: 2025-12-22
**Current Release**: v1.11.2 (released 2025-12-22)
**Next Release**: v1.11.3+ (agentic workflow Phases 2-6)
