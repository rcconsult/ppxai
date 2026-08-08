# Handoff — extracting `build_task_runner` to the engine layer

**Written:** 2026-08-08, from the Windows host, at `bbba6fbc` on
`bugfix/v1.19.1`.
**For:** the ppxai-sre session. **This is a request for review BEFORE the
code exists**, not a notification after the fact.
**Protocol:** `docs/handoff-seam-watcher.md`.

---

## What I want from you

I am about to move `build_task_runner` out of
`ppxai/server/routes/agent_v1.py` into an engine-level module so it can be
called **in-process, with no HTTP server**. That function is item (1) on
your SDK critical path, so you get the signature review before I build,
not after. Concretely, answer these four:

1. Does the signature below serve your embedding model as-is?
2. `registry` is the first positional param — an object you must supply.
   Is constructing/owning one workable on your side, or do you need a
   factory that builds a default?
3. The returned runner is `async def _runner(m) -> str`, where `m` is a
   run-meta object it uses as `m.run_id` and `getattr(m, "owner", None)`.
   That duck type is currently implicit. Do you want it pinned as a
   Protocol before I move it? (I lean yes; cheap now, breaking later.)
4. Proposed home is `ppxai/engine/task_runner.py`. Object?

Reply through the human with a verdict. **I am not extracting until you
answer** — the protocol is stop-before-build for seam items.

## Why now

T8b (the `/task` + `/run` port to the TUIs) is unblocked, and the Textual
client is the target. The TUIs are **in-process — no channel to a
ppxai-server**, so porting forces the transport decision recorded in
`docs/plan-task-command-sequencing.md` §T8b: embed the runner, or grow an
HTTP client in the TUIs. We are taking **embed**, which is the direction
that plan already recommended precisely because it retires debt (t) and
hands you the embeddable runner as a by-product.

So this extraction is not TUI-motivated bookkeeping. The TUI is the first
consumer; you are the second, and yours is the one with a contract.

## The extraction is clean — verified, not assumed

| Check | Result |
|---|---|
| Extent | lines **1278–1540**, 263 lines (next def is `list_agent_runs` at 1541) |
| FastAPI / starlette coupling in that range | **NONE** (`grep` for `Request`, `Depends`, `HTTPException`, `fastapi`, `starlette`) |
| Dependencies | all engine/config-level: `EngineClient`, `ScopedToolManager`, `NetworkPolicy`, `SpawnSubagentTool`, `build_filesystem_policy`, `compose_agent_system_prompt`, `get_execution_task_config`, `get_default_working_dir`, `get_control` |

It constructs `EngineClient()` directly and never touches the request. It
is engine code that happens to live in a route module.

**Scope of my reading, stated honestly:** I read 1278–1372 line by line
and scanned 1278–1540 by grep. I have not read 1372–1540 line by line, so
treat "no hidden coupling" as grep-strength, not eyeball-strength, for
that tail. I will read it fully during the extraction.

## Current signature (verbatim, `agent_v1.py:1278`)

```python
def build_task_runner(
    registry,
    *,
    provider_name: str,
    model: str,
    task: str,
    tools: list[str],
    allow_outbound: list,
    allow_spawn: bool = False,
    system: Optional[str] = None,
    extra_read_paths: Optional[list] = None,
    workdir: Optional[str] = None,
):
```

Returns `async def _runner(m) -> str`.

Semantics worth knowing before you review:

- **`allow_spawn` is the depth cap, structurally.** A top-level run gets
  the `spawn_subagent` tool only if it is in `tools`; a child is always
  built with `allow_spawn=False`, so a grandchild is impossible — not by a
  runtime check the model could probe.
- **The function passes itself as `runner_builder=build_task_runner`**
  (`:1365`) to `SpawnSubagentTool`, i.e. it recurses for child runs. The
  extraction preserves this as a module-level self-reference.
- **Consent parks the run.** When a spawn needs consent, `_spawn_consent`
  calls `registry.park_run(m, kind="consent", ...)` and blocks until
  `respond` answers or the TTL expires (fail-closed → denial). Policy from
  `execution.task.consent.spawn_consent`; `"auto"` skips the park.
- **`workdir` applies only when the filesystem seal is OFF** — the sealed
  branch always uses the per-run jail. `None` → server default, and
  deliberately never the process launch dir.
- **`extra_read_paths` (T4)** mounts skill dirs on top of
  `read_paths.allow`, and is consulted only under
  `enforcement="in_process"`.

## Compatibility plan

- `agent_v1.build_task_runner` stays importable as a re-export. This is
  not cosmetic: **four tests monkeypatch that exact attribute** —
  `tests/test_agent_runs.py:951, 1044, 2624, 2682` — and
  `server/routes/oneshot.py:301` imports it from there. Break the name and
  T1–T7 go red.
- Route call sites (`agent_v1.py:442`, `:1260`, `:1730`,
  `oneshot.py:322`) become thin callers; behavior unchanged.

## What does NOT change

**No wire surface moves.** `POST /v1/oneshot` stays byte-identical,
`/v1/agent/*` request and response shapes are untouched, and no event
payload changes. This is a code-location change plus a new in-process
entry point. If you find anything in the review that contradicts that,
say so — that would make it a seam break and I want to know before it
lands, not after.

Also unchanged: the `~/.ppxai/runs/<run_id>/agent-<n>/` namespace,
`state.json`, `meta.json`.

## Open, and yours to answer

The ADR 0010 grep against ppxai-sre (`docs/handoff-seam-watcher.md`) is
still outstanding and unrelated to this note. If it has not run yet,
please run it in the same pass.
