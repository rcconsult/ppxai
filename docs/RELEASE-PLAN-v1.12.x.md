# Release Plan: v1.12.x Series

**Created:** December 29, 2025
**Last Updated:** December 29, 2025
**Status:** In Progress
**Branch:** `feature/agent-multi-file-atomic-edit`

---

## Overview

This document outlines the release plan for the v1.12.x series, focusing on:
1. Checkpoint system with stale detection (DONE)
2. Real-time token usage and cost tracking (DONE)
3. Per-provider/model usage breakdown (TODO)
4. Dedicated Gemini provider for native features (PLANNED)

---

## v1.12.0 - Checkpoint System & Usage Tracking

**Status:** Ready for Release (all blockers resolved)
**Target:** Immediate

### Features Complete

#### Checkpoint System
- [x] Git-based checkpoints (auto-commit before agent tasks)
- [x] File-based checkpoints (fallback when no git)
- [x] `/undo` command for atomic rollback
- [x] Auto-commit after successful agent tasks
- [x] `EventType.STATUS` for checkpoint notifications
- [x] HTTP endpoints: `/checkpoint/status`, `/checkpoint/undo`
- [x] VSCode Undo button with confirmation dialog
- [x] Collapsible tool messages with verbose mode

#### Checkpoint Stale State Detection (FIXED)
- [x] `is_checkpoint_valid()` checks if checkpoint is HEAD or HEAD~1
- [x] Auto-invalidate stale checkpoints in `get_checkpoint_status()`
- [x] HTTP endpoint rejects undo on stale checkpoints (400 error)
- [x] TUI `/undo` checks validity before reverting
- [x] VSCode Undo button disabled (red) when stale
- [x] 12 new stale detection tests (40 checkpoint tests total)

#### Token Usage & Cost Tracking (FIXED)
- [x] Streaming usage extraction (`stream_options={"include_usage": True}`)
- [x] Cost calculation based on per-model pricing
- [x] Session usage accumulation
- [x] TUI status line shows `1.2K↓/0.5K↑ $0.0045`
- [x] VSCode usage badge with live updates
- [x] `/usage` command shows session stats
- [x] Works with tools/agent mode (accumulated across iterations)
- [x] Fallback for APIs that don't support `stream_options`
- [x] Self-hosted LLMs: tokens tracked, cost = $0.00

#### Bug Fixes
- [x] `provider_id` → `provider_name` attribute error
- [x] `UsageStats` JSON serialization (use `asdict()`)
- [x] Usage tracking in `_chat_with_tools()` (was missing)

### Tests
- 377 tests passing (12 new checkpoint tests)

---

## v1.12.1 - Usage Analytics & Cost Breakdown

**Status:** Proposed
**Target:** 1-2 days after v1.12.0

### Motivation

Current usage tracking shows only aggregated totals:
```json
{"total_tokens": 1298, "prompt_tokens": 1143, "completion_tokens": 155, "estimated_cost": 0.005754}
```

This is misleading when users switch between providers/models in a session. Different models have vastly different pricing (e.g., sonar: $0.20/M vs sonar-pro: $3.00/M input).

Users also need to track spending over time to budget their API costs effectively.

### Proposed Implementation

#### 1. Session Storage Change

**Current:**
```python
self.usage = UsageStats(...)  # Single aggregate
```

**Proposed:**
```python
self.usage_by_model: Dict[str, UsageStats] = {}  # Key: "provider/model"
# Example keys: "perplexity/sonar-pro", "gemini/gemini-2.0-flash"
```

#### 2. Update `update_usage()` Signature

```python
def update_usage(self, usage: UsageStats, provider: str, model: str):
    key = f"{provider}/{model}"
    if key not in self.usage_by_model:
        self.usage_by_model[key] = UsageStats()

    self.usage_by_model[key].prompt_tokens += usage.prompt_tokens
    self.usage_by_model[key].completion_tokens += usage.completion_tokens
    self.usage_by_model[key].total_tokens += usage.total_tokens
    self.usage_by_model[key].estimated_cost += usage.estimated_cost
```

#### 3. Update `get_usage()` Response

```python
def get_usage(self) -> Dict[str, Any]:
    # Calculate totals
    totals = UsageStats()
    for usage in self.usage_by_model.values():
        totals.prompt_tokens += usage.prompt_tokens
        # ... etc

    return {
        "by_model": {
            key: asdict(usage)
            for key, usage in self.usage_by_model.items()
        },
        "totals": asdict(totals)
    }
```

#### 4. TUI `/usage` Display

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                     Session Usage Statistics                      ┃
┣━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┫
┃ Provider     ┃ Model              ┃ In      ┃ Out     ┃ Cost     ┃
┣━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━╋━━━━━━━━━╋━━━━━━━━━━┫
┃ perplexity   ┃ sonar-pro          ┃ 1,143   ┃ 155     ┃ $0.0058  ┃
┃ gemini       ┃ gemini-2.0-flash   ┃ 101     ┃ 3       ┃ $0.0000  ┃
┣━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━╋━━━━━━━━━╋━━━━━━━━━━┫
┃ TOTAL        ┃                    ┃ 1,244   ┃ 158     ┃ $0.0058  ┃
┗━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━┻━━━━━━━━━┻━━━━━━━━━━┛
```

#### 5. VSCode Extension Usage Tooltip

Hover over usage badge shows breakdown instead of just totals.

#### 6. Status Line (No Change)

Keep showing session totals in status line (space constrained):
```
[Perplexity | sonar-pro | Tools: ON | 1.2K↓/0.5K↑ $0.0058]
```

### Part B: Time-Based Cost Aggregation

#### 1. Persistent Usage Storage

**New File:** `~/.ppxai/usage/usage.json`

```json
{
  "version": 1,
  "sessions": [
    {
      "session_id": "abc123",
      "session_name": "chat-2025-12-29-1430",
      "started_at": "2025-12-29T14:30:00Z",
      "ended_at": "2025-12-29T15:45:00Z",
      "usage_by_model": {
        "perplexity/sonar-pro": {"prompt_tokens": 1143, "completion_tokens": 155, "estimated_cost": 0.0058},
        "gemini/gemini-2.0-flash": {"prompt_tokens": 500, "completion_tokens": 50, "estimated_cost": 0.0001}
      },
      "total_cost": 0.0059
    }
  ]
}
```

#### 2. Time-Based Aggregation

```python
def get_usage_report(period: str = "all") -> Dict[str, Any]:
    """Get usage aggregated by time period.

    Args:
        period: "session" | "24h" | "week" | "month" | "year" | "all"
    """
    now = datetime.now(UTC)
    cutoff = {
        "24h": now - timedelta(hours=24),
        "week": now - timedelta(weeks=1),
        "month": now - timedelta(days=30),
        "year": now - timedelta(days=365),
        "all": datetime.min,
    }.get(period, datetime.min)

    # Filter sessions by cutoff
    sessions = [s for s in usage_data["sessions"] if s["started_at"] >= cutoff]

    return {
        "period": period,
        "session_count": len(sessions),
        "by_model": aggregate_by_model(sessions),
        "by_session": [summarize_session(s) for s in sessions],
        "totals": aggregate_totals(sessions)
    }
```

#### 3. TUI `/usage` Command Enhancement

```
/usage              # Current session (default)
/usage 24h          # Last 24 hours
/usage week         # Last 7 days
/usage month        # Last 30 days
/usage year         # Last 365 days
/usage all          # All time
```

**Example Output:**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                    Usage Report: Last 7 Days                              ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ Sessions: 12 | Period: Dec 22 - Dec 29, 2025                              ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃                                                                           ┃
┃ BY PROVIDER/MODEL:                                                        ┃
┣━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━┫
┃ Provider     ┃ Model                ┃ Tokens   ┃ Requests ┃ Cost         ┃
┣━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━━━━━┫
┃ perplexity   ┃ sonar-reasoning-pro  ┃ 45,230   ┃ 8        ┃ $0.2261      ┃
┃ perplexity   ┃ sonar-pro            ┃ 12,500   ┃ 15       ┃ $0.0500      ┃
┃ gemini       ┃ gemini-2.0-flash     ┃ 8,000    ┃ 10       ┃ $0.0016      ┃
┣━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━━━━━┫
┃ TOTAL        ┃                      ┃ 65,730   ┃ 33       ┃ $0.2777      ┃
┗━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━━━━━━━┛
┃                                                                           ┃
┃ BY SESSION:                                                               ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┫
┃ Session                    ┃ Date         ┃ Messages ┃ Cost              ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━┫
┃ chat-2025-12-29-2134       ┃ Dec 29 21:34 ┃ 12       ┃ $0.1579           ┃
┃ chat-2025-12-29-1430       ┃ Dec 29 14:30 ┃ 8        ┃ $0.0505           ┃
┃ chat-2025-12-28-0900       ┃ Dec 28 09:00 ┃ 25       ┃ $0.0693           ┃
┃ ... (9 more sessions)      ┃              ┃          ┃                   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━┛
```

#### 4. VSCode Extension Dashboard

New command: `ppxai.openUsageDashboard`

- Shows usage breakdown in a dedicated webview
- Interactive charts (bar chart by model, line chart over time)
- Period selector: 24h | Week | Month | Year | All
- Export to CSV option

#### 5. HTTP Endpoints

```
GET /usage                    # Current session
GET /usage/report?period=week # Time-based report
GET /usage/sessions           # List all sessions with usage
GET /usage/export?format=csv  # Export usage data
```

### Files to Modify

| File | Changes |
|------|---------|
| `ppxai/engine/session.py` | Add `usage_by_model`, update methods |
| `ppxai/engine/client.py` | Pass provider/model to `update_usage()` |
| `ppxai/engine/types.py` | No change (UsageStats stays same) |
| `ppxai/ui.py` | Update `display_usage()` for breakdown table |
| `ppxai/server/http.py` | Update `/usage` endpoint response |
| `vscode-extension/src/chatPanel.ts` | Update usage tooltip |
| `tests/test_session.py` | Add per-model usage tests |
| **NEW** `ppxai/usage.py` | Persistent usage storage and aggregation |
| **NEW** `ppxai/commands.py` | Enhanced `/usage` with period argument |
| **NEW** `vscode-extension/src/usageDashboard.ts` | Usage dashboard webview |

### Effort Estimate

**Part A: Per-Model Breakdown**
- Implementation: 2-3 hours
- Testing: 1 hour
- Subtotal: 3-4 hours

**Part B: Time-Based Aggregation**
- Persistent storage: 2 hours
- Aggregation logic: 2 hours
- TUI enhancements: 2 hours
- VSCode dashboard: 4-6 hours
- HTTP endpoints: 2 hours
- Testing: 2 hours
- Subtotal: 14-16 hours

**Total: 17-20 hours (split across v1.12.1 and v1.12.2)**

### Phased Rollout

| Version | Features |
|---------|----------|
| v1.12.1 | Part A: Per-model breakdown (current session only) |
| v1.12.2 | Part B: Time-based aggregation, persistent storage, `/usage <period>` |
| v1.12.3 | VSCode dashboard webview, CSV export |

---

## v1.12.2 - Time-Based Usage Analytics

**Status:** Planned
**Target:** 3-5 days after v1.12.1

### Features

#### Persistent Usage Storage
- [ ] `~/.ppxai/usage/usage.json` - Session history with costs
- [ ] Auto-save session usage on exit/new session
- [ ] Migration from session-only tracking

#### Time-Based Aggregation
- [ ] `/usage 24h` - Last 24 hours spending
- [ ] `/usage week` - Last 7 days spending
- [ ] `/usage month` - Last 30 days spending
- [ ] `/usage year` - Last 365 days spending
- [ ] `/usage all` - All-time spending

#### HTTP Endpoints
- [ ] `GET /usage/report?period=week` - Time-based report
- [ ] `GET /usage/sessions` - List sessions with costs
- [ ] `GET /usage/export?format=csv` - Export for spreadsheets

### Bug Fixes (TBD based on feedback)
- [ ] Checkpoint edge cases discovered in production
- [ ] Usage tracking accuracy issues
- [ ] VSCode extension UI glitches

---

## v1.12.3 - Gemini Dedicated Provider

**Status:** Planned
**Target:** 2-3 weeks after v1.12.2

### Motivation

Currently Gemini uses the generic `OpenAICompatibleProvider`. A dedicated provider enables:

| Feature | Generic OpenAI | Dedicated Gemini |
|---------|---------------|------------------|
| Search Grounding | N/A | Real-time web search |
| Safety Settings | N/A | Configurable thresholds |
| Code Execution | N/A | Native Python sandbox |
| System Instructions | Merged into messages | Proper `system_instruction` field |
| Caching | N/A | Context caching for cost reduction |
| Multimodal | Basic | Native image/video/audio |

### What is Search Grounding?

Gemini's Search Grounding connects the model to Google Search in real-time:
- Model can retrieve up-to-date information during generation
- Returns grounding sources (citations) with responses
- Similar to Perplexity's native web search capability
- Reduces hallucination for factual queries

**When enabled:**
```
User: "What's the weather in Tokyo today?"
Gemini: "According to current data, Tokyo is 12°C with partly cloudy skies [1]"
        Sources: [1] weather.google.com
```

### Implementation Plan

**New File:** `ppxai/engine/providers/gemini.py`

### Features to Implement

| Feature | Priority | Effort |
|---------|----------|--------|
| Basic chat with native SDK | High | 2-3 hrs |
| Streaming responses | High | 1-2 hrs |
| Usage/token tracking | High | 1 hr |
| Search grounding | High | 2-3 hrs |
| Grounding source citations | High | 1-2 hrs |
| System instruction handling | Medium | 1 hr |
| Safety settings config | Medium | 1-2 hrs |
| Context caching | Low | 3-4 hrs |
| Code execution | Low | 4-6 hrs |

**Total Effort:** 12-20 hours

### Dependencies

```toml
# pyproject.toml - new optional dependency
[project.optional-dependencies]
gemini = ["google-generativeai>=0.8.0"]
```

---

## v1.12.4 - Gemini Bug Fixes

**Status:** Planned
**Target:** 1-2 weeks after v1.12.3

### Anticipated Issues
- [ ] Grounding response format changes
- [ ] Rate limiting handling
- [ ] Safety settings edge cases
- [ ] Token counting discrepancies

---

## Future Considerations (v1.13+)

### Claude/Anthropic Dedicated Provider

**Priority:** Low (ppxai is not competing with Claude Code)

| Feature | Value for ppxai |
|---------|-----------------|
| Prompt caching | Up to 90% cost reduction |
| Extended thinking | Chain-of-thought visibility |
| Native tool use | Better tool calling format |

### AGENTS.md Support

As planned in ROADMAP.md:
- Load project context on startup
- File precedence (global → project → subdirectory)
- `/agents show`, `/agents reload`, `/agents edit` commands

---

## Release Checklist Template

For each release:

- [ ] All tests passing (377+ tests)
- [ ] Update version in:
  - [ ] `pyproject.toml`
  - [ ] `vscode-extension/package.json`
  - [ ] `ppxai/__init__.py`
  - [ ] `CLAUDE.md`
  - [ ] `ROADMAP.md`
- [ ] Create release notes: `docs/RELEASE-NOTES-v{version}.md`
- [ ] Run `/release v{version}` skill
- [ ] Verify CI builds pass
- [ ] Verify GitHub release marked as "Latest"
- [ ] Test TUI and VSCode extension manually
- [ ] Update documentation if needed

---

## Timeline Summary

```
Current:     v1.11.9 (released 2025-12-27)
             │
             ▼
Ready:       v1.12.0 (checkpoint + usage) ◄── NOW READY
             │  ✅ Checkpoint stale detection FIXED
             │  ✅ Usage tracking bugs FIXED
             │  ✅ Concurrent request protection FIXED
             ▼
Proposed:    v1.12.1 (per-model usage breakdown) ──────── 1-2 days
             │  • Track usage by provider/model
             │  • Table display in /usage
             │  • VSCode tooltip breakdown
             ▼
Planned:     v1.12.2 (time-based usage analytics) ─────── 3-5 days
             │  • Persistent usage storage
             │  • /usage 24h|week|month|year|all
             │  • Session history with costs
             │  • CSV export endpoint
             ▼
Planned:     v1.12.3 (VSCode dashboard + Gemini) ──────── 2-3 weeks
             │  • Usage dashboard webview
             │  • Interactive charts
             │  • Gemini dedicated provider
             ▼
Planned:     v1.12.4 (bug fixes) ──────────────────────── 1-2 weeks
             │
             ▼
Future:      v1.13.0 (AGENTS.md)
```

---

## Summary of Changes in This Session

### Completed Today (Dec 29, 2025)

1. **Checkpoint Stale Detection** - CRITICAL bug fixed
   - `is_checkpoint_valid()` in checkpoint backends
   - Auto-invalidation in `get_checkpoint_status()`
   - TUI and VSCode protection against stale undo
   - 12 new tests

2. **Usage Tracking Bugs** - FIXED
   - `provider_id` → `provider_name` typo
   - `UsageStats` JSON serialization
   - Usage tracking in `_chat_with_tools()` (was completely missing)
   - `stream_options` fallback for vLLM/Ollama
   - VSCode usage badge now updates after each response

3. **UI Improvements**
   - TUI status line: checkpoint ID with validity colors
   - VSCode Undo button: grey/blue/red based on state
   - VSCode table CSS: horizontal scroll for wide tables

4. **Concurrent Request Protection** - NEW
   - VSCode input disabled during streaming/consent
   - Session cleanup on 400 message alternation errors
   - Prevents accidental duplicate messages

5. **Context Injection Fix** - NEW
   - `@tree` and `@git` now work correctly in VSCode extension
   - Previously treated as file search instead of context providers

### Proposed for v1.12.1

6. **Per-Model Usage Breakdown**
   - Track usage by `{provider}/{model}` key
   - Table display in `/usage` command
   - Detailed tooltip in VSCode

### Proposed for v1.12.2

7. **Time-Based Usage Analytics**
   - Persistent storage in `~/.ppxai/usage/usage.json`
   - `/usage 24h|week|month|year|all` commands
   - Session history with cost breakdown
   - CSV export for budgeting

---

## v1.12.0 Release Checklist

**Pre-Release Verification** (on feature branch)
```bash
# 1. Verify all changes are committed
git status  # Should be clean or have only expected changes

# 2. Run tests
uv run pytest tests/ -v

# 3. Verify release notes are complete (not template)
cat docs/RELEASE-NOTES-v1.12.0.md | grep -c "\[Brief description"  # Should be 0

# 4. Verify validation passes (dry run)
python scripts/validate-release.py v1.12.0
```

**Merge Feature Branch to Master**
```bash
# 1. Ensure on feature branch
git checkout feature/agent-multi-file-atomic-edit

# 2. Fast-forward merge to master
git checkout master
git merge feature/agent-multi-file-atomic-edit --ff-only

# 3. Verify merge succeeded
git log --oneline -5  # Should show feature commits
```

**Execute Release**
```bash
# Option 1: Use /release skill (RECOMMENDED)
/release v1.12.0

# Option 2: Run script directly
python scripts/release.py v1.12.0
```

**Post-Release Verification**
```bash
# Verify on GitHub
# 1. Check release: https://github.com/rcconsult/ppxai/releases/tag/v1.12.0
# 2. Verify assets: 7 binaries + 1 VSIX
# 3. Verify release notes are populated
# 4. Verify marked as "Latest"
```

**Rollback (if needed)**
```bash
# Delete release and redo from scratch
python scripts/release.py v1.12.0 --redo --force
```

---

**Last Updated:** December 29, 2025
