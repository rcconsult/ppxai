# Pi coding agent vs ppxai — comparative notes

**Date:** 2026-06-18
**Status:** Reference (session research, source-verified via web)
**Related:** [2026-06-12-hermes-openclaw-reference.md](2026-06-12-hermes-openclaw-reference.md),
[../decisions/0003-agent-platform-architecture.md](../decisions/0003-agent-platform-architecture.md)

Recorded comparison of **Pi** (the open-source CLI coding agent by Mario
Zechner, in the Claude Code / OpenCode category) against **ppxai**. Prompted
by "how does this project compare with the Pi harness tool?"

## Source basis

- Author's own write-up: <https://mariozechner.at/posts/2025-11-30-pi-coding-agent/>
- Category placement: <https://github.com/bradAGI/awesome-cli-coding-agents>
- Three-way comparison (Claude Code vs Pi vs OpenCode): <https://yun123.io/en/blog/cli-coding-agents-comparison/>

Numbers below (≈46k GitHub stars, provider list, package count) are
as-of-search and move fast; the **architectural philosophy** contrast is the
durable takeaway. There are several tools loosely called "Pi" — this refers to
the TypeScript coding-agent monorepo, not the various π/Pi eval harnesses.

## The fundamental difference

They are **not the same kind of tool** despite both being terminal+LLM projects:

- **Pi is a coding agent** — point it at a repo; it reads/writes/edits/runs to
  do software-engineering tasks for one hands-on developer.
- **ppxai is a multi-provider chat UI + an emerging agent *platform*** —
  interactive chat across 4 clients, PLUS a server-side `/v1/agent/*` run
  registry that *other software* (e.g. ppxai-sre's outlook-monitor) calls as a
  governed backend.

Pi = a developer's hands-on tool. ppxai = chat-for-humans + an API-addressable,
governed agent backend for other services.

## Side by side

| Dimension | Pi | ppxai |
|---|---|---|
| Primary purpose | Hands-on coding agent | Multi-provider chat UI + agent platform/gateway |
| Language | TypeScript/Node monorepo (pi-ai, pi-agent-core, pi-tui, pi-coding-agent) | Python core; TS (VSCode), JS (web) clients |
| Architecture | 4 packages, one CLI | Engine → Server (FastAPI/SSE) → 4 clients (Rich TUI, Textual TUI, web, VSCode) |
| Philosophy | Minimal "Arch Linux": 4 tools (read/write/edit/bash), <1000-token prompt, "if I don't need it, it won't be built" | Batteries-included: file upload, office/PDF preview, /doctor, themes, command envelope, AppState sync |
| Sub-agents | **Rejected** as built-in (spawn via bash + tmux; externalize state to files) | **Built in**: `/v1/agent/task`, `spawn_subagent`, run registry, budgets/cancel |
| MCP | **Rejected** | Planned (v1.20.x), not yet integrated |
| Safety/sandbox | "Full YOLO" — "use a container if you need guardrails" | Consent gates, tool allowlist (AC-1), egress allowlist + SSRF guard (AC-2), bearer auth, pluggable secret sources |
| Providers | Anthropic, OpenAI, Google, xAI, Groq, Cerebras, OpenRouter, OpenAI-compat | Perplexity, Gemini, OpenAI, OpenRouter, vLLM/NIM/Ollama; Anthropic in progress |
| Headless/API | JSON streaming + RPC for the coding agent itself | Stable semver `POST /v1/oneshot` + `/v1/agent/*` as a gateway for OTHER services |
| Session model | continue/resume/branching, AGENTS.md context, HTML export, cost/token tracking, Claude OAuth | sessions + checkpoints, AppState sync, command envelope, multi-client |
| Maturity/reach | ≈46k stars, fast public OSS | Private project, 4 clients, ≈148k LoC |

## The sharpest contrast (relevant to v1.19.0)

Pi **deliberately rejects** exactly what ppxai v1.19.0 just *built*: sub-agents,
an orchestrated agent platform, and "safety theater." Pi's stance: externalize
state to files, use tmux, run in a container, frontier models are RL-trained so
don't over-instrument. ppxai's v1.19.0 went the opposite way — durable run
registry, capability/egress allowlists, per-run authz, secret sources, AppState
mirroring.

Neither is wrong — different **bets**:
- Pi optimizes for a single power-user developer wanting total transparency and
  control over one context window.
- ppxai's Stage-2 platform optimizes for *other software* needing an
  addressable, governed agent backend with security boundaries — which is
  precisely why it needs bearer auth, egress firewalls, and owner-scoped runs
  that Pi explicitly does NOT want.

This is the same design-space tension explored in the Hermes/OpenClaw research:
Pi sits at the **minimalist** extreme, ppxai's platform toward the
**governed-infrastructure** extreme.

## Ideas from Pi potentially worth borrowing

Not decisions — candidates to weigh against ppxai's goals (esp. the deferred
interactive sub-agent UX, debt 37m):

- **The 4-tool / minimal-prompt thesis** ("read/write/edit/bash is all you
  need; frontier models don't need long prompts"). Contrast with ppxai's
  per-provider system prompts + agent framing (§B). Worth A/B-testing whether a
  leaner agent prompt helps modern models.
- **tmux / externalize-state-to-files** as the sub-agent process model — a
  lighter alternative to a full orchestrated registry for the *interactive*
  (human-driven) case, even though the *programmatic* ppxai-sre case needs the
  governed registry.
- **Read-only mode via toolset restriction** (`--tools read,grep,find,ls`) —
  ppxai already has the grant mechanism (AC-1); a one-flag read-only preset for
  the clients could be a cheap UX win.

## Verdict

Same neighborhood (terminal + LLM + tools), different buildings. Pi is the
minimalist single-dev coding agent; ppxai is a multi-client chat product whose
v1.19.0 agent platform is purpose-built as governed infrastructure for other
software. Comparing them head-to-head as "coding agents" undersells ppxai's
gateway/platform half and overstates the overlap.
