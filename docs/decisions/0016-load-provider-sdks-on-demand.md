# ADR 0016: Load provider SDKs on demand, through the provider factory

- **Status:** Implemented (2026-10-20, all six steps; measured under "Expected effect"). Accepted 2026-10-11: owner answered all four open questions, below. Steps 1–2 landed on `feature/v1.19.5` (2026-10-13), step 3 on 2026-10-19, step 4 on 2026-10-20, step 5 on 2026-10-20 with a narrowed server-probe fence (§7 note; owner accepted ~1.8 s probes 2026-10-20); step 6 (re-measure) on 2026-10-20
- **Deciders:** owner
- **Target:** v1.19.5 (owner, 2026-10-11). Not part of v1.19.4.
- **Amends:** the project's no-lazy-imports rule
  (`docs/patterns/protocol-dependency-inversion.md`,
  `tests/test_no_new_lazy_imports.py`). It adds one named exception: a
  declared registry loaded through one factory.
- **Related:** debt Item 83 (the suite got slower; one root cause is this
  import cost), ADR 0012 (per-model facts on the provider class), ADR 0013
  (the SSH hub, whose remote probes pay this cost on every call), ADR 0015
  (Perplexity removed; its module is still named in two PyInstaller specs).

## Context

The owner asked on 2026-10-11, while root-causing a flaky SSH-launcher
test: why do we load every provider SDK when the configuration says which
provider is in use? There is a factory (`create_provider`), so loading
could happen when a provider is actually created, with a "loading…"
message at that moment.

### What loads today, and why

Measured on the macOS dev host (`python -X importtime`, cumulative, one
cold interpreter each; bare `python -c pass` is 0.04 s):

| Import | Cost |
|---|---|
| `import ppxai.version` | 2.37 s wall |
| `ppxai` package | 2.07 s, of which `ppxai.engine.providers` is 1.78 s |
| `ppxai.server.http` | 2.81 s |
| `ppxai.config` | 0.08 s |
| `openai` alone | 0.71 s |
| `anthropic` alone | 0.97 s |
| `google.genai` alone | 0.77 s |
| `fastapi` alone | 0.46 s |

The SDK figures overlap (they share `httpx` and `pydantic`), so they don't
add up; the provider package's 1.78 s is the combined cost.

Three layers of eager imports load every SDK, whatever the config says:

1. **The registry imports every implementation to register it.**
   `ppxai/engine/providers/__init__.py` imports the Anthropic, Gemini,
   OpenAI-native and OpenAI-compatible modules at package import, then
   calls `register_provider(...)`. `create_provider()` exists, but it only
   looks a class up in a dict that was already filled.
2. **`providers/base.py` imports the OpenAI SDK for every provider.** It
   uses `openai.NOT_GIVEN`, constructs `OpenAI(...)` in `__init__`, and maps
   `openai.*Error` classes. A Gemini or Anthropic session pays for the
   OpenAI SDK because the shared base class is the OpenAI wire's.
3. **`ppxai/__init__.py` re-exports `EngineClient`.** Any `ppxai.*` import
   loads the engine, so `import ppxai.version` costs 2.37 s. This is what a
   remote `ppxai-server --version`, `--registry-contract` or
   `--list --json` pays, about 3.2 s each, every time the SSH Launcher lists
   or launches (ADR 0013).

Three engine modules also name `OpenAICompatibleProvider` directly:
`provider_ops.py` (the fallback for an unregistered name),
`facts_resolver.py` (the fallback class) and `server/routes/oneshot.py`.

### Who reads provider classes without creating a provider

ADR 0012 put per-model facts on the provider class: `shipped_model_facts`,
`default_capabilities`, `unmeasured_facts`, `default_model_for_facts`.
They are read **without an instance** through `get_provider_class()`:

- `engine/facts_resolver.py` (capabilities and facts for any provider);
- `engine/task_authorizer.py:1035` (suggesting tool-capable models in a
  refusal);
- `commands/provider.py:330` (`/provider` listing).

So deferring the module import alone would move the SDK load into
`/provider`, `/doctor` and `/task` authorization for providers nobody is
using. The facts are data; they have to stop living next to the SDK
import.

### What is already SDK-free

The four wire handlers (`providers/wire/`) import no SDK. The search layer
imports `openai` only in `engine/search/perplexity.py`.

### Who would notice

- **ppxai-sre** imports `ppxai.engine.*` and `ppxai.config.*` only (pinned
  in `tests/test_consumer_import_surface.py`); nothing in their tree uses
  `from ppxai import …`. Checked 2026-10-11. **But their binaries are
  affected:** ppxai-sre's three PyInstaller specs
  (`agents/{cert-monitor,incident-responder,outlook-monitor}/*.spec`) name
  `ppxai.engine.providers`, `.base`, `.openai_compat` and `.gemini` as
  hiddenimports, and not `.openai_native` or `.anthropic` (reported by
  ppxai-sre, 2026-10-11). Like ours, that only works because of the static
  imports.
- **PyInstaller.** The binaries find modules by following static imports.
  `ppxai.spec` and `ppxai-server.spec` already list
  `ppxai.engine.providers.perplexity`, deleted by ADR 0015, and omit
  `openai_native` and `anthropic`. That is harmless only because the
  static imports pull those in. Once loading is dynamic, a missing entry
  breaks a binary at provider-switch time.

## Decision

### 1. The registry is data

`providers/__init__.py` holds a declared table instead of importing
implementations:

```python
_PROVIDER_MODULES: dict[str, tuple[str, str]] = {
    "openai":    ("ppxai.engine.providers.openai_native", "OpenAINativeProvider"),
    "gemini":    ("ppxai.engine.providers.gemini",        "GeminiProvider"),
    "anthropic": ("ppxai.engine.providers.anthropic",     "AnthropicProvider"),
    "local":     ("ppxai.engine.providers.openai_compat", "OpenAICompatibleProvider"),
    "custom":    ("ppxai.engine.providers.openai_compat", "OpenAICompatibleProvider"),
}
#: Any configured name not in the table (openrouter, nvidia, ollama, ...).
_FALLBACK = ("ppxai.engine.providers.openai_compat", "OpenAICompatibleProvider")
```

This mirrors `_BUILTIN_COMMAND_MODULES` in `commands/factory.py`, which
already loads command modules through `importlib.import_module` in one
place (`CommandFactory._ensure_loaded`).

### 2. One load point

`load_provider_class(name)` is the only function that imports a provider
module: `importlib.import_module` and `getattr`, cached per process.
`create_provider()` and `get_provider_class()` go through it. The
unregistered-name fallback moves inside it, so `provider_ops.py`,
`facts_resolver.py` and `oneshot.py` stop importing
`OpenAICompatibleProvider` by name.

A Gemini SDK missing behind `"gemini"` keeps today's behaviour (fall back
to the OpenAI-compatible class), decided at load time.

### 3. Facts move to SDK-free modules

Each provider's class-level facts (`shipped_model_facts`,
`default_capabilities`, `unmeasured_facts`, `default_model_for_facts`)
move to a data module with no SDK import, e.g.
`ppxai/engine/providers/facts/<provider>.py`. The provider class keeps the
same attribute names, assigned from that module, so ADR 0012's resolution
order and every reader stay as they are.

`get_provider_facts(name)` reads the data module, and the three
no-instance readers switch to it. Rule: **no facts lookup may import an
SDK.** A fence asserts it (§7).

### 4. `base.py` stops importing the OpenAI SDK

The `OpenAI(...)` client construction, `client_timeout()`'s
`openai.NOT_GIVEN` and the `openai.*Error` mapping move into an
OpenAI-wire layer (a mixin or an intermediate base) that `openai_compat`
and `openai_native` use. `BaseProvider` keeps everything wire-neutral.

### 5. Clients see the load

`create_provider()` emits `EventType.STATUS` with
`{"kind": "provider_loading", "provider": name}` before importing a module
not yet loaded, and `{"kind": "provider_loaded", "provider": name,
"seconds": …}` after. No new event type: all four clients already render
STATUS in a chat stream. A switch outside a stream (`/provider`, the
model picker) reaches web and VSCode through the command envelope's
`events` list; step 4 checks that each client renders it there, and that
the TUIs show it in-process. A failed import is an `ERROR` that names the missing package and
its install extra (`install_extra_hint`, as the Gemini and Anthropic
modules do today).

Start-up loads only the configured default provider. A provider switch
loads the new one, once per process.

**As built (step 4, 2026-10-20).** Three refinements to the text above:

- The notices are emitted by `provider_ops.set_provider` (through
  `_load_provider_module`), not `create_provider()`: the registry has no
  engine to queue events on. `data` is the human text, as for every other
  STATUS, and the structured fields above are in `metadata` (`kind`,
  `provider`, `seconds`; `provider_load_failed` with `module` on the ERROR).
- Both STATUS notices are queued **after** the import. A switch is a
  command, and its events reach every client with the command's response
  (switches are refused while a response streams), so a "Loading" queued
  first would still arrive next to the "Loaded".
- A load under 0.1 s (`ANNOUNCE_LOAD_AFTER_S`) is not announced: its SDK
  was already in memory, e.g. openrouter after openai.

Where each client shows them: web from `/command/provider`'s envelope and,
new, from `POST /providers` in the provider dropdown; VSCode from
`_drainEnvelopeEvents` (which now handles `status` and `error`) for both
the command and the provider quick pick; Rich and Textual drain the engine
queue in their `set_provider` (nothing drained it in the TUIs before). A
failed load is `POST /providers`' 400 detail. Tests:
`tests/test_provider_loading_events.py`.

### 6. `ppxai/__init__.py` stops re-exporting the engine

It keeps `__version__` and the config re-exports (0.08 s), and drops
`EngineClient`. `from ppxai.engine import EngineClient`, the documented
form since v1.12.0, is unchanged. `from ppxai import EngineClient` stops
working; nothing in this repo or in ppxai-sre uses it. A PEP 562
`__getattr__` shim would keep it working but is exactly the hidden import
the rule forbids, so it is not proposed (open question 2).

### 7. The import rule's exception, and its fences

The no-lazy-imports rule exists so a module's real dependencies can be read
from its imports. A declared table loaded by one function keeps that
property: the table is the dependency list. The exception is therefore
narrow:

- `importlib.import_module` is allowed in **exactly two places**:
  `CommandFactory._ensure_loaded` (existing) and
  `providers.load_provider_class` (new). A fence in
  `tests/test_no_new_lazy_imports.py` fails on any other call site.
- **Registry ↔ PyInstaller parity:** every module in `_PROVIDER_MODULES`
  and `_FALLBACK` appears in the `hiddenimports` of every spec that bundles
  the engine, and no spec names a `ppxai.engine.providers.*` module that
  doesn't exist. This fixes today's drift as a side effect.
- **No SDK on the cheap paths**, each measured in a fresh subprocess:
  - `import ppxai.version` loads none of `openai`, `anthropic`,
    `google.genai`;
  - `ppxai-server --version`, `--registry-contract` and `--list --json`
    load none of them;
  - `get_provider_facts(name)` for every registered name loads none of
    them;
  - creating a Gemini provider loads neither `openai` nor `anthropic`.
  - **As built (step 5, 2026-10-20):** the first and third hold and are
    fenced (`tests/test_cheap_import_paths.py`,
    `tests/test_provider_sdk_free_modules.py`). The second and fourth hold
    for `anthropic` and `google.genai` only, and are fenced that far
    (`test_cheap_import_paths.py::TestServerProbes`,
    `test_provider_registry.py::test_the_gemini_class_loads_no_anthropic`):
    any import under `ppxai.engine` runs `ppxai/engine/__init__.py`, which
    loads `EngineClient` and with it `engine/search/perplexity.py`, which
    imports `openai` at module top (owner decision 3). The probes are also
    parsed in `server/http.py::run_server`, after the whole server module
    is imported.
    Probes measured ~1.8 s on the macOS dev host (about 3.2 s before this
    ADR). Making them cheap needs a probe-first entry point, i.e. one more
    named exception to the import rule. **Owner, 2026-10-20: accept the
    ~1.8 s probes for now**; no probe-first entry point.
- **Every registry entry resolves:** each `(module, class)` imports
  (skipping a missing optional extra) and the class subclasses
  `BaseProvider`.

## Expected effect

These are estimates from the table above, to be measured after the change:

- A remote probe stops importing the engine: from about 3.2 s towards the
  config-only cost plus interpreter start, well under 1 s. The SSH
  Launcher's list, launch and refresh get faster by that much per call, and
  the SSH-launcher Playwright spec stops running close to its 30 s limit.
- A Gemini session skips `openai` and `anthropic`; an OpenRouter or OpenAI
  session skips `anthropic` and `google.genai`.
- The 31 test sites that spawn a fresh interpreter (Item 83) get cheaper.

### Measured (step 6, 2026-10-20)

macOS dev host (Intel, 4 physical / 8 logical cores), one venv, v1.19.4
(`0a02eb68`, before any step) against `feature/v1.19.5` @ `81dab79b`. Each
figure is the median of 5 cold interpreters with an empty `HOME`
(`PYTHONPATH` = the tree); "importtime" is `-X importtime`'s cumulative
figure for the module.

| | v1.19.4 wall | v1.19.4 importtime | 1.19.5 wall | 1.19.5 importtime |
|---|---|---|---|---|
| `import ppxai.version` | 2.43 s | 2.12 s | **0.14 s** | 0.08 s |
| `import ppxai` | 2.42 s | 2.10 s | **0.14 s** | 0.09 s |
| `import ppxai.config` | 2.45 s | 2.13 s | **0.14 s** | 0.08 s |
| `import ppxai.engine` | 2.56 s | 2.22 s | **1.06 s** | 0.89 s |
| `import ppxai.engine.providers` | 2.47 s | 2.20 s | **1.05 s** | 0.95 s |
| `import ppxai.server.http` | 3.34 s | 2.87 s | **1.82 s** | 1.61 s |
| `ppxai-server --version` / `--registry-contract` / `--list --json` (from source) | 3.31 / 3.29 / 3.33 s | | **1.81 / 1.80 / 1.81 s** | |

SDKs loaded by `import ppxai.engine` or `ppxai.server.http`: all three
before, `openai` only after (owner decision 3). The SDKs alone are
unchanged (openai 0.86 s, anthropic 1.14 s, google.genai 0.94 s,
fastapi 0.57 s wall).

Against the estimates:

- **Remote probes: 3.3 s → 1.8 s, not "well under 1 s".** They still
  import the whole server (§7 note); the owner accepted ~1.8 s on
  2026-10-20. The installed one-file binary's `--version` is ~3.7 s,
  most of it PyInstaller unpacking itself, so a remote probe against an
  installed binary gains less than the source figure.
- **SSH-launcher Playwright spec: 66 s → 38.5 s** (7 tests, two runs each;
  v1.19.4's code run by pointing the spec's server spawns at the old tree).
  The two slowest tests, which had been close to their 30 s limit: launch
  15.6 s → 9.8 s, Stop 22.7 s → 12.9 s.
- **Sessions skip unused SDKs:** yes, measured above and fenced
  (`tests/test_provider_registry.py`, `tests/test_cheap_import_paths.py`),
  except that every session loads `openai` (decision 3).
- **The suite: no measurable change.** With the same 7 skips, v1.19.4 ran
  7,450 tests in 159 s and 1.19.5 ran 7,539 in 170 s, back to back; two
  earlier back-to-back pairs gave 139–147 s and 147–153 s. Per test that
  is ~21 ms against ~23 ms, inside the run-to-run spread from host load
  (Item 83). The spawn sites save ~1.5 s each, a few seconds of wall at
  6 workers. This branch also added about ten tests that start fresh
  interpreters.

## Alternatives considered

- **Keep eager loading; raise the Playwright timeout.** Fixes the test,
  not the cost: every launcher call and every interpreter start keeps
  paying 2–3 s. Worth doing anyway as a stopgap if this ADR waits.
- **Function-level `import` inside `create_provider`.** Same runtime
  effect, but the dependency becomes invisible: exactly the pattern the
  rule exists to prevent, and one the fence would have to whitelist per
  module.
- **PEP 562 `__getattr__` on the providers package.** Keeps
  `from ppxai.engine.providers import GeminiProvider` working lazily, but
  hides the import behind attribute access and makes the trigger
  unpredictable (any `hasattr`, any `dir()`).
- **A fast path only for the CLI probes** (parse `--version` /
  `--list` before importing anything). Fixes ADR 0013's cost only; the
  interactive start-up, the test suite and the facts readers keep loading
  every SDK.

## Migration steps

Each step lands green on its own:

1. **Facts to data modules** (§3) and `get_provider_facts`; switch the
   three no-instance readers. No behaviour change; fence: facts lookups
   load no SDK.
2. **OpenAI wire out of `base.py`** (§4). No behaviour change.
3. **Registry as data plus `load_provider_class`** (§1, §2), the three
   direct imports removed, PyInstaller specs fixed, parity and
   `importlib` fences added. **Notify ppxai-sre before this step lands:**
   their binaries break at a switch to `openai` or `anthropic` unless their
   specs list every registry module (or read `_PROVIDER_MODULES` and
   `_FALLBACK` at build time). The §7 parity fence reads only this repo's
   specs, so it cannot catch theirs.
4. **Loading events** (§5) and their rendering in the four clients.
5. **`ppxai/__init__.py` slimmed** (§6) plus the cheap-path fences.
   ppxai-sre doesn't use `from ppxai import`, so this step doesn't affect
   them; tell them it landed.
6. Re-measure: import table, remote probe time, SSH-launcher spec, the
   suite's wall time. Record the numbers here and in Item 83.

## Owner decisions (2026-10-11)

1. **Prewarm: yes.** Start-up loads the configured default provider, as
   today. Only a switch to another provider loads on demand and shows the
   loading message.
2. **`from ppxai import EngineClient`: dropped.** No PEP 562 shim. Goes in
   the v1.19.5 release notes as a breaking change, with the replacement
   `from ppxai.engine import EngineClient`.
3. **Search backends: left as they are.** `engine/search/perplexity.py`
   keeps its module-top `openai` import; revisit only if a session without
   `openai` becomes possible.
4. **Release: v1.19.5.**

## Open questions as proposed

These were the questions put to the owner; the answers are above.

1. **Prewarm.** Should start-up load the default provider in the
   background (the first message doesn't wait) or on first use (start-up
   is fastest, the first message pays 0.5–1 s)? Proposed: at start-up, as
   today, so only non-default providers change behaviour.
2. **`from ppxai import EngineClient`.** Drop it (proposed; no known
   user), or keep it through a PEP 562 shim with a written exception?
3. **Search backends.** `engine/search/perplexity.py` imports `openai` at
   module top. Fold the search backends into the same rule now, or leave
   them, since `openai` is a hard dependency and is loaded by most
   sessions anyway? Proposed: leave them, and revisit if a session without
   `openai` becomes possible.
4. **Release.** Which release carries this, if any.
