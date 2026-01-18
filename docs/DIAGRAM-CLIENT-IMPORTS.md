# client.py Import Dependency Diagrams

**Generated:** 2026-01-17

---

## 1. What client.py DEPENDS ON (Imports)

```
                              ┌─────────────────────────────────────────────────────────┐
                              │              PYTHON STDLIB (leaf)                       │
                              │  asyncio, hashlib, json, re, datetime, pathlib, typing  │
                              │                   dataclasses                           │
                              └─────────────────────────────────────────────────────────┘
                                                        ▲
                                                        │
    ┌───────────────────────────────────────────────────┴───────────────────────────────────────────────────┐
    │                                                                                                       │
    │                                      ppxai/engine/client.py                                          │
    │                                         (2,037 lines)                                                 │
    │                                                                                                       │
    └───────────────────────────────────────────────────────────────────────────────────────────────────────┘
           │              │              │               │              │               │
           │              │              │               │              │               │
           ▼              ▼              ▼               ▼              ▼               ▼
    ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌───────────┐  ┌──────────┐   ┌──────────────┐
    │ engine/  │   │ engine/  │   │  engine/  │   │  engine/  │  │  engine/ │   │   engine/    │
    │ types.py │   │session.py│   │context.py │   │providers/ │  │  tools/  │   │ tools/       │
    │  (leaf)  │   │ (704 L)  │   │ (562 L)   │   │           │  │manager.py│   │ builtin/     │
    └──────────┘   └──────────┘   └───────────┘   └───────────┘  └──────────┘   └──────────────┘
                                                        │               │               │
                                                        ▼               ▼               │
                                                  ┌───────────┐   ┌──────────┐          │
                                                  │ providers/│   │tools/    │          │
                                                  │ base.py   │   │base.py   │          │
                                                  └───────────┘   └──────────┘          │
                                                                                        │
    ┌───────────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
    ┌──────────────────────────────────────────────────────────────────────────────────────┐
    │                              CROSS-PACKAGE DEPENDENCIES                              │
    └──────────────────────────────────────────────────────────────────────────────────────┘
           │              │               │               │              │
           ▼              ▼               ▼               ▼              ▼
    ┌──────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐  ┌──────────┐
    │ config/  │   │checkpoint │   │ constants │   │  common/  │  │ prompts/ │
    │ (1247 L) │   │   .py     │   │   .py     │   │ logger.py │  │          │
    │          │   │ (479 L)   │   │  (leaf)   │   │           │  │          │
    └──────────┘   └───────────┘   └───────────┘   └───────────┘  └──────────┘
         │
         ▼
    ┌──────────────────────────────────────────────────────────────────────────────────────┐
    │                           LAZY IMPORTS (inside methods)                              │
    │                                                                                      │
    │  Line 114:  from ..config import PROVIDERS, get_api_key, get_base_url, ...          │
    │  Line 753:  from ..checkpoint import FileCheckpointBackend                          │
    │  Line 1258: from ..config import get_system_prompt, get_system_prompt_mode          │
    │  Line 1903: from ..config import EXPORTS_DIR                                        │
    │  Line 1979: from ..config import get_model_context_limit                            │
    └──────────────────────────────────────────────────────────────────────────────────────┘
```

### Import Summary Table

| Category | Module | Import Type | Lines |
|----------|--------|-------------|------:|
| **Engine (same package)** | `types.py` | Top-level | - |
| | `session.py` | Top-level | 704 |
| | `context.py` | Top-level | 562 |
| | `providers/` | Top-level | - |
| | `tools/manager.py` | Top-level | 447 |
| | `tools/builtin/` | Top-level | - |
| **Cross-package** | `config/` | Top + Lazy | 1,247 |
| | `checkpoint.py` | Top + Lazy | 479 |
| | `constants.py` | Top-level | - |
| | `common/logger.py` | Top-level | - |
| | `prompts/` | Top-level | - |

---

## 2. What DEPENDS ON client.py (Who Imports It)

```
    ┌──────────────────────────────────────────────────────────────────────────────────────┐
    │                                    TESTS                                             │
    │                           (direct import for testing)                                │
    └──────────────────────────────────────────────────────────────────────────────────────┘
           │              │               │               │
           ▼              ▼               ▼               ▼
    ┌──────────────┐ ┌───────────────┐ ┌────────────────┐ ┌───────────────────┐
    │test_engine_  │ │test_engine_   │ │test_engine_    │ │test_context_      │
    │context.py    │ │streaming.py   │ │tool_parsing.py │ │injection.py       │
    └──────────────┘ └───────────────┘ └────────────────┘ └───────────────────┘
           │              │               │               │
           └──────────────┴───────────────┴───────────────┘
                                    │
                                    ▼
    ┌──────────────────────────────────────────────────────────────────────────────────────┐
    │                                                                                      │
    │                              ppxai/engine/client.py                                  │
    │                                  EngineClient                                        │
    │                                                                                      │
    └──────────────────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │
           ┌────────────────────────┼────────────────────────┐
           │                        │                        │
           │                        │                        │
    ┌──────┴──────┐          ┌──────┴──────┐          ┌──────┴──────┐
    │   engine/   │          │   ppxai/    │          │   server/   │
    │ __init__.py │          │ __init__.py │          │             │
    │  (exports)  │          │  (exports)  │          │             │
    └─────────────┘          └─────────────┘          └─────────────┘
                                                             │
                             ┌───────────────────────────────┼───────────────────────────────┐
                             │                               │                               │
                             ▼                               ▼                               ▼
                      ┌─────────────┐              ┌──────────────────┐             ┌──────────────┐
                      │  http.py    │              │session_manager.py│             │  jsonrpc.py  │
                      │ (2,247 L)   │              │    (467 L)       │             │   (200 L)    │
                      │             │              │                  │             │              │
                      │ FastAPI     │              │ Creates          │             │ Creates      │
                      │ endpoints   │              │ EngineClient     │             │ EngineClient │
                      │             │              │ instances        │             │ instance     │
                      └─────────────┘              └──────────────────┘             └──────────────┘
                             │                               │                               │
                             │                               │                               │
                             ▼                               ▼                               ▼
    ┌──────────────────────────────────────────────────────────────────────────────────────────────┐
    │                                      FRONTENDS                                               │
    │                                                                                              │
    │     VSCode Extension (TypeScript)        TUI (main.py)         Web App (JavaScript)         │
    │     Uses HTTP API                        Uses EngineClient     Uses HTTP API                 │
    │                                          directly              via ppxai-server              │
    └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Dependents Summary Table

| Category | Module | Import Pattern | Usage |
|----------|--------|----------------|-------|
| **Package exports** | `engine/__init__.py` | `from .client import EngineClient` | Re-exports class |
| | `ppxai/__init__.py` | `from .engine import EngineClient` | Public API |
| **Server** | `server/http.py` | `from ..engine import EngineClient` | Creates instances |
| | `server/session_manager.py` | `from ..engine import EngineClient` | Creates instances |
| | `server/jsonrpc.py` | `from ..engine import EngineClient` | Creates instance |
| **Tests** | `test_engine_*.py` | `from ppxai.engine.client import EngineClient` | Direct testing |

---

## Key Observations

### 1. Client is a Facade
- EngineClient is the **main entry point** for all engine functionality
- All servers (HTTP, JSON-RPC) create EngineClient instances
- It aggregates: providers, tools, session, context, checkpoint

### 2. Dependency Direction
```
config/ ──────────────────────────────────────┐
constants.py ─────────────────────────────────┤
common/ ──────────────────────────────────────┤
checkpoint.py ────────────────────────────────┼───► client.py ───► server/
engine/session.py ────────────────────────────┤                   (http, jsonrpc)
engine/context.py ────────────────────────────┤
engine/tools/ ────────────────────────────────┤
engine/providers/ ────────────────────────────┘
```

### 3. Lazy Imports = Potential Circular Risk
The 5 lazy imports inside methods suggest these were added to avoid import cycles:
- `config/` has multiple lazy imports (4 locations)
- `checkpoint.py` has 1 lazy import

### 4. Refactoring Impact
Changing client.py affects:
- **3 server modules** (http.py, session_manager.py, jsonrpc.py)
- **4+ test files**
- **2 package __init__.py files** (public API)

The public interface (`EngineClient` class) must remain stable.
