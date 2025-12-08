# Alternatives Considered

This document captures architectural decisions and alternatives that were evaluated but not adopted for the ppxai project. It serves as a reference for future contributors to understand why certain technologies were chosen.

**Last Updated:** December 9, 2025

---

## Bun Runtime for JavaScript/TypeScript

**Evaluated:** December 2025
**Decision:** Not adopted
**Reason:** No significant benefit for current architecture

### What is Bun?

Bun is a fast JavaScript runtime and toolkit that offers:
- Faster execution than Node.js
- Built-in bundler, test runner, package manager
- Native TypeScript support (no compilation step)
- Fast startup times
- Drop-in Node.js compatibility (mostly)

### Current Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Clients (UI Layer)                           │
├─────────────────┬─────────────────┬─────────────────────────────┤
│  TUI (Python)   │ VS Code Ext     │  Web UI (Browser JS)        │
│  Rich library   │ (TypeScript)    │  HTML + SSE client          │
└────────┬────────┴────────┬────────┴────────────┬────────────────┘
         │                 │                     │
         │                 ▼                     │
         │    ┌─────────────────────────┐        │
         └───►│   HTTP Server (Python)  │◄───────┘
              │   FastAPI + uvicorn     │
              └───────────┬─────────────┘
                          │
                          ▼
              ┌─────────────────────────┐
              │    EngineClient         │
              │    (Python)             │
              │    • Providers (OpenAI) │
              │    • Tools              │
              │    • Sessions           │
              └─────────────────────────┘
```

### Analysis

| Component | Current | Bun Alternative | Benefit? |
|-----------|---------|-----------------|----------|
| VS Code Extension | TypeScript → Node.js | **Can't use Bun** | ❌ VS Code requires Node.js runtime |
| Extension Build | npm + tsc + vsce | Bun build | ⚠️ Marginal - faster builds, but npm ecosystem integration better |
| HTTP Server | Python FastAPI | Bun server (Elysia/Hono) | ❌ Would require rewriting Python engine in TS |
| Web UI | Browser JS | Same | ❌ No change - browser doesn't use Bun |
| TUI | Python Rich | Node.js Ink | ❌ Would lose Python ecosystem benefits |

### Why Bun Doesn't Add Value

#### 1. VS Code Extension Runtime Constraint

VS Code extensions **must** run in VS Code's embedded Node.js runtime. Bun cannot be used as the runtime for extensions.

```typescript
// VS Code extensions MUST run in VS Code's embedded Node.js
// Bun cannot be used as the runtime
export function activate(context: vscode.ExtensionContext) {
    // This runs in Node.js, not Bun
}
```

#### 2. Python Backend is Core Strength

The Python backend provides significant advantages:

- **OpenAI SDK**: First-class Python support with excellent async handling
- **Provider ecosystem**: anthropic, google-generativeai, and other AI SDKs are Python-native
- **PyInstaller bundling**: Essential for v1.10.0 self-contained extension distribution
- **Tool system**: Python's flexibility for shell commands, file operations, etc.
- **Rich TUI library**: Excellent terminal UI capabilities

#### 3. Complexity vs Benefit

Adding Bun would mean:
- Two runtimes to maintain (Python + Bun)
- Rewriting HTTP server and potentially the engine
- Different toolchain for extension builds
- More CI complexity
- Risk of compatibility issues

#### 4. Current Roadmap Already Addresses Performance

| Concern | Solution in Roadmap |
|---------|---------------------|
| Build speed | v1.9.0: `uv` (15x faster than pip) |
| Server performance | v1.9.0: FastAPI + uvicorn (async, optimized) |
| Extension bundling | v1.10.0: esbuild via vsce (already fast) |
| Latency | v1.9.0: SSE streaming (3-10x improvement) |

### Scenarios Where Bun Would Help

Bun could be beneficial if:

1. **Building a standalone Node.js CLI tool** - Not applicable; TUI is Python-based
2. **Server-side JavaScript application** - Not applicable; server is Python FastAPI
3. **Monorepo with multiple JS packages** - Not applicable; only one TS package (extension)
4. **Replacing npm for faster installs** - Marginal benefit; vsce still uses npm ecosystem

### Conclusion

The current architecture with **Python + TypeScript** (compiled to JS for VS Code) is well-suited for this project:

- **Python** excels at AI/ML integration, tooling, and the core engine
- **TypeScript** is required for VS Code extensions (runs in Node.js)
- **Browser JS** for web UI doesn't need a server-side runtime

The v1.9.0 `uv` migration already provides 15x speedup for Python dependencies. For the extension, `esbuild` (used by vsce) is already very fast.

---

## Other Alternatives (Future Reference)

### Tauri vs Electron (for Desktop App)

**Status:** Not evaluated yet
**Relevance:** Would apply if building a standalone desktop app instead of VS Code extension

### Deno vs Node.js

**Status:** Not evaluated
**Relevance:** Same constraints as Bun - VS Code requires Node.js

### Alternative Python HTTP Frameworks

| Framework | Considered | Notes |
|-----------|------------|-------|
| FastAPI | ✅ Adopted | Best async support, automatic OpenAPI docs |
| Flask | ❌ | Synchronous, less suitable for SSE |
| Django | ❌ | Too heavy for API server |
| Starlette | ❌ | FastAPI is built on it, adds conveniences |
| aiohttp | ❌ | Lower-level than FastAPI |

FastAPI was chosen for v1.9.0 because:
- Native async/await support
- Excellent SSE streaming via `StreamingResponse`
- Automatic request validation with Pydantic
- Built-in OpenAPI documentation
- Large ecosystem and community

---

## Document History

| Date | Change |
|------|--------|
| 2025-12-09 | Initial document with Bun analysis |
