# Premium Web Search - Comprehensive Test Matrix

**Version:** v1.13.4
**Date Created:** 2026-01-03
**Status:** Testing Guide

## Overview

This document defines the comprehensive test matrix for premium web search fallback scenarios across all providers and configuration combinations.

## Test Matrix: Providers × Configurations × API Keys

### Dimensions

| Dimension | Values | Count |
|-----------|--------|-------|
| **Providers** | Perplexity, Gemini, OpenAI, OpenRouter, Custom vLLM | 5 |
| **Global Config** | auto, perplexity, gemini, duckduckgo | 4 |
| **Per-Provider Config** | (none), auto, perplexity, gemini, duckduckgo | 5 |
| **API Keys Set** | none, perplexity-only, gemini-only, both | 4 |

**Total Test Cases:** 5 × 4 × 5 × 4 = **400 combinations**
**Practical Test Cases (after filtering exclusions):** ~120 cases

---

## Test Categories

### Category 1: Providers with Native Search (Should Exclude web_search Tool)

#### 1.1 Perplexity Provider

| Test Case | Provider | Global Config | Per-Provider | API Keys | Expected Behavior |
|-----------|----------|---------------|--------------|----------|-------------------|
| P-1.1 | Perplexity | auto | (none) | perplexity | ✓ NO web_search tool (native search) |
| P-1.2 | Perplexity | perplexity | (none) | perplexity | ✓ NO web_search tool (native search) |
| P-1.3 | Perplexity | gemini | (none) | gemini | ✓ NO web_search tool (native search) |
| P-1.4 | Perplexity | duckduckgo | (none) | (none) | ✓ NO web_search tool (native search) |

**Notes:**
- Perplexity always has native web search via sonar models
- web_search tool should never be registered regardless of config
- Provider exclusion in register_tools() handles this

---

#### 1.2 Gemini Provider

| Test Case | Provider | Global Config | Per-Provider | API Keys | Expected Behavior |
|-----------|----------|---------------|--------------|----------|-------------------|
| G-1.1 | Gemini | auto | (none) | gemini | ✓ NO web_search tool (Google Search Grounding) |
| G-1.2 | Gemini | perplexity | (none) | perplexity | ✓ NO web_search tool (Google Search Grounding) |
| G-1.3 | Gemini | gemini | (none) | gemini | ✓ NO web_search tool (Google Search Grounding) |
| G-1.4 | Gemini | duckduckgo | (none) | (none) | ✓ NO web_search tool (Google Search Grounding) |

**Notes:**
- Gemini capabilities now correctly set to web_search=true
- Google Search Grounding provides native search
- web_search tool should never be registered regardless of config

---

### Category 2: Providers WITHOUT Native Search (Should Register web_search Tool)

#### 2.1 OpenAI Provider - Auto-Detect (Global Config)

| Test Case | Provider | Global Config | Per-Provider | API Keys | Expected Result |
|-----------|----------|---------------|--------------|----------|-----------------|
| O-2.1.1 | OpenAI | auto | (none) | neither | DuckDuckGo (free) |
| O-2.1.2 | OpenAI | auto | (none) | perplexity | Perplexity (premium) |
| O-2.1.3 | OpenAI | auto | (none) | gemini | Gemini (premium) |
| O-2.1.4 | OpenAI | auto | (none) | both | Perplexity (priority) |

**Expected Behavior:**
- Registers web_search tool ✓
- Uses global "preferred": "auto"
- Auto-detects: Perplexity → Gemini → DuckDuckGo
- When both keys present, Perplexity wins (priority order)

---

#### 2.2 OpenAI Provider - Force Perplexity (Global Config)

| Test Case | Provider | Global Config | Per-Provider | API Keys | Expected Result |
|-----------|----------|---------------|--------------|----------|-----------------|
| O-2.2.1 | OpenAI | perplexity | (none) | neither | ❌ Error (key not set, no fallback) |
| O-2.2.2 | OpenAI | perplexity | (none) | perplexity | Perplexity (forced) ✓ |
| O-2.2.3 | OpenAI | perplexity | (none) | gemini | ❌ Error (Perplexity key missing, no fallback) |
| O-2.2.4 | OpenAI | perplexity | (none) | both | Perplexity (forced) ✓ |

**Expected Behavior:**
- Registers web_search tool ✓
- Uses global "preferred": "perplexity"
- Only uses Perplexity, no fallback to Gemini or DuckDuckGo
- Fails if PERPLEXITY_API_KEY not set

---

#### 2.3 OpenAI Provider - Force Gemini (Global Config)

| Test Case | Provider | Global Config | Per-Provider | API Keys | Expected Result |
|-----------|----------|---------------|--------------|----------|-----------------|
| O-2.3.1 | OpenAI | gemini | (none) | neither | ❌ Error (key not set, no fallback) |
| O-2.3.2 | OpenAI | gemini | (none) | perplexity | ❌ Error (Gemini key missing, no fallback) |
| O-2.3.3 | OpenAI | gemini | (none) | gemini | Gemini (forced) ✓ |
| O-2.3.4 | OpenAI | gemini | (none) | both | Gemini (forced) ✓ |

**Expected Behavior:**
- Registers web_search tool ✓
- Uses global "preferred": "gemini"
- Only uses Gemini, no fallback to Perplexity or DuckDuckGo
- Fails if GEMINI_API_KEY not set

---

#### 2.4 OpenAI Provider - Force DuckDuckGo (Global Config)

| Test Case | Provider | Global Config | Per-Provider | API Keys | Expected Result |
|-----------|----------|---------------|--------------|----------|-----------------|
| O-2.4.1 | OpenAI | duckduckgo | (none) | neither | DuckDuckGo (forced) ✓ |
| O-2.4.2 | OpenAI | duckduckgo | (none) | perplexity | DuckDuckGo (forced, key ignored) ✓ |
| O-2.4.3 | OpenAI | duckduckgo | (none) | gemini | DuckDuckGo (forced, key ignored) ✓ |
| O-2.4.4 | OpenAI | duckduckgo | (none) | both | DuckDuckGo (forced, keys ignored) ✓ |

**Expected Behavior:**
- Registers web_search tool ✓
- Uses global "preferred": "duckduckgo"
- Always uses free DuckDuckGo, ignores API keys
- Never fails

---

#### 2.5 OpenAI Provider - Per-Provider Override (Gemini Override)

| Test Case | Provider | Global Config | Per-Provider | API Keys | Expected Result |
|-----------|----------|---------------|--------------|----------|-----------------|
| O-2.5.1 | OpenAI | auto | gemini | neither | DuckDuckGo (per-provider: gemini, but key missing, falls back to auto) |
| O-2.5.2 | OpenAI | auto | gemini | perplexity | DuckDuckGo (per-provider: gemini, but key missing, falls back to auto) |
| O-2.5.3 | OpenAI | auto | gemini | gemini | Gemini (per-provider override) ✓ |
| O-2.5.4 | OpenAI | auto | gemini | both | Gemini (per-provider override) ✓ |
| O-2.5.5 | OpenAI | perplexity | gemini | both | Gemini (per-provider overrides global) ✓ |

**Expected Behavior:**
- Per-provider config overrides global config
- Per-provider "preferred": "gemini" only uses Gemini if key available
- Falls back to auto-detect if per-provider key not available
- Respects fallback chain: Per-provider → Global → Auto-detect

---

#### 2.6 OpenAI Provider - Per-Provider Override (Perplexity Override)

| Test Case | Provider | Global Config | Per-Provider | API Keys | Expected Result |
|-----------|----------|---------------|--------------|----------|-----------------|
| O-2.6.1 | OpenAI | auto | perplexity | neither | DuckDuckGo (per-provider: perplexity, but key missing, falls back to auto) |
| O-2.6.2 | OpenAI | auto | perplexity | gemini | DuckDuckGo (per-provider: perplexity, but key missing, falls back to auto) |
| O-2.6.3 | OpenAI | auto | perplexity | perplexity | Perplexity (per-provider override) ✓ |
| O-2.6.4 | OpenAI | auto | perplexity | both | Perplexity (per-provider override) ✓ |
| O-2.6.5 | OpenAI | gemini | perplexity | both | Perplexity (per-provider overrides global) ✓ |

**Expected Behavior:**
- Per-provider "preferred": "perplexity" only uses Perplexity if key available
- Falls back to auto-detect if per-provider key not available
- Precedence: Per-provider config > Global config > Auto-detect

---

### Category 3: Other Non-Native-Search Providers

#### 3.1 OpenRouter Provider

| Test Case | Provider | Global Config | Per-Provider | API Keys | Expected Result |
|-----------|----------|---------------|--------------|----------|-----------------|
| OR-3.1.1 | OpenRouter | auto | (none) | neither | DuckDuckGo |
| OR-3.1.2 | OpenRouter | auto | (none) | perplexity | Perplexity ✓ |
| OR-3.1.3 | OpenRouter | auto | (none) | gemini | Gemini ✓ |
| OR-3.1.4 | OpenRouter | auto | (none) | both | Perplexity (priority) ✓ |
| OR-3.1.5 | OpenRouter | auto | perplexity | both | Perplexity (per-provider) ✓ |

**Expected Behavior:**
- Same as OpenAI: auto-detect with fallback
- Per-provider override works the same way

---

#### 3.2 Custom vLLM Provider

| Test Case | Provider | Global Config | Per-Provider | API Keys | Expected Result |
|-----------|----------|---------------|--------------|----------|-----------------|
| CV-3.2.1 | Custom vLLM | auto | (none) | neither | DuckDuckGo |
| CV-3.2.2 | Custom vLLM | auto | (none) | perplexity | Perplexity ✓ |
| CV-3.2.3 | Custom vLLM | auto | (none) | gemini | Gemini ✓ |
| CV-3.2.4 | Custom vLLM | auto | (none) | both | Perplexity (priority) ✓ |
| CV-3.2.5 | Custom vLLM | duckduckgo | (none) | both | DuckDuckGo (forced) ✓ |

**Expected Behavior:**
- Same fallback logic as other non-native providers
- Benefits most from premium search since no native search

---

## Test Execution Checklist

### Pre-Test Setup
- [ ] Create test environment with isolated .env files
- [ ] Set up API key combinations for testing
- [ ] Create config files for each test scenario
- [ ] Document actual vs expected results

### Phase 1: Native Search Providers (Should Pass)
- [ ] Perplexity: Verify NO web_search tool registered
- [ ] Gemini: Verify NO web_search tool registered
- [ ] Both: Verify capabilities correctly set to web_search=true

### Phase 2: Auto-Detect (No Keys)
- [ ] OpenAI + no keys → DuckDuckGo
- [ ] OpenAI + Perplexity key → Perplexity
- [ ] OpenAI + Gemini key → Gemini
- [ ] OpenAI + both keys → Perplexity (priority)

### Phase 3: Global Config Overrides
- [ ] "preferred": "perplexity" with key → Perplexity ✓
- [ ] "preferred": "perplexity" without key → Error ✗
- [ ] "preferred": "gemini" with key → Gemini ✓
- [ ] "preferred": "gemini" without key → Error ✗
- [ ] "preferred": "duckduckgo" → Always DuckDuckGo ✓

### Phase 4: Per-Provider Config Overrides
- [ ] Per-provider override takes precedence over global
- [ ] Per-provider fallback to global if key missing
- [ ] Per-provider fallback to auto-detect if needed
- [ ] Wrapper function correctly passes provider_name

### Phase 5: Usage Tracking
- [ ] Perplexity calls: tracked as "perplexity", per-token pricing
- [ ] Gemini calls: tracked as "gemini", per-query pricing
- [ ] DuckDuckGo calls: tracked as "duckduckgo", free (no cost)
- [ ] /usage command shows tool provider correctly
- [ ] /tools status shows search provider correctly

### Phase 6: Error Handling
- [ ] Invalid Perplexity API key → Falls back to DuckDuckGo
- [ ] Invalid Gemini API key → Falls back to DuckDuckGo
- [ ] Network error during Perplexity call → Falls back to DuckDuckGo
- [ ] Network error during Gemini call → Falls back to DuckDuckGo
- [ ] Malformed API response → Falls back to DuckDuckGo

---

## Expected Test Results Summary

| Scenario | Expected Outcome | Risk Level |
|----------|-----------------|-----------|
| Perplexity provider with any config | NO tool (native) | Low |
| Gemini provider with any config | NO tool (native) | Low |
| OpenAI + auto + no keys | DuckDuckGo | Low |
| OpenAI + auto + Perplexity key | Perplexity | Medium |
| OpenAI + auto + Gemini key | Gemini | Medium |
| OpenAI + force Perplexity + no key | Error (expected) | Low |
| OpenAI + force DuckDuckGo | Always DuckDuckGo | Low |
| OpenAI + per-provider override | Per-provider config | High |
| Per-provider fallback to auto | Correct fallback chain | High |
| Usage tracking per provider | Correct attribution | Medium |

---

## Known Issues & Mitigations

### Issue 1: Missing API Key with Forced Config
**Scenario:** `"preferred": "perplexity"` but no PERPLEXITY_API_KEY set
**Current Behavior:** Function tries to execute, fails with ValueError
**Mitigation:** Documented in config comments. Users should check `get_premium_search_provider()` returns valid provider before using.

### Issue 2: Per-Provider Config Propagation
**Scenario:** Per-provider web_search config not reaching register_tools()
**Mitigation:** Wrapper closure (`web_search_with_provider`) captures provider_name at registration time

### Issue 3: Global Config Not Found
**Scenario:** config.get_tool_config() returns empty dict
**Current Behavior:** Falls back to auto-detect (safe)
**Mitigation:** Try/except in get_premium_search_provider()

---

## Test Execution Notes

When running tests:
1. **Isolate environment:** Each test should have clean env vars
2. **Mock API calls:** Use responses library to mock Perplexity/Gemini APIs
3. **Log provider choice:** Add logging to get_premium_search_provider() for debugging
4. **Track fallbacks:** Monitor when premium search falls back to DuckDuckGo
5. **Verify registration:** Check tool_manager.list_tools() includes/excludes web_search

---

## Success Criteria

All test cases should pass with:
- ✓ Correct provider selection based on precedence
- ✓ Proper fallback behavior when API keys missing
- ✓ No errors or crashes (except documented expected failures)
- ✓ Correct usage tracking per provider
- ✓ UI displays correct search provider
- ✓ Native search providers never register web_search tool

---

## Test Results Log

| Phase | Test Case | Result | Notes |
|-------|-----------|--------|-------|
| 1 | Perplexity native search | PENDING | To be tested |
| 1 | Gemini native search | PENDING | To be tested |
| 2 | OpenAI auto-detect | PENDING | To be tested |
| 3 | Global config override | PENDING | To be tested |
| 4 | Per-provider override | PENDING | To be tested |
| 5 | Usage tracking | PENDING | To be tested |
| 6 | Error handling | PENDING | To be tested |

