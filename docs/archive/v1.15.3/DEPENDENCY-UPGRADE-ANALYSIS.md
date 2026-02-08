# Dependency Upgrade Analysis (v1.15.3)

**Date:** 2026-02-08
**Current Environment:** Python 3.12.3
**Purpose:** Pre-Gemini tuning dependency review

---

## Executive Summary

**Total Outdated Packages:** 28 out of 130 (21.5%)

**Recommended Action:** **UPGRADE BEFORE GEMINI BENCHMARKS**

### Critical Upgrades
- **google-genai:** 1.56.0 → 1.62.0 (6 versions behind, Gemini provider)
- **google-ai-generativelanguage:** 0.6.15 → 0.10.0 (API layer)
- **protobuf:** 5.29.6 → 6.33.5 (major version, minimal breaking changes)

### High Priority
- **openai:** 2.11.0 → 2.17.0 (Perplexity + OpenAI-compat providers)
- **fastapi:** 0.124.4 → 0.128.5 (HTTP server)
- **starlette:** 0.50.0 → 0.52.1 (FastAPI dependency)
- **uvicorn:** 0.38.0 → 0.40.0 (server runtime)

### Medium Priority
- **textual:** 7.4.0 → 7.5.0 (TUI framework - ppxaide)
- **rich:** 14.2.0 → 14.3.2 (CLI rendering)
- **ruff:** 0.14.9 → 0.15.0 (linter)

---

## Detailed Analysis

### 1. Gemini Provider Stack

#### google-genai (1.56.0 → 1.62.0)

**Impact:** HIGH
**Risk:** LOW
**Recommendation:** UPGRADE

**Changes (as reviewed earlier):**
- v1.57.0: Removed validation on empty text parts (helpful for edge cases)
- v1.58.0: FileSearchCallContent, ImageConfig, voice activity detection
- v1.59.0: Environment variable token control, aspect ratio support
- v1.60.0: ModelArmorConfig for sanitization
- v1.61.0: Enhanced metadata in batch responses
- v1.62.0: Error handling improvements for live/music APIs

**Benefits:**
- Better edge case handling in tool responses (v1.57.0)
- Improved metadata (v1.61.0)
- General stability improvements

**No function calling bug fixes**, but good for maintenance.

---

#### google-ai-generativelanguage (0.6.15 → 0.10.0)

**Impact:** MEDIUM
**Risk:** LOW
**Recommendation:** UPGRADE

**Purpose:** Underlying API protocol layer (gRPC definitions)
**Changes:** Likely API schema updates, new features support
**Dependency:** Required by google-genai (transitive)

**Note:** This is NOT the deprecated SDK - this is the protocol buffer definitions package.

---

#### protobuf (5.29.6 → 6.33.5)

**Impact:** HIGH (major version)
**Risk:** LOW
**Recommendation:** UPGRADE

**Breaking Changes:**
- ✅ Python 3.9+ required (we're on 3.12.3 - safe)
- ❌ Removed: `FieldDescriptor.label` (deprecated)
- ❌ Removed: `UseDeprecatedLegacyJsonFieldConflicts()` (deprecated)
- ⚠️ `__qualname__` change for nested messages (cosmetic)

**Assessment:** We don't use deprecated APIs. Safe to upgrade.

**Source:** [Protobuf Version Support](https://protobuf.dev/support/version-support/)

---

### 2. OpenAI SDK (2.11.0 → 2.17.0)

**Impact:** MEDIUM-HIGH
**Risk:** LOW
**Recommendation:** UPGRADE

**Affected Providers:**
- Perplexity (uses OpenAI SDK)
- OpenAI-compat (custom providers via OpenAI format)
- Local providers (vLLM, Ollama, LMStudio)

**Changes:** Likely bug fixes, new API features, better error handling

**Benefit:** More stable API interactions across all OpenAI-compatible providers.

---

### 3. Server Stack

#### fastapi (0.124.4 → 0.128.5)

**Impact:** MEDIUM
**Risk:** LOW
**Recommendation:** UPGRADE

**Affected Components:**
- `ppxai-server` (HTTP + SSE endpoints)
- VSCode extension communication
- Web app backend

**Changes:** 4 minor versions - likely bug fixes, performance improvements

---

#### starlette (0.50.0 → 0.52.1)

**Impact:** MEDIUM
**Risk:** LOW
**Recommendation:** UPGRADE

**Purpose:** FastAPI's underlying ASGI framework
**Changes:** Performance improvements, bug fixes

---

#### uvicorn (0.38.0 → 0.40.0)

**Impact:** MEDIUM
**Risk:** LOW
**Recommendation:** UPGRADE

**Purpose:** ASGI server runtime
**Changes:** 2 minor versions - stability improvements

---

### 4. TUI/UI Stack

#### textual (7.4.0 → 7.5.0)

**Impact:** LOW-MEDIUM
**Risk:** LOW
**Recommendation:** UPGRADE

**Affected:** `ppxaide` (Textual-based TUI)
**Changes:** 1 minor version - bug fixes, widget improvements

---

#### rich (14.2.0 → 14.3.2)

**Impact:** LOW
**Risk:** LOW
**Recommendation:** UPGRADE

**Affected:**
- `ppxai` (Rich CLI)
- Markdown rendering in TUI
- Console output formatting

**Changes:** 2 patch versions - rendering improvements

---

### 5. Development Tools

#### ruff (0.14.9 → 0.15.0)

**Impact:** LOW (dev only)
**Risk:** LOW
**Recommendation:** UPGRADE

**Purpose:** Linter/formatter
**Changes:** New lint rules, performance improvements

**Note:** Doesn't affect runtime, only code quality checks.

---

#### pyinstaller (6.17.0 → 6.18.0)

**Impact:** LOW (build only)
**Risk:** LOW
**Recommendation:** UPGRADE LATER

**Purpose:** Binary building
**When to upgrade:** Before next release (v1.16.0), not urgent for benchmarks

---

### 6. Low Priority Updates

| Package | Current | Latest | Impact | Risk |
|---------|---------|--------|--------|------|
| anyio | 4.12.0 | 4.12.1 | LOW | LOW |
| cachetools | 6.2.4 | 7.0.0 | LOW | LOW |
| certifi | 2025.11.12 | 2026.1.4 | LOW | LOW |
| google-auth | 2.45.0 | 2.48.0 | LOW | LOW |
| grpcio-status | 1.71.2 | 1.78.0 | LOW | LOW |
| ipython | 9.8.0 | 9.10.0 | LOW | LOW |
| jiter | 0.12.0 | 0.13.0 | LOW | LOW |
| packaging | 25.0 | 26.0 | LOW | LOW |
| pyasn1 | 0.6.1 | 0.6.2 | LOW | LOW |
| pyinstaller-hooks-contrib | 2025.10 | 2026.0 | LOW | LOW |
| setuptools | 80.9.0 | 81.0.0 | LOW | LOW |
| sse-starlette | 3.0.3 | 3.2.0 | LOW | LOW |
| tenacity | 9.1.2 | 9.1.4 | LOW | LOW |
| tqdm | 4.67.1 | 4.67.3 | LOW | LOW |
| tzdata | 2025.2 | 2025.3 | LOW | LOW |
| urllib3 | 2.6.2 | 2.6.3 | LOW | LOW |
| wcwidth | 0.2.14 | 0.6.0 | LOW | MEDIUM |

**Note on wcwidth:** 0.2.14 → 0.6.0 is a major jump. Used for terminal width calculations. Low impact but test TUI after upgrade.

---

## Upgrade Strategy

### Option 1: Conservative (Recommended for Benchmarks)

**Upgrade only critical Gemini stack:**
```bash
uv pip install --upgrade google-genai google-ai-generativelanguage protobuf
```

**Why:**
- Minimal risk
- Focused on benchmark needs
- Quick verification (5 minutes)

**After benchmarks:** Upgrade rest of stack.

---

### Option 2: Comprehensive (Recommended Overall)

**Upgrade all outdated packages:**
```bash
uv pip install --upgrade \
  google-genai google-ai-generativelanguage protobuf \
  openai fastapi starlette uvicorn \
  textual rich ruff \
  anyio cachetools certifi google-auth grpcio-status \
  ipython jiter packaging pyasn1 pyinstaller-hooks-contrib \
  setuptools sse-starlette tenacity tqdm tzdata urllib3
```

**Skip for now:**
- `wcwidth` (major version jump - test separately)
- `pyinstaller` (not needed for benchmarks)

**Verification steps:**
1. Run test suite: `uv run pytest tests/ -v`
2. Test TUI: `uv run ppxaide --version`
3. Test server: `uv run ppxai-server &` + curl test
4. Run single benchmark: `uv run python benchmarks/llm-eval/benchmark.py --provider gemini --model gemini-2.5-flash --categories tool_calling`

**Time:** 15-20 minutes

---

### Option 3: Full Upgrade (Most Aggressive)

**Upgrade everything including risky packages:**
```bash
uv pip install --upgrade-all
```

**Risks:**
- wcwidth 0.6.0 might break terminal width calculations
- Untested package interactions
- Need full regression testing

**Recommendation:** NOT before benchmarks. Save for v1.16.0 development.

---

## Recommended Approach

### Phase 1: Pre-Benchmark (NOW)

**Strategy:** Conservative (Option 1)

```bash
# 1. Backup current lock
cp uv.lock uv.lock.backup

# 2. Upgrade Gemini stack
uv pip install --upgrade google-genai google-ai-generativelanguage protobuf

# 3. Verify installation
uv pip list | grep -E "(google-genai|google-ai-generativelanguage|protobuf)"

# 4. Quick smoke test
uv run python -c "from google import genai; print('Gemini SDK OK')"

# 5. Update lock file
uv lock
```

**Expected versions after upgrade:**
- google-genai: 1.62.0
- google-ai-generativelanguage: 0.10.0
- protobuf: 6.33.5

**Verification:** Run single test benchmark
```bash
uv run python benchmarks/llm-eval/benchmark.py \
  --provider gemini \
  --model gemini-2.5-flash \
  --categories tool_calling
```

**If successful:** Proceed with full Gemini tuning plan.

**If issues:** Rollback with `cp uv.lock.backup uv.lock && uv sync`

---

### Phase 2: Post-Benchmark (After Gemini Tuning)

**Strategy:** Comprehensive (Option 2)

Upgrade remaining packages after benchmarks complete:
```bash
uv pip install --upgrade \
  openai fastapi starlette uvicorn \
  textual rich ruff \
  anyio cachetools certifi google-auth grpcio-status \
  ipython jiter packaging pyasn1 sse-starlette \
  tenacity tqdm tzdata urllib3

uv lock
uv run pytest tests/ -v
```

---

### Phase 3: v1.16.0 Development (Future)

**Strategy:** Full upgrade including risky packages

Test wcwidth 0.6.0 and pyinstaller 6.18.0 in development branch.

---

## Impact Assessment

### Before Upgrade

| Component | google-genai | protobuf | openai | fastapi |
|-----------|--------------|----------|--------|---------|
| Gemini benchmarks | 1.56.0 | 5.29.6 | N/A | N/A |
| Perplexity benchmarks | N/A | N/A | 2.11.0 | N/A |
| VSCode server | 1.56.0 | 5.29.6 | N/A | 0.124.4 |
| TUI (ppxaide) | 1.56.0 | 5.29.6 | N/A | N/A |

### After Phase 1 Upgrade

| Component | google-genai | protobuf | openai | fastapi |
|-----------|--------------|----------|--------|---------|
| Gemini benchmarks | **1.62.0** ✅ | **6.33.5** ✅ | N/A | N/A |
| Perplexity benchmarks | N/A | **6.33.5** ✅ | 2.11.0 | N/A |
| VSCode server | **1.62.0** ✅ | **6.33.5** ✅ | N/A | 0.124.4 |
| TUI (ppxaide) | **1.62.0** ✅ | **6.33.5** ✅ | N/A | N/A |

### After Phase 2 Upgrade

| Component | google-genai | protobuf | openai | fastapi |
|-----------|--------------|----------|--------|---------|
| Gemini benchmarks | **1.62.0** ✅ | **6.33.5** ✅ | N/A | N/A |
| Perplexity benchmarks | N/A | **6.33.5** ✅ | **2.17.0** ✅ | N/A |
| VSCode server | **1.62.0** ✅ | **6.33.5** ✅ | N/A | **0.128.5** ✅ |
| TUI (ppxaide) | **1.62.0** ✅ | **6.33.5** ✅ | N/A | N/A |

---

## Rollback Plan

If any upgrade causes issues:

```bash
# Restore backup
cp uv.lock.backup uv.lock

# Reinstall from lock
uv sync

# Verify
uv pip list | grep -E "(google-genai|protobuf|openai)"
```

---

## Expected Benefits

### Immediate (Phase 1)
- ✅ Latest Gemini SDK (1.62.0) - best compatibility
- ✅ Better edge case handling in tool responses
- ✅ Improved metadata for debugging
- ✅ Modern protobuf protocol (6.x series)

### Post-Benchmark (Phase 2)
- ✅ More stable OpenAI SDK (better Perplexity interactions)
- ✅ Improved FastAPI server (better VSCode extension)
- ✅ Better TUI rendering (textual + rich updates)
- ✅ Enhanced development tools (ruff 0.15.0)

---

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Protobuf 6.x breaks code | LOW | We don't use deprecated APIs |
| Benchmark results change | MEDIUM | Run comparison benchmarks |
| TUI rendering issues | LOW | Test ppxaide after upgrade |
| Server endpoint breaks | LOW | Test with curl/VSCode |
| Test suite failures | LOW | Run full pytest before committing |

---

## Testing Checklist

After each upgrade phase:

- [ ] `uv pip list` shows correct versions
- [ ] `uv run python -c "from google import genai; print('OK')"` succeeds
- [ ] `uv run pytest tests/ -v` passes (100%)
- [ ] `uv run ppxaide --version` shows correct version
- [ ] Single benchmark test completes successfully
- [ ] TUI renders correctly (no width issues)
- [ ] Server starts without errors

---

## Sources

- [Protobuf Version Support](https://protobuf.dev/support/version-support/)
- [Protobuf Migration Guide](https://protobuf.dev/support/migration/)
- [google-genai Changelog](https://github.com/googleapis/python-genai/blob/main/CHANGELOG.md)
- [google-genai Releases](https://github.com/googleapis/python-genai/releases)

---

## Conclusion

**Recommendation:** Execute **Phase 1 (Conservative)** upgrade NOW before Gemini benchmarks.

**Command:**
```bash
uv pip install --upgrade google-genai google-ai-generativelanguage protobuf && uv lock
```

**Verification:**
```bash
uv run python benchmarks/llm-eval/benchmark.py --provider gemini --model gemini-2.5-flash --categories tool_calling
```

**If successful:** Proceed with full Gemini tuning experiments.

**Time investment:** 5-10 minutes
**Risk:** LOW
**Benefit:** MEDIUM-HIGH (better Gemini compatibility, latest features)
