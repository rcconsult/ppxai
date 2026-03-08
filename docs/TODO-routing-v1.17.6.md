# TODO: Multi-Model Routing (v1.17.6+)

**Status:** Planning
**Target:** v1.17.6 (infrastructure), v1.18.x (full routing)
**Priority:** Medium — foundational for advanced agentic workflows

---

## Overview

Enable cross-provider/model routing so ppxai can use different models for different
roles within a single session: planning with a reasoning model, coding with a code
specialist, tool execution with a fast model, and chat with a cheap model.

### Motivation

Primary target is the **k8s-based ppxai deployment** with access to multiple local/corporate
models (GPT-OSS 120B on DGX cluster, Qwen3-Coder-30B on DGX Spark), where routing
compensates for each model's weaknesses:

- **GPT-OSS 120B**: Strong reasoning and planning, but slow inference, Harmony format
  quirks, and intermittent tool call failures (HarmonyError)
- **Qwen3-Coder-30B**: Fast inference (81.2% benchmark), excellent at code editing and
  tool calling, but weaker at complex multi-step planning
- **Cloud models** (Perplexity, Gemini): Best for web search/grounding, but require
  network access and incur API costs

By routing planning to GPT-OSS and execution to Qwen3-Coder, sessions get the best
of both: robust task decomposition AND fast, reliable code generation and tool use.

Secondary use case: local development with LM Studio (budget hardware) using cloud
models for planning and local models for execution.

---

## Architecture

### Core Principle

The routing layer sits **above** `EngineClient`, not inside it. `EngineClient` remains
the single-model facade. The router manages a pool of provider instances and swaps
them into `EngineClient` as needed.

```
User Request
    │
    ▼
ModelRouter.resolve(role)
    │
    ▼
ProviderPool.get_provider(name)   ← lazy init + cache
    │
    ▼
EngineClient.provider = cached_instance
    │
    ▼
API call → response
    │
    ▼
Restore original provider (if temporary switch)
```

### Four Roles

| Role | When Used | Example Models |
|------|-----------|----------------|
| `chat` | Regular conversation (single turns) | gpt-5-mini, sonar, qwen2.5-coder-7b |
| `planner` | Agent mode first turn (task decomposition) | o4-mini, sonar-reasoning-pro |
| `coder` | Coding commands (/generate, /test, /explain) | gemini-3-flash, codex-mini |
| `tools` | Agent tool loop iterations 2+ | gpt-5.2, qwen2.5-coder-7b |

### New Code

```
ppxai/engine/router.py  (NEW — ~200 lines)
├── RoutingRole(Enum)      — chat, planner, coder, tools
├── RoleBinding            — dataclass: provider_name + model_id
├── ProviderPool           — lazy create + cache provider instances
└── ModelRouter            — resolve(role) → RoleBinding, set_preset(), enabled
```

---

## Config Schema

Added to `ppxai-config.json` under a new `routing` key:

```json
{
  "routing": {
    "enabled": false,
    "active_preset": "cloud-power",
    "mode_presets": {
      "agent": "cloud-power",
      "chat": "budget"
    },
    "presets": {
      "cloud-power": {
        "description": "High-quality cloud models for each role",
        "roles": {
          "chat":    {"provider": "openai",    "model": "gpt-5-mini"},
          "planner": {"provider": "openai",    "model": "o4-mini"},
          "coder":   {"provider": "gemini",    "model": "gemini-3-flash-preview"},
          "tools":   {"provider": "openai",    "model": "gpt-5.2"}
        }
      },
      "local-dev": {
        "description": "Local coding with cloud planning",
        "roles": {
          "chat":    {"provider": "lmstudio",   "model": "qwen2.5-coder-7b-instruct"},
          "planner": {"provider": "perplexity", "model": "sonar-pro"},
          "coder":   {"provider": "lmstudio",   "model": "qwen2.5-coder-7b-instruct"},
          "tools":   {"provider": "lmstudio",   "model": "qwen2.5-coder-7b-instruct"}
        }
      },
      "dgx-hybrid": {
        "description": "GPT-OSS thinks, Qwen3-Coder executes (k8s)",
        "think":   {"provider": "custom",      "model": "openai/gpt-oss-120b"},
        "execute": {"provider": "asusai-vllm", "model": "Qwen3-Coder-30B-A3B-Instruct-FP8"}
      },
      "dgx-full": {
        "description": "All GPT-OSS (max quality, slower)",
        "default": {"provider": "custom", "model": "openai/gpt-oss-120b"}
      },
      "openai-split": {
        "description": "o4-mini reasons, codex-mini codes",
        "think":   {"provider": "openai", "model": "o4-mini"},
        "execute": {"provider": "openai", "model": "gpt-5.1-codex-mini"}
      },
      "offline": {
        "description": "All local, no network required",
        "default": {"provider": "lmstudio", "model": "qwen2.5-coder-7b-instruct"}
      },
      "budget": {
        "description": "All roles use same cheap model",
        "default": {"provider": "openai", "model": "gpt-5-mini"}
      }
    }
  }
}
```

### Config Rules

- `enabled: false` (default) preserves current single-model behavior — fully backward compatible
- `mode_presets` is optional — if omitted, `active_preset` is used for all modes
- Each role in a preset must reference a provider defined in the `providers` section
- If a role's provider API key is missing, router falls back to current provider with WARNING event
- Presets can share roles (e.g., budget preset maps all roles to same model)

### Simplified Presets (Recommended Pattern)

Most real presets will use only **2 backends** (think+execute split) or even a
**single provider with 2 models**. The 4-role system supports this naturally —
just map multiple roles to the same provider/model:

**Pattern 1: Two backends (most common in k8s)**
```json
{
  "dgx-hybrid": {
    "description": "GPT-OSS thinks, Qwen3-Coder acts",
    "think":   {"provider": "custom",      "model": "openai/gpt-oss-120b"},
    "execute": {"provider": "asusai-vllm", "model": "Qwen3-Coder-30B"}
  }
}
```

**Pattern 2: Single provider, two models**
```json
{
  "openai-split": {
    "description": "o4-mini reasons, codex-mini codes",
    "think":   {"provider": "openai", "model": "o4-mini"},
    "execute": {"provider": "openai", "model": "gpt-5.1-codex-mini"}
  }
}
```

**Pattern 3: Single model (equivalent to current behavior)**
```json
{
  "simple": {
    "description": "Everything on one model",
    "default": {"provider": "gemini", "model": "gemini-3-flash-preview"}
  }
}
```

To support this, presets accept **shorthand keys** that expand to full role mappings:

| Shorthand | Expands To |
|-----------|-----------|
| `default` | All 4 roles (chat, planner, coder, tools) |
| `think` | `planner` + `chat` |
| `execute` | `coder` + `tools` |

Explicit role keys (`chat`, `planner`, `coder`, `tools`) always override shorthands.
This keeps simple presets short (2-3 lines) while allowing full control when needed.

---

## Phased Implementation

### Phase 1: Infrastructure (v1.17.6)

**Goal:** Define config schema, build `ProviderPool` and `ModelRouter` — no actual routing yet.

**New files:**
- `ppxai/engine/router.py` — `RoutingRole`, `RoleBinding`, `ProviderPool`, `ModelRouter`

**Modified files:**
- `ppxai/config/__init__.py` — Add `get_routing_config()`, `get_active_preset()`
- `ppxai-config.example.json` — Add `routing` section (disabled by default)

**Key classes:**

```python
from enum import Enum
from dataclasses import dataclass

class RoutingRole(Enum):
    CHAT = "chat"
    PLANNER = "planner"
    CODER = "coder"
    TOOLS = "tools"

@dataclass
class RoleBinding:
    """Resolved provider+model for a specific role."""
    provider_name: str
    model_id: str

class ProviderPool:
    """Lazily creates and caches provider instances by provider name."""

    def get_provider(self, provider_name: str) -> BaseProvider:
        """Get or create a provider instance. Cached after first creation."""
        ...

    def warmup(self, provider_names: list[str]) -> None:
        """Pre-create providers for a preset to avoid cold-start latency."""
        ...

class ModelRouter:
    """Resolves routing roles to provider/model pairs based on active preset."""

    def __init__(self, config: dict, provider_pool: ProviderPool):
        ...

    def resolve(self, role: RoutingRole) -> RoleBinding:
        """Get the provider+model binding for a role in the active preset."""
        ...

    def set_preset(self, name: str) -> bool:
        """Switch to a named preset. Returns False if preset doesn't exist."""
        ...

    @property
    def enabled(self) -> bool:
        """Whether routing is enabled in config."""
        ...
```

**Tests:**
- `tests/test_router.py` — Unit tests for ProviderPool, ModelRouter, RoleBinding
- Test preset resolution, fallback on missing API key, preset switching

**Definition of Done:**
- [ ] `RoutingRole` enum, `RoleBinding` dataclass, `ProviderPool`, `ModelRouter` implemented
- [ ] Config validation for routing section
- [ ] Unit tests pass
- [ ] `routing.enabled: false` has zero impact on existing behavior

---

### Phase 2: Coding Command Routing (v1.17.7)

**Goal:** Replace `coding_model` + `/autoroute` with routing system. Simplest integration
point — coding commands already switch models.

**Modified files:**
- `ppxai/engine/client.py` — Add `self._router: Optional[ModelRouter]`, init from config
- `ppxai/commands/coding.py` — Use `router.resolve(RoutingRole.CODER)` instead of `get_coding_model()`
- `ppxai/commands/provider.py` — Update `/autoroute` to show routing info

**Key pattern — temporary provider switch:**

```python
async def _with_role(self, role: RoutingRole, fn):
    """Execute fn with the provider/model for the given role, then restore."""
    if not self._router or not self._router.enabled:
        return await fn()

    binding = self._router.resolve(role)
    original = (self.provider_name, self.model)

    try:
        if binding.provider_name != original[0]:
            self._swap_provider(binding.provider_name)  # uses ProviderPool
        if binding.model_id != self.model:
            self.set_model(binding.model_id, reset_context=False)
        return await fn()
    finally:
        if (binding.provider_name, binding.model_id) != original:
            self._swap_provider(original[0])
            self.set_model(original[1], reset_context=False)
```

**Important:** `_swap_provider()` is a NEW lightweight method that uses `ProviderPool`
to swap a cached provider instance, NOT `set_provider()` which reconstructs everything.

**Definition of Done:**
- [ ] `/generate`, `/test`, `/explain` use routing when enabled
- [ ] `/autoroute` shows active preset and role bindings
- [ ] Backward-compatible when routing disabled (falls back to `coding_model`)
- [ ] Provider swap uses pool (no reconstruction)

---

### Phase 3: Agent Mode Routing (v1.18.0)

**Goal:** In agent mode, route first turn to `planner` role, subsequent tool-loop
iterations to `tools` role.

**Modified files:**
- `ppxai/engine/chat.py` — `chat_with_tools()` uses routing for tool iterations
- `ppxai/engine/client.py` — `chat()` routes first agent turn to planner

**Complexity:** This is the hardest phase. `chat_with_tools()` currently assumes a fixed
provider/model for the entire iteration loop. The router must inject provider switches
between iterations while preserving the shared session.

**Approach:** Add `role_override: Optional[RoutingRole]` parameter to `chat()` and
`chat_with_tools()`. When set, resolve the role and swap provider before each API call.

**Cross-provider message compatibility issue:**
When switching providers mid-conversation, `tool_calls` and `tool_call_id` fields in
messages may not be understood by the new provider (e.g., OpenAI format vs Gemini native).
**Mitigation:** When provider changes, convert tool-related messages to text summaries
before sending to the new provider.

**Definition of Done:**
- [ ] Agent mode first turn uses `planner` role
- [ ] Tool loop iterations use `tools` role
- [ ] Session messages shared across role switches
- [ ] Cross-provider message format conversion works
- [ ] Fallback to single-model when routing disabled

---

### Phase 4: Chat Mode Routing + Mode Presets (v1.18.1)

**Goal:** Route regular chat to `chat` role. Support `mode_presets` for automatic
preset switching when entering/leaving agent mode.

**Modified files:**
- `ppxai/engine/client.py` — `chat()` resolves `RoutingRole.CHAT` for non-agent messages
- `ppxai/engine/router.py` — `resolve()` considers current mode when looking up preset

**Definition of Done:**
- [ ] Regular chat uses `chat` role
- [ ] Agent mode auto-switches to agent preset
- [ ] Mode preset switching is seamless (no user action required)

---

### Phase 5: `/preset` Command + TUI Integration (v1.18.2)

**Goal:** User-facing commands for preset management.

**New files:**
- `ppxai/commands/routing.py` — `/preset`, `/route` slash commands

**Commands:**
- `/preset` — Show current preset, all role bindings, active mode
- `/preset <name>` — Switch to a named preset
- `/preset list` — List all configured presets with descriptions
- `/route <role> <provider>/<model>` — Override a single role temporarily (session-only)

**TUI integration:**
- Status bar badge showing active preset name
- `/preset` output in side panel (ppxaide) or inline (ppxai)

**Definition of Done:**
- [ ] `/preset` and `/route` commands implemented
- [ ] Status bar shows preset name when routing enabled
- [ ] Commands work in TUI, server (VSCode/Web via CommandFactory)

---

### Phase 6: Prompt Analyzer + Automatic Routing (v1.19.x)

**Goal:** ppxai analyzes user prompts to automatically route to the best role,
with a tiered classifier that improves over time through usage data.

#### Phase 6a: Rule-Based Classifier (v1.19.0)

**New files:**
- `ppxai/engine/analyzer.py` — `PromptAnalyzer` class

**Tiered classification (fast path first, AI fallback last):**

```python
class PromptAnalyzer:
    """Tiered prompt classifier for automatic role routing."""

    def classify(self, prompt: str) -> tuple[RoutingRole, float]:
        """Returns (role, confidence 0.0-1.0)."""

        # Tier 1: Rule-based (~0ms, handles ~70% of prompts)
        role, conf = self._rule_classify(prompt)
        if conf >= 0.8:
            return role, conf

        # Tier 2: Embedding similarity (~10ms, handles ~25%)
        role, conf = self._embedding_classify(prompt)
        if conf >= 0.7:
            return role, conf

        # Tier 3: Silent AI classify (~500ms-2s, handles ~5%)
        return self._ai_classify(prompt)
```

**Tier 1 — Rule-based patterns:**

```python
PATTERNS = {
    RoutingRole.PLANNER: [
        r"\bplan\b", r"\bdesign\b", r"\barchitect", r"\bstrategy\b",
        r"\bhow should\b", r"\bbreak down\b", r"\bstep.?by.?step\b",
    ],
    RoutingRole.CODER: [
        r"\bwrite\b.*\b(function|class|code)\b", r"\bimplement\b",
        r"\brefactor\b", r"\bfix\b.*\b(bug|error)\b", r"\badd\b.*\bmethod\b",
        r"\.(py|js|ts|go|rs|java)\b",  # file extensions
    ],
    RoutingRole.TOOLS: [
        r"\brun\b.*\b(test|command|script)\b", r"\bexecute\b",
        r"\bdeploy\b", r"\bbuild\b", r"\bsearch\b.*\b(file|code)\b",
    ],
    RoutingRole.CHAT: [
        r"\bexplain\b", r"\bwhat is\b", r"\bwhy\b", r"\bhow does\b",
        r"\btell me\b", r"\bdescribe\b",
    ],
}
```

**Config:**
```json
{
  "routing": {
    "auto_classify": false,
    "classify_confidence_threshold": 0.7,
    "classify_fallback_role": "chat"
  }
}
```

**Definition of Done:**
- [ ] `PromptAnalyzer` with Tier 1 rules
- [ ] Integration with `ModelRouter.resolve()` — when `auto_classify: true`
- [ ] Confidence below threshold → fall back to `classify_fallback_role`
- [ ] `/route auto` to toggle automatic classification on/off

---

#### Phase 6b: Decision Logging (v1.19.1)

**Goal:** Log every routing decision for future learning.

**New files:**
- `ppxai/engine/routing_log.py` — `RoutingLogger` class

**Log format:** `~/.ppxai/routing/decisions.jsonl`

```jsonl
{"ts": "2026-03-08T15:00:00", "prompt_hash": "a1b2c3", "prompt_prefix": "refactor the auth...", "classified_role": "coder", "confidence": 0.85, "tier": 1, "provider": "asusai-vllm", "model": "Qwen3-Coder-30B", "tokens_in": 450, "tokens_out": 120, "tool_calls": 2, "duration_ms": 3200, "outcome": "success"}
{"ts": "2026-03-08T15:01:00", "prompt_hash": "d4e5f6", "prompt_prefix": "plan a migration...", "classified_role": "planner", "confidence": 0.92, "tier": 1, "provider": "custom", "model": "gpt-oss-120b", "tokens_in": 1200, "tokens_out": 800, "tool_calls": 0, "duration_ms": 8500, "outcome": "success"}
```

**Outcome signals (no explicit user feedback needed):**

| Signal | Meaning | Detection |
|--------|---------|-----------|
| User didn't re-ask or /regenerate | Satisfactory | Session log |
| Tool calls all succeeded | Right model for tools | Tool results |
| User manually switched model after | Wrong routing | Command log |
| User sent `/regenerate` | Bad response quality | Command log |
| Response within latency budget | Good model choice | Duration tracking |
| Low token usage | Efficient | Usage stats |

**Privacy:** Only prompt prefix (first 50 chars) + hash stored. Full prompts never logged.

**Definition of Done:**
- [ ] `RoutingLogger` writes decisions.jsonl
- [ ] Outcome signals captured from session events
- [ ] `/route stats` command shows routing decision summary
- [ ] Log rotation (keep last 10K decisions, ~2MB)

---

#### Phase 6c: Embedding Similarity Cache (v1.19.2)

**Goal:** Use past decisions to classify similar prompts without AI.

**Approach:** Build a local embedding index from logged decisions. When a new prompt
arrives, compute its embedding and find the nearest past decision.

**Embedding options (all local, no API):**
1. **TF-IDF + cosine similarity** — No ML, ~1ms, good enough for keyword overlap
2. **sentence-transformers** (all-MiniLM-L6-v2) — 384-dim, ~10ms, semantic similarity
3. **Ollama embeddings** (nomic-embed-text) — if Ollama is running anyway

**Recommended: TF-IDF first** (zero dependencies), upgrade to sentence-transformers
if accuracy is insufficient.

```python
class EmbeddingCache:
    """Local embedding index for prompt classification."""

    def __init__(self, decisions_path: str):
        self._index: dict[str, RoutingRole] = {}  # prompt_hash → role
        self._vectorizer = TfidfVectorizer(max_features=500)
        self._load_decisions(decisions_path)

    def classify(self, prompt: str) -> tuple[RoutingRole, float]:
        """Find most similar past prompt and return its role."""
        ...
```

**Cache rebuild:** Triggered on startup or after every 100 new decisions.

**Definition of Done:**
- [ ] `EmbeddingCache` with TF-IDF similarity
- [ ] Integrated as Tier 2 in `PromptAnalyzer`
- [ ] Cache rebuilds automatically from decisions.jsonl
- [ ] Benchmark: >80% accuracy on past decisions (cross-validation)

---

#### Phase 6d: Silent AI Classifier (v1.20.0)

**Goal:** For ambiguous prompts that Tier 1+2 can't classify, use a fast/cheap model.

**Silent classifier prompt:**
```
Classify this user request into ONE word: PLAN, CODE, TOOL, or CHAT.
- PLAN: Task decomposition, architecture, strategy, reasoning
- CODE: Write/edit/refactor code, fix bugs, add features
- TOOL: Run commands, search files, execute tests, deploy
- CHAT: Explain, discuss, describe, general questions

User: {prompt}
Category:
```

**Model selection (prioritized):**
1. Same model that's already loaded (no extra startup cost)
2. Smallest available local model (qwen2.5-coder:0.5b, ~50ms)
3. Cheapest cloud model (gpt-5-mini, ~200ms)

**Optimization:** Use `max_tokens: 3` — we only need one word back.

**Definition of Done:**
- [ ] Silent AI classify as Tier 3 fallback
- [ ] Configurable classifier model in routing config
- [ ] Timeout (500ms) — if classifier is slow, fall back to default role
- [ ] Decision logged with `tier: 3` for learning feedback

---

### Phase 7: Adaptive Learning (v1.21.x — Future)

**Goal:** The routing system improves over time by learning from its own decisions.

**Approach:**
1. Periodically analyze `decisions.jsonl` for patterns
2. Identify misrouted prompts (user switched model after, used /regenerate)
3. Update rule weights and embedding index accordingly
4. Optionally retrain a tiny local classifier (logistic regression on TF-IDF features)

**Learning loop:**

```
User prompt → PromptAnalyzer → Role → Model → Response
                    ↑                              ↓
                    │                         Outcome signal
                    │                              ↓
                    └──── RoutingLogger ← decisions.jsonl
                              ↓
                    EmbeddingCache rebuild (periodic)
```

**NOT a priority** — Phases 6a-6d provide 90% of the value. Phase 7 is a nice-to-have
for power users running ppxai in production k8s with high request volumes.

**Definition of Done:**
- [ ] Periodic cache rebuild incorporates outcome weights
- [ ] Misrouted decisions down-weighted in similarity index
- [ ] `/route learn` command triggers manual relearn
- [ ] Accuracy tracked over time in `/route stats`

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Provider switch latency in agent loops | Slower tool iterations | `ProviderPool` caches instances — swap is pointer assignment, not reconstruction |
| Tool re-registration on every switch | ~50ms overhead per switch | Cache tool registrations per provider in pool |
| Cross-provider message format incompatibility | Broken context after switch | Convert `tool_calls`/`tool_call_id` to text summaries when switching providers |
| Missing API key for preset role | Role unusable | `resolve()` validates key availability, falls back to current provider with WARNING |
| Config complexity for users | Adoption barrier | Ship with 4 example presets, `enabled: false` default, existing behavior unchanged |
| Session messages grow with multi-model overhead | Token budget pressure | Planner summaries should be concise; consider pruning planner messages before coder |

---

## What NOT to Build

1. **No automatic prompt classification** in Phases 1-5
2. **No per-message model tracking** in session history (would require Message schema change)
3. **No parallel model calls** (ask 2 models same question, pick better answer)
4. **No VSCode/Web preset UI** initially (config-file + `/preset` command only)
5. **No cross-provider tool call forwarding** (tool results go back to the model that called them)
6. **No dynamic preset creation at runtime** (presets are config-only)

---

## Relationship to Existing Features

| Existing Feature | Relationship | Action |
|------------------|-------------|--------|
| `coding_model` config field | Replaced by `coder` role in presets | Keep as fallback when routing disabled |
| `/autoroute` command | Extended with preset info | Show routing status when enabled |
| `/provider` + `/model` commands | Still work for manual override | Override active for current role only |
| `EngineClient.set_provider()` | Internal use only when routing active | Public API unchanged |
| `ModelProfile` / `ToolCallingProfile` | Looked up per resolved model | No changes needed |
| AGENTS.md provider/model hints | Applied based on resolved model | No changes needed |

---

## Critical Files

| File | Phase | Change |
|------|-------|--------|
| `ppxai/engine/router.py` | 1 | NEW — all routing infrastructure |
| `ppxai/config/__init__.py` | 1 | Add `get_routing_config()`, preset validation |
| `ppxai-config.example.json` | 1 | Add `routing` section |
| `ppxai/engine/client.py` | 2-4 | Add `_router`, `_with_role()`, `_swap_provider()` |
| `ppxai/engine/chat.py` | 3 | Role-aware tool loop |
| `ppxai/commands/coding.py` | 2 | Use `router.resolve(RoutingRole.CODER)` |
| `ppxai/commands/routing.py` | 5 | NEW — `/preset`, `/route` commands |
| `tests/test_router.py` | 1 | NEW — router unit tests |

---

## k8s Deployment Considerations

The primary deployment target is the k8s-based ppxai (see `deploy/k8s/`). Routing
integrates with the multi-user architecture:

### Per-User Preset Selection

In k8s, each user gets a pod pair (webapp + server). The routing preset can be:
- **ConfigMap-driven**: Default preset in the namespace ConfigMap, user override via session
- **Login-gated**: Different presets based on user role (admin → dgx-hybrid, guest → budget)
- **Auto-detected**: Based on available backend endpoints (if DGX Spark is down, fall back)

### Provider Endpoint Discovery

In k8s, provider endpoints may be internal services rather than external URLs:
```json
{
  "providers": {
    "custom": {"base_url": "http://vllm-gpt-oss.ppxai.svc:8000/v1"},
    "asusai-vllm": {"base_url": "http://vllm-qwen3.ppxai.svc:8000/v1"}
  }
}
```

The `ProviderPool` should handle endpoint health checks — if a model endpoint is down,
the router falls back to the next available preset or single-model mode.

### Session Manager Integration

The k8s session manager (`deploy/k8s/session-manager/`) creates per-user pods. When
routing is enabled, the session manager should:
1. Include routing config in the pod's ConfigMap
2. Pre-warm the `ProviderPool` with providers from the active preset
3. Report active preset in session metadata (for the login dashboard)

---

## Open Questions

1. **Should presets allow partial role definitions?** E.g., only define `coder` and inherit
   the rest from the current provider/model. Simplifies config but adds ambiguity.

2. **How to handle cost tracking?** When multiple providers are used in one session,
   `/usage` must aggregate costs across all providers with correct pricing.

3. **Should the planner's output be summarized before passing to the coder?** Full
   planner output may contain reasoning traces that waste coder tokens.

4. **Should we support provider-specific AGENTS.md hints per role?** Currently hints
   are loaded for the active provider. With routing, the tools role may need different
   hints than the chat role even within the same preset.

5. **Web search routing?** When the user asks a web-search question and the active
   chat model doesn't have web search, should the router automatically switch to a
   web-capable model (perplexity/gemini)?
