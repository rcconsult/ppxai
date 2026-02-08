# client.py Import Dependency Diagrams

**Original:** 2026-01-17
**Updated:** 2026-01-18 (Post-refactoring)

---

# AFTER REFACTORING (v1.13.10)

## 1. What client.py DEPENDS ON (Post-Refactoring)

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
    │                                    (1,311 lines, was 2,037)                                          │
    │                                         FACADE ONLY                                                   │
    │                                                                                                       │
    └───────────────────────────────────────────────────────────────────────────────────────────────────────┘
           │              │              │               │              │               │
           │              │              │               │              │               │
           ▼              ▼              ▼               ▼              ▼               ▼
    ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌───────────┐  ┌──────────┐   ┌──────────────┐
    │ engine/  │   │ engine/  │   │  engine/  │   │  engine/  │  │  engine/ │   │   engine/    │
    │ types.py │   │session.py│   │context.py │   │providers/ │  │  tools/  │   │   chat.py    │
    │  (leaf)  │   │ (704 L)  │   │ (562 L)   │   │           │  │manager.py│   │   (NEW)      │
    └──────────┘   └──────────┘   └───────────┘   └───────────┘  └──────────┘   │   (433 L)    │
                                                        │               │       └──────────────┘
                                                        ▼               ▼               │
                                                  ┌───────────┐   ┌──────────┐          │
                                                  │ providers/│   │tools/    │          │
                                                  │ base.py   │   │base.py   │          │
                                                  └───────────┘   │parser.py │◄─────────┘
                                                                  │ (NEW)    │
                                                                  │ (308 L)  │
                                                                  │  LEAF    │
                                                                  └──────────┘

    ┌──────────────────────────────────────────────────────────────────────────────────────┐
    │                              CROSS-PACKAGE DEPENDENCIES                              │
    │                              (ALL TOP-LEVEL - no lazy imports!)                      │
    └──────────────────────────────────────────────────────────────────────────────────────┘
           │              │               │               │              │
           ▼              ▼               ▼               ▼              ▼
    ┌──────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐  ┌──────────┐
    │ config/  │   │checkpoint │   │ constants │   │  common/  │  │ prompts/ │
    │ (1247 L) │   │   .py     │   │   .py     │   │ consent.py│  │          │
    │          │   │ (479 L)   │   │  (leaf)   │   │ logger.py │  │          │
    │+defaults │   └───────────┘   └───────────┘   │+classify_ │  └──────────┘
    │  .py NEW │                                   │ shell_cmd │
    └──────────┘                                   └───────────┘
```

### New Extracted Modules

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                          EXTRACTED FROM client.py                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────────┐        ┌──────────────────────┐        ┌──────────────────────┐
    │  config/defaults.py  │        │  tools/parser.py     │        │  engine/chat.py      │
    │       (NEW)          │        │      (NEW)           │        │      (NEW)           │
    │                      │        │                      │        │                      │
    │  LEAF MODULE         │        │  LEAF MODULE         │        │  Uses ChatContext    │
    │  No ppxai imports    │        │  No ppxai imports    │        │  Protocol for DI     │
    │                      │        │  except Protocol     │        │                      │
    │  • Shell defaults    │        │  • parse_tool_call() │        │  • chat_simple()     │
    │  • Agent defaults    │        │  • Tool inference    │        │  • chat_with_tools() │
    │                      │        │  • JSON parsing      │        │  • ~433 lines        │
    │  ~65 lines           │        │  ~308 lines          │        │                      │
    └──────────────────────┘        └──────────────────────┘        └──────────────────────┘
           │                               │                               │
           ▼                               ▼                               ▼
    ┌──────────────────────────────────────────────────────────────────────────────────────┐
    │                                  client.py                                           │
    │                               (uses all three)                                       │
    └──────────────────────────────────────────────────────────────────────────────────────┘
```

### Import Summary Table (Post-Refactoring)

| Category | Module | Import Type | Lines | Change |
|----------|--------|-------------|------:|--------|
| **Engine (same package)** | `types.py` | Top-level | - | - |
| | `session.py` | Top-level | 704 | - |
| | `context.py` | Top-level | 562 | - |
| | `providers/` | Top-level | - | - |
| | `tools/manager.py` | Top-level | 447 | - |
| | `tools/parser.py` | Top-level | 308 | **NEW** |
| | `chat.py` | Top-level | 433 | **NEW** |
| **Cross-package** | `config/` | **Top-level** | 1,247 | ✅ No lazy |
| | `config/defaults.py` | Top-level | 65 | **NEW** |
| | `checkpoint.py` | **Top-level** | 479 | ✅ No lazy |
| | `constants.py` | Top-level | - | - |
| | `common/consent.py` | Top-level | 649 | ✅ +classify |
| | `prompts/` | Top-level | - | - |

**Key improvement:** All lazy imports eliminated. All imports are now top-level.

---

## 2. What DEPENDS ON client.py (Post-Refactoring)

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
    │                            EngineClient (1,311 lines)                                │
    │                                                                                      │
    │         Implements ChatContext Protocol for dependency injection                     │
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

    ┌──────────────────────────────────────────────────────────────────────────────────────┐
    │                    TOOLS (TYPE_CHECKING imports only)                                │
    │           These use TYPE_CHECKING to avoid runtime cycles                            │
    └──────────────────────────────────────────────────────────────────────────────────────┘
           │              │               │               │              │
           ▼              ▼               ▼               ▼              ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ editor.py    │ │filesystem.py │ │  shell.py    │ │container.py  │ │ __init__.py  │
    │              │ │              │ │              │ │              │ │ (builtin)    │
    │ if TYPE_     │ │ if TYPE_     │ │ if TYPE_     │ │ if TYPE_     │ │ if TYPE_     │
    │ CHECKING:    │ │ CHECKING:    │ │ CHECKING:    │ │ CHECKING:    │ │ CHECKING:    │
    │   import     │ │   import     │ │   import     │ │   import     │ │   import     │
    │   Engine     │ │   Engine     │ │   Engine     │ │   Engine     │ │   Engine     │
    │   Client     │ │   Client     │ │   Client     │ │   Client     │ │   Client     │
    └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
```

### Dependents Summary Table (Unchanged)

| Category | Module | Import Pattern | Usage |
|----------|--------|----------------|-------|
| **Package exports** | `engine/__init__.py` | `from .client import EngineClient` | Re-exports class |
| | `ppxai/__init__.py` | `from .engine import EngineClient` | Public API |
| **Server** | `server/http.py` | `from ..engine import EngineClient` | Creates instances |
| | `server/session_manager.py` | `from ..engine import EngineClient` | Creates instances |
| | `server/jsonrpc.py` | `from ..engine import EngineClient` | Creates instance |
| **Tools** | `tools/builtin/*.py` | `if TYPE_CHECKING: from ...client` | Type hints only |
| **Tests** | `test_engine_*.py` | `from ppxai.engine.client import EngineClient` | Direct testing |

---

## Comparison: Before vs After

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                               BEFORE REFACTORING                                        │
└─────────────────────────────────────────────────────────────────────────────────────────┘

                    client.py (2,037 lines)
                    ┌─────────────────────────────────────────┐
                    │  • Config loading (with lazy imports)   │
                    │  • Tool parsing (~250 lines)            │
                    │  • Shell classification (~40 lines)     │
                    │  • Chat simple (~80 lines)              │
                    │  • Chat with tools (~330 lines)         │
                    │  • Session wrappers                     │
                    │  • Checkpoint management                │
                    │  • Provider management                  │
                    │  • 5 LAZY IMPORTS inside methods        │
                    └─────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                               AFTER REFACTORING                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘

    config/defaults.py          tools/parser.py           engine/chat.py
    ┌───────────────┐          ┌───────────────┐         ┌───────────────┐
    │ 65 lines      │          │ 308 lines     │         │ 433 lines     │
    │ LEAF MODULE   │          │ LEAF MODULE   │         │ ChatContext   │
    │               │          │               │         │ Protocol      │
    │ Shell/Agent   │          │ parse_tool_   │         │               │
    │ defaults      │          │ call()        │         │ chat_simple() │
    └───────────────┘          │               │         │ chat_with_    │
           │                   │ Tool          │         │ tools()       │
           │                   │ inference     │         └───────────────┘
           │                   └───────────────┘                │
           │                          │                         │
           └──────────────────────────┼─────────────────────────┘
                                      │
                                      ▼
                         client.py (1,311 lines)
                         ┌─────────────────────────────────────────┐
                         │  FACADE PATTERN                         │
                         │  • ChatContext implementation           │
                         │  • Delegates to extracted modules       │
                         │  • Session/Checkpoint/Provider mgmt     │
                         │  • 0 LAZY IMPORTS                       │
                         └─────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────────────────────────────┐
    │  METRICS                                                                            │
    │                                                                                     │
    │  Lines: 2,037 → 1,311  (36% reduction, -726 lines)                                 │
    │  Lazy imports: 5 → 0   (100% eliminated)                                           │
    │  New modules: 3        (defaults.py, parser.py, chat.py)                           │
    │  Import cycles: Reduced (parser.py and defaults.py are LEAF modules)              │
    └─────────────────────────────────────────────────────────────────────────────────────┘
```

---

# ORIGINAL DIAGRAMS (Pre-Refactoring)

The following diagrams show the state BEFORE the refactoring for comparison.

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
