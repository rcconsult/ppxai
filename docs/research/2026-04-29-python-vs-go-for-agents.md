# Research note: Python vs Go (and where Zig/CGo fit) for ppxai-future

**Date:** 2026-04-29
**Status:** Research / exploratory — not a decision
**Triggered by:** discussion during the v1.18.2 release-evening session about
language choice for ppxai-sre and future autonomous agents
**Author:** Captured from a research conversation; not vetted against a build.

This is a research note, not an architecture decision record. It exists to
spare the next contributor from re-litigating the question from scratch
when "should we move from Python to Go/Rust/Zig" comes up — which it will,
because language choice is one of the perennial bikeshed prompts. The
answer here is **probably hybrid, not a rewrite**, and the reasoning is
laid out below.

If/when an actual decision is taken (e.g. "ppxai-sre starts in Go"), open
an ADR in `docs/decisions/` that references this note as the prior research.

## TL;DR

| Layer | Recommended language | Why |
|---|---|---|
| **ppxai** (interactive TUI/web/VSCode chat) | Python — keep | LLM SDK velocity, rapid prompt iteration, mature codebase |
| **ppxai-sre** (autonomous agents, k8s-scheduled) | Go — strong candidate | Long-running stability, concurrency, deployment shape |
| **Specific hot loops** (parsing, terminal rendering) | Zig/Rust if profiled-bottleneck | Almost never the actual bottleneck for agent work |
| **ppxai-server alone** (port HTTP layer in Go, keep engine in Python) | **Probably not worth it** — see §4 | Server is a thin wrapper; the operational characteristics live in the engine |

## 1. Reframe the question

"Python vs Go for ppxai's future" is too broad. The answer depends on
*which layer* of the system. The honest reframe:

- **ppxai itself** (the interactive client): Python is correct. The
  user-facing latency is dominated by LLM round-trips (~500ms–10s per
  call). Language choice for the orchestrator adds maybe 50ms in the
  worst case. PyInstaller binaries are clunky (50–60 MB, ~1s startup)
  but install once, run for hours. Rapid iteration on prompts, hint
  blocks, tool definitions matters more than steady-state efficiency.
- **Autonomous agents (ppxai-sre and similar)**: different operational
  shape — long-lived, often k8s-scheduled, possibly N concurrent
  instances. Different language might fit better.

## 2. Where Go wins for autonomous agents

Concrete operational characteristics that matter for ppxai-sre-style
work (long-lived, k8s-scheduled, possibly many concurrent):

| Dimension | Python (today) | Go (estimated) | Why it matters for agents |
|---|---|---|---|
| Binary size | 50–60 MB (our PyInstaller output) | 5–15 MB static | Faster pod cold starts, denser k8s scheduling |
| Startup time | ~500ms–1s | ~10–50ms | Crash recovery, pod restart speed |
| Memory baseline | ~80–120 MB resident | ~20–40 MB | 100 agents: 10 GB → 3 GB |
| Concurrency model | asyncio (I/O fine) + GIL (CPU limited) | goroutines + channels | Native fit for "supervise N tasks, drain results" |
| Long-process stability | GC pauses, memory bloat over days | Mature long-running profile | Reduces "reschedule the agent every 24h" hacks |
| Cross-compilation | Per-platform PyInstaller spec, painful | `GOOS=linux go build` single line | One CI matrix, multi-arch trivial |
| Static analysis | Limited (mypy partial) | Compiler catches more | Refactor confidence at week-1000 of agent runtime |

The two-week stable runtime profile is what matters most. Python
long-lived processes accumulate quirks (cyclic GC pressure, file
descriptor leaks, memory growth from cached data) that ops teams
paper over with periodic restarts. A Go binary doing the same workload
tends to stay flat.

## 3. Where Python wins (and why ppxai-sre might still pick Python)

| Dimension | Python | Go |
|---|---|---|
| LLM SDK first-class support | All of `anthropic` / `openai` / `google-genai` are Python-first | Anthropic Go SDK is 3rd-party; google-genai-go lags official Python |
| Tool-calling JSON parsing | dataclasses + Pydantic = 5 lines | struct tags + json.Unmarshal verbose |
| Iteration speed | Best for rapid prompt/tool/hint experimentation | Slower than Python for prototype |
| LLM-generated code quality | Models trained heavily on Python; output is better | Models are weaker at idiomatic Go (struct embedding, channel patterns) |
| Existing ppxai engine | 55k lines, mature, decomposed into ops modules | Would need full rewrite |
| Cross-language schema (`AppState`) | Works (we ship Python + JS + TS mirrors) | Add a 4th mirror, more drift risk |

The LLM-SDK lag is the single biggest argument for staying Python.
Anthropic ships features (extended thinking, prompt caching, citations,
file API) in their Python SDK first; Go often catches up weeks or months
later, sometimes never. For an agent that depends on cutting-edge LLM
features, you're trading framework velocity for runtime efficiency.

The LLM-generated-code factor is real but less discussed: if LLMs are
part of your dev loop (writing tests, scaffolding handlers, generating
provider adapters), Python output quality is meaningfully higher than Go.
The training-data skew is asymmetric and unlikely to flip soon.

## 4. The "port only the server to Go" middle path

The server is the most "infrastructure-shaped" component of ppxai —
long-lived, concurrent, less iteration-heavy than prompt-tuning code.
Tempting target. **Three sub-options exist; only one is worth the
effort, and only conditionally.**

### Option A — Pure HTTP shim in Go, Python keeps the engine

Go runs a thin reverse-proxy / SSE multiplexer. Every request crosses a
process boundary into a Python worker (gRPC or JSON-RPC over stdio).

| Pro | Con |
|---|---|
| Small Go binary | **Every request now requires IPC** |
| Fast startup | Python is still in the loop for actual work |
| Native SSE in Go | Two-process operability cost (logging, restart, observability) |
| | **Adds complexity without removing the Python long-process characteristics** that motivate the change |

**Verdict: not worth it for ppxai's single-user desktop case.** The user
runs one ppxai-server on their laptop. Two processes for one user is
over-engineering. The Python engine still has the GC behaviour and
memory profile you were trying to escape — you've just put a thin Go
HTTP layer in front of it.

### Option B — Port server *and* engine to Go (the meaningful commitment)

Port `ppxai/server/` AND `ppxai/engine/` together. TUI / web / VSCode
clients keep their language; wire protocol stays the same.

This is essentially **the "ppxai SDK extraction" conversation** from
the v1.18.2 session, but with Go-as-target instead of separately-released
Python package. Same scope, different language.

| Pro | Con |
|---|---|
| Real operational wins (memory, startup, stability) | 3+ months of work minimum |
| Single static binary with the actual logic | Lose Python LLM SDK velocity (the single biggest argument) |
| Goroutine-per-session is structurally cleaner than asyncio-per-session | Anthropic / Gemini features will lag |
| AppState pattern translates cleanly to Go channels | LLM-generated code quality drops |
| Protocol-DI (CommandContext, EngineClientProtocol) → Go interfaces, even cleaner | Cross-language schema (AppState JSON) gets a 4th mirror |

**Verdict: this is the real choice, not "server only".** If you're
porting the engine, the server comes with it for free (it's a thin
HTTP wrapper around engine calls). If you're not porting the engine,
porting just the server is rearranging the deck chairs.

### Option C — Side-car proxy pattern (Go in front of Python)

Go service in front of the Python server handles connection pooling,
rate limiting, structured observability, auth, k8s health probes.
Python server stays lean and focused on engine logic.

| Pro | Con |
|---|---|
| Best operational fit for **multi-tenant k8s** | Single-user desktop case doesn't justify it |
| Auth/rate-limit moves to Go layer (where it's faster) | More processes to operate |
| Python server stays simple | Local-dev story is harder (which port? which proxy?) |

**Verdict: only valuable for multi-tenant deployment.** ppxai is
predominantly single-user; the side-car pattern's operational wins
(connection pooling across users, fast health checks, ingress shape)
don't matter when there's one user. **If/when ppxai-sre runs as a
multi-tenant k8s service**, this becomes the natural shape — but
ppxai-sre might be the side-car, not need one.

### Server-port verdict summary

The server-only port has a structural problem: **the server is mostly
a thin wrapper around the engine.** Porting just the wrapper:
- Doesn't fix the engine's GC / memory characteristics (the actual
  operational pain).
- Adds a process boundary (IPC overhead).
- Couples two languages without gaining the benefits of either.

Either:
- Port server + engine together (Option B = "SDK extraction in Go") if
  the operational characteristics are the forcing function.
- Stay full-Python and accept the operational tax otherwise.
- Add a Go side-car if/when multi-tenant deployment becomes real.

## 5. Where Zig and CGo fit (probably nowhere yet)

**Zig:**
- No LLM SDKs at all. Would need to hand-write OpenAI/Anthropic API
  clients with HTTP and SSE parsing.
- Ecosystem cost is huge for what amounts to a 10–20% steady-state
  efficiency gain over Go.
- The only honest use case: writing the *agent runtime itself* (event
  loop, scheduler, syscall surface) where minimal overhead matters.
  ppxai-sre is high-level orchestration, not runtime kernel work.
- Revisit when Zig 1.0 ships AND an Anthropic-equivalent SDK exists.

**CGo:**
- Relevant only if you embed a specific C library from Go (tree-sitter,
  libgit2, ggml, llama.cpp). For ppxai-sre's task shape — drive remote
  LLM APIs, run shell tools, maintain state — there's no obvious C lib
  you'd reach for.
- CGo is a tax: context switch per call, slower compile, more complex
  build. Don't pay it speculatively.
- **If you're doing on-device inference** (running llama.cpp locally
  as part of an agent), CGo or pure-Rust bindings become real. That's
  a different product than ppxai-sre as currently scoped.

## 6. Hybrid recommendation if ppxai-sre becomes the forcing function

**Go for ppxai-sre, Python for ppxai. Treat them as separate products
with a stable wire protocol (HTTP/SSE/gRPC) between them.**

Why this shape works:

1. **ppxai-sre's value is operational characteristics** (concurrent
   agent supervision, long-running stability, dense k8s packing). Go
   delivers those structurally; Python papers over them with periodic
   restarts and overprovisioning.
2. **ppxai's value is interactive feedback loops** (rapid prompt
   tuning, fast iteration on tool/hint blocks). Python delivers those
   structurally; Go would slow you down.
3. **The bridge is a wire protocol you already have** — ppxai's
   HTTP+SSE server is the proven seam. ppxai-sre can be a Go service
   that talks to ppxai's engine over the same protocol, OR runs its
   own engine that mirrors the interface.

### Migration path if you go this route

| Phase | Scope | Effort |
|---|---|---|
| 1 | Define ppxai-sre's protocol surface (LLM-call request + response + tool-call envelope) | 1–2 weeks; reuses learnings from ppxai's CommandContext / AppState patterns |
| 2 | Pick Go LLM library/libraries that meet your model coverage | Audit week — pin known-good versions per provider |
| 3 | Implement core agent loop + tool dispatch in Go | 3–4 weeks |
| 4 | Port one or two real agents from Python prototype to Go | 2 weeks |
| 5 | Operational comparison (memory, startup, stability over 30 days) | 1 month observation |

Total: ~3 months to a defensible "is this worth it?" answer. If yes,
scale up; if no, stay Python and accept the operational tax.

The 30-day operational comparison is the load-bearing step. Without
it, the choice is aesthetic ("Go feels right for ops") rather than
data-driven. With it, the team has a real benchmark.

## 7. What NOT to do

1. **Rewrite ppxai in Go.** Bad ROI. The codebase is mature; the win
   is real but small (faster startup, smaller binaries) and the cost
   is enormous (lose ecosystem velocity, drag features behind Python
   releases). The fact that v1.18.2 shipped with 11 closed debt items
   in one evening is evidence of Python's iteration value at this
   stage of the project.
2. **Adopt Zig anywhere.** The ecosystem isn't there for agent work.
   Revisit when Zig 1.0 ships and a usable Anthropic SDK exists.
3. **Use CGo speculatively.** Only when there's a specific C library
   you've identified as load-bearing.
4. **Port "just the server" as a half-measure.** §4 above — this
   doesn't actually fix the operational characteristics that motivate
   the change.
5. **Treat this as urgent.** Python is working. The real forcing
   function is "ppxai-sre needs operational characteristics Python
   can't easily give us" — and that's measurable, not philosophical.

## 8. Triggers to revisit this analysis

- **ppxai-sre needs to scale beyond ~10 concurrent agents on a single
  node** — Python's memory baseline becomes a real ops cost.
- **Anthropic / OpenAI / Google ship a Go SDK with feature parity to
  Python** — the biggest argument against Go evaporates.
- **k8s deployment of ppxai-sre becomes multi-tenant** — Option C
  side-car becomes natural.
- **A specific Python long-running stability incident** (memory leak
  taking down agents weekly, GC pause causing missed heartbeats) makes
  the operational tax visible to ops, not just to a research note.
- **Zig 1.0 ships with a usable LLM SDK** — re-evaluate Zig for
  performance-critical sub-components (low probability before 2027).

## 9. References / related work

- `docs/decisions/0002-command-context-three-pattern-split.md` — the
  three-pattern split (Pattern A proxy / Pattern B explicit / no
  adapter) translates cleanly to Go interfaces if/when ported.
- `docs/archive/DEBT-INVENTORY-v1.18.2.md` Item 14 (Anthropic provider
  with TOS-aware auth fallback) — pure Python work; would need separate
  Go-side equivalent if Option B is taken. (Item moved to ROADMAP v1.19.x
  on 2026-05-05; original entry preserved in archive snapshot.)
- `memory/release-lessons.md` — captures the operational pain points
  of Python long-running processes (PyInstaller silent module drop,
  binary metadata staleness).
- The "ppxai SDK extraction" discussion in the v1.18.2 session
  (2026-04-28 conversation) — Option B in this note is the same scope
  with Go-as-target instead of separately-released Python package.

## 10. Open questions for the team

1. **Is ppxai-sre a multi-tenant service or per-user binary?** The
   answer changes which language characteristics matter most.
2. **What's the expected concurrency profile?** 1–5 agents on a laptop
   vs 50–100 agents in a k8s cluster have different language fits.
3. **Are there specific LLM features you depend on that aren't in Go
   SDKs today?** (Anthropic prompt caching, citations, extended
   thinking). If yes, Go cuts you off from those features.
4. **What's the on-device inference roadmap?** If "no, always remote
   APIs" — Go is the answer for ops-heavy work. If "yes, local
   llama.cpp" — Rust or Go+CGo become real choices.
5. **Who maintains the agents long-term?** A team with strong Go
   experience makes Go a natural fit; a team comfortable in Python
   pays the operational tax to keep iteration speed.

The answer to question 1 is the most consequential. Settle that first
before re-opening this research.
