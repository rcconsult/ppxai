# MCP is not integrated in ppxai (verified 2026-05-23)

**TL;DR:** ppxai has three filename-level breadcrumbs that look like
MCP support but isn't. The integration is planned for v1.20.x, not
shipped. Authoritative plan: [`../mcp-integration-plan.md`](../mcp-integration-plan.md).

**Verify with:**
```bash
# Confirm zero MCP imports across production code:
grep -r "from mcp\|import mcp" ppxai/

# Confirm tool_manager has no extension point for non-builtin sources:
grep -n '"source"' ppxai/engine/tools/manager.py
```

The first returns nothing. The second shows
`tool_manager.py:193` hardcodes `"source": "engine"` with no
extension point for non-builtin tool sources.

## Why this trips people up

Three filename-level signals make ppxai look MCP-enabled:

1. **`pyproject.toml` declares `mcp>=0.1.0` under `[project.optional-dependencies.mcp]`** —
   but the venv doesn't install it by default; `import mcp` raises
   `ModuleNotFoundError` in a fresh sync. The extra is documented
   intent, not shipped functionality.

2. **`.mcp.json` at repo root** lists `code-review-graph` as if it
   were a wired MCP server config. It's a placeholder. **Zero Python
   code in `ppxai/` loads it** — verified by grep across the whole
   tree.

3. **`tests/test_mcp.py`** exists. It's a *diagnostic script* — "can
   my host run MCP?" — not an integration test against ppxai's MCP
   wiring (which doesn't exist to test).

A reader who sees any of these and concludes "MCP is supported" will
build downstream code against a feature that isn't there.

## What's actually true

- The old `tool_manager.py` MCP loader from pre-v1.11.7 was **deleted**
  in v1.11.7. There has been no in-tree MCP code since.
- `ppxai/engine/tools/manager.py:193` hardcodes `"source": "engine"`
  with no extension point. External tool sources (MCP servers,
  ppxai-sre's `tools_adapter.py` workaround, etc.) have no public
  way to surface tools through the engine today.
- The MCP integration plan ([`../mcp-integration-plan.md`](../mcp-integration-plan.md),
  ~500 lines, committed 2026-05-23) enumerates 17 missing pieces
  across engine / slash command / UI / security / config layers, and
  a 5-phase implementation breakdown (~6-8d total).
- Implementation branch `feat/mcp-integration-day-0` is reserved
  but not opened. v1.20.x is gated on v1.19.x agent-platform Stage 2
  + credential broker landing first (credential broker is the natural
  partner for MCP's per-server env-var handling).
- The peer `ppxai-sre/agents/outlook-monitor`'s `ppxai-outlook-agent
  mcp` POC is the Day-0 consumer driving the design.

## Generalization — the filename-as-evidence trap

Three signal classes that mislead similarly:

| Signal | What it actually means |
|---|---|
| Optional-extras in `pyproject.toml` | Intent / planned dependency. Not implementation. |
| Config files at repo root (`.<thing>.json`) | Placeholder or external-tool config. Verify with grep that any Python code loads it. |
| `tests/test_<thing>.py` | Could be integration test, could be diagnostic script, could be skipped scaffold. Open the file. |

When asked "does ppxai support X?", grep these in order:

1. **Actual imports in `ppxai/`** — `grep -r "from X import\|import X" ppxai/`.
   Zero hits = not implemented, regardless of dep declaration.
2. **Concrete dispatch sites** — search for the symbol being WIRED
   into the tool manager / engine / etc., not just defined somewhere.
3. **`ROADMAP.md`** for the v1.X.x slot it's planned for. A "planned"
   entry means the answer is "no, scheduled for v1.X.x".
4. **Filename-level evidence is INTENT, not shipped state.** Treat
   as TODO indicators.

## Related

- [`../mcp-integration-plan.md`](../mcp-integration-plan.md) — the
  full v1.20.x plan + verified-state section
- [`../../ROADMAP.md`](../../ROADMAP.md) §"v1.20.x — MCP integration
  Day-0 (planned)"
- Same failure class as the import-surface heuristic: see the parallel
  ppxai-sre agent's first-pass v1.18.6 impact analysis (2026-05-15)
  that incorrectly concluded "ADR 0006 outside SRE's import surface,
  no SRE code change needed" — technically true but missed the
  strategic framework foundation. The corrective discipline lives in
  per-host memory (`feedback_read_files_dont_infer.md`).
