# ADR 0015: Remove Perplexity as a chat provider

- **Status:** Accepted (2026-09-27): owner chose option B; release and window answered below
- **Deciders:** owner
- **Target:** v1.19.3, together with ADR 0014 and after it in commit
  order (owner, 2026-09-27).
- **Depends on:** ADR 0014. Perplexity grounding must run through the
  search layer before the chat provider can go.
- **Revises:** ADR 0012 in part (the facts table on the provider class,
  Perplexity on two wires). Design decision #6 in CLAUDE.md ("built-in
  providers") was already corrected in phase 1.

## Context

The owner decided on 2026-09-27, option B, that Perplexity stops being a
chat provider and stays as a web-search backend. The reasons were
measured:

- Perplexity's chat-completions API retired on 2026-09-27, leaving one
  Sonar id, `perplexity/sonar`, on the Responses wire.
- That id needed two wire fixes found the day before, both failing every
  affected turn (`1bafc270`): attachment part types, and three reserved
  tool names.
- Credits ran out during the smoke retest.
- The known issue stands: with tools on, it reaches for shell commands to
  get web data.

**Phase 1** (`a6500041`, on `bugfix/v1.19.3`, unreleased) removed nothing:

- Gemini is the default everywhere a default ships.
- Selecting Perplexity for chat warns and never raises (a promise made to
  ppxai-sre).
- `/doctor` flags a Perplexity default.
- The web_search backend stopped importing the provider class.

This record is **phase 2**: the removal.

## Decision

### 1. What is removed

- `PerplexityProvider` (`ppxai/engine/providers/perplexity.py`) and its
  registration in `providers/__init__.py`.
- The **gateway models** it served with a Perplexity key: `openai/*`,
  `anthropic/*`, `google/*`, `xai/*`, and the namespaced `perplexity/*` as
  a chat model. Users of those move to the vendor's own provider or
  OpenRouter.
- The `providers.perplexity` block in `ppxai-config.json`,
  `ppxai-config.example.json`, the configs `install.sh` and
  `scripts/install.ps1` generate, and VSCode's built-in `config.ts`.
- Chat-only data and code:
  - `PERPLEXITY_DEPRECATIONS` and `RECOMMENDED_DEFAULTS["perplexity"]` in
    `model_deprecations.py`;
  - the Perplexity chat system prompt (`config/prompts.py`);
  - the `perplexity:` hints section in `AGENTS.md`;
  - the `provider == "perplexity"` skip and `provider_excluded` entries in
    `web_premium.py`;
  - `_apply_oneshot_grounding`'s Perplexity branch;
  - phase 1's warn-on-select code.
- **About 13 test files** that exercise Perplexity as a chat provider (the
  list is in the phase-1 footprint, 2026-09-27); they are deleted or
  rewritten.

### 2. What stays

- The Perplexity **search backend** (ADR 0014 `search/` layer),
  `PERPLEXITY_API_KEY`, `tools.web_search.perplexity_model`, its search
  pricing (`tools.web_search.pricing.perplexity`), and its first place in
  the backend order.
- `providers/perplexity_facts.py`, shrunk to the rows the search backend
  needs: the Responses-wire fact for `perplexity/sonar`. It moves next to
  the backend under `engine/search/`.
- `ResponsesHandler`'s reserved-name aliasing (`1bafc270`). It is a
  generic mechanism; after removal no provider declares reserved names,
  and it stays for the next provider that does.

### 3. A config that still names Perplexity is refused, loudly

This is the trap to close. When a provider id is not registered,
`provider_ops.set_provider` falls back to a generic
`OpenAICompatibleProvider` for any `providers.<id>` block it finds. A
leftover `providers.perplexity` block, such as the owner's own
`~/.ppxai/ppxai-config.json` today, would therefore keep "working" against
the retired chat-completions endpoint and fail every turn with a 400.
Therefore:

- **`set_provider("perplexity")` returns False with a clear log line**,
  and never builds the generic fallback. It does not raise: a raise would
  fail every caller that selects the configured default at start-up
  (ppxai-sre's `initialize()`). It is the same False an unconfigured
  provider returns.
- **The server falls back to the next configured provider.** This is
  already built: `SessionManager._select_default_provider` tries the
  default, then each configured provider in file order.
- **`/doctor` says "removed" and names the fix** for a `default_provider`
  or `MODEL_PROVIDER` of `perplexity`, or a `providers.perplexity` block.
  Status is warning, not error: nothing else is broken.
- **Startup logs one warning** when the loaded config still carries the
  block, so a headless deployment sees it without running `/doctor`.
- The block is **ignored, not rewritten**. ppxai never edits an operator's
  config file.

### 4. Sessions that recorded Perplexity

`session_ops.restore_session` calls `set_provider(stored_provider)`. On
False, today it silently stays on the current provider and drops to that
provider's default model. That behaviour is right; the silence is not.
Restoring a session recorded on Perplexity keeps the history, lands on
the current provider, and says so once, in the restore result and as an
INFO event. The owner's `~/.ppxai/session-state.json` records
`provider: perplexity` today, so this is a real path, not a hypothetical.

### 5. Order of work

1. ADR 0014 lands: the search layer, then retrieval grounding.
2. Phase-1 warnings ship to users in a release (question 1).
3. This removal lands.
4. Before it merges, **ppxai-sre is told**: `set_provider("perplexity")`
   then returns False on any host still configured that way, and they have
   asked for time to add a seam test for it, as they did for
   `ModelSwitchInFlightError`.

## Why this and not the alternatives

- **Keep the chat provider, deprecated indefinitely.** Every future
  Responses-wire change, Perplexity API change or reserved name costs
  maintenance, for a provider the owner no longer wants for chat.
- **Remove it and let the generic fallback serve old configs.** That is
  the trap in Decision 3: it fails later, on every turn, with an HTTP 400
  that names nothing ppxai did.
- **Remove it and raise on select.** This breaks start-up for embedders
  that select the configured default, which is exactly what phase 1
  promised not to do.

## Owner answers (2026-09-27)

1. **No deprecation window.** Phase 1 and this removal ship together in
   v1.19.3, so operators meet the removal and the `/doctor` message at the
   same time. Phase 1's warn-on-select code therefore never ships. It is
   replaced by Decision 3's refusal before the tag, and the release notes
   describe one change, the removal, with its upgrade step.

## Implementation defaults (the owner may override)

- **Semver.** A clean break in a patch release, as ADR 0010 did in
  v1.19.1. The v1.19.3 release notes carry an upgrade step naming the
  replacement providers.
- **Gateway-model users.** `/doctor` names the vendor's own provider as the
  replacement for each `openai/*`, `anthropic/*`, `google/*` and `xai/*` id
  it finds in a leftover `providers.perplexity` block, noting that the
  Anthropic provider is opt-in and untested (Item 71).

## Triggers to revisit

- Perplexity restores a stable chat API with feature parity (tools,
  attachments) and the owner wants it back. That would be a new record
  adding a provider, not a revert of this one.
- The search backend needs something only the chat client provided, such
  as a Perplexity-only request option. It then belongs in the
  `SearchBackend` implementation, not a revived provider.
