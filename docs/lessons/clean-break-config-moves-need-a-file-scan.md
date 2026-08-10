# A clean-break config move is invisible to the code that moved it

**TL;DR:** When a config key moves with **no dual-read**, nothing in the
codebase reads the old location any more — so no accessor, no validator and
no startup path can ever notice a config still sitting at the old key. The
operator's setting is silently ignored and reverts to its default. The only
thing that can detect it is a check that reads the **config file itself**.
`/doctor` carries that check; it must scan raw JSON, never the accessors.

**Verify with:**
```bash
# The migration table and the file-scanning check that reports it
grep -n "ADR_0010_KEY_MOVES" -A14 ppxai/commands/doctor.py

# Proof the accessors are structurally blind to the old paths: the whole
# `tools.agent` block has exactly ONE reader, and it returns only the
# tool-loop knobs — no tier key comes back out of it.
grep -rn 'get_tool_config("agent")' ppxai/ --include=*.py
# -> ppxai/config/tools.py only (inside get_agent_config)
```
```python
# Same thing, executable:
from ppxai.config import get_agent_config
set(get_agent_config()) & {"task_tier_enabled", "sandbox", "spawn_consent",
                           "consent_ttl_s", "result_retention_s",
                           "default_subagent"}          # -> set()
```

## Why this trips people up

The instinct after moving a key is "the accessor will warn if someone still
uses the old name." That instinct is correct **only** for a dual-read
migration, where the accessor deliberately still looks at the legacy
location in order to fall back and warn.

Under a clean break there is no fallback, so there is nothing to warn *from*.
`get_execution_task_config()` reads `execution.task.*` and that is all it
does. A config still carrying the tier flag at its pre-v1.19.1 location
(`execution.task.enabled` was `tools.agent.task_tier_enabled`) is not
"wrong" from the code's perspective — it is a key in a block the accessor
never opens. From inside the program the stale key does not exist.

The failure this produces is the quiet kind:

- The operator leaves the tier flag at that old location (their v1.19.0
  config, unchanged).
- The tier resolves to its default, `false`.
- `POST /v1/agent/task` returns 403 — and the operator is looking at a
  config file that plainly says the tier is enabled.

Nothing logs, nothing warns, and the config file *looks* right. Note this
also means an operator's **security-relevant** settings can silently relax
to defaults (`spawn_consent`, sandbox `enforcement`) — the defaults are the
safe values here, but "safe" and "what the operator asked for" are not the
same thing, and the divergence is unannounced.

## What's actually true

- **The detector must read the file, not the config object.** In
  `ppxai/commands/doctor.py`, `_format_config_migration_section()` takes raw
  parsed JSON and walks the legacy paths with `_lookup_path()`. It is called
  with a fresh `json.load()` of `audit["config_path"]`, deliberately not with
  `get_config()` — the loader's whitelist and the accessors would both have
  already discarded what we are trying to find.
- **The loader whitelist is a second silencer.** `load_config()` returns an
  explicit dict of top-level blocks; a block not listed there is invisible
  even to a raw `get_config()` read. This has bitten the repo three times now
  (`file_tree` in v1.18.7, `execution` in v1.19.1 F3, and
  `providers.<name>.web_search` dead since v1.13.4). A file scan bypasses
  that layer too.
- **`/doctor` is therefore load-bearing, not a nicety.** For a clean-break
  migration it is the *only* migration path an operator has. If the check is
  removed or stops running offline, the breaking change becomes undiagnosable
  from inside the product.
- **A doc sentinel is the other half.** `tests/test_docs_consistency.py`
  `TestAdr0010MigrationStaysComplete` fails if any active doc still instructs
  an operator to set a legacy path, or if a moved key resurfaces on the old
  accessor. A doc that teaches the old key is as harmful as the stale config
  itself, because following it produces the same silent no-op.

## The general rule

When choosing **clean break vs. dual-read** for a config move, the tradeoff
is not "less code vs. more code" — it is *who* discovers the drift:

| | Dual-read | Clean break |
|---|---|---|
| Old key still works | Yes, one release | No |
| Who notices drift | The program (warns at load) | Only an explicit file scan |
| Cost if you skip the detector | Warning noise | **Silent misconfiguration** |

A clean break is a perfectly good choice — it avoids a release with both
names live in docs and support. But it **moves the detection burden out of
the runtime and into a tool you must deliberately build.** Ship the file
scan in the same change as the move, never as follow-up cleanup.

## The second half: the codebase keeps teaching the old key (2026-08-10)

The file scan catches a stale key in the operator's config. It cannot catch
the mirror-image failure — **our own strings still telling operators to set
the old path.** Three months after ADR 0010 landed, `/task --skill x` on a
box with no `skills_dir` answered:

> Skills are not enabled: set `tools.agent.sandbox.skills_dir`.

An operator who follows that hint edits a key that is read by nothing, gets
the same refusal, and has no way to tell the difference from a bug. This is
the exact silent-no-op the file scan exists to surface, except *we* are the
one printing the stale path — and `/doctor` cannot flag it, because the
operator's file is fine.

**Grep for the moved key across everything that reaches a human, not just
the code that reads config:**

```bash
# Every surface: error strings, API field descriptions, client help text
grep -rn "tools\.agent\.sandbox\|tools\.agent\.default_subagent" \
  --include=*.py --include=*.js --include=*.ts ppxai/ vscode-extension/src/
# -> should return ONLY the "was X" rows in config/execution.py docstrings
```

Scoped as "3 error strings", it was **12 references across 8 files**. The two
that mattered most were not error strings at all: `AgentTaskRequest.spec` and
`.skills` field descriptions, which FastAPI publishes into the OpenAPI
schema — so the stale path was in the API contract external consumers read.
Four more were web/VSCode help text.

**The tell for how this survives review:** the `spec` field description said
`tools.agent.sandbox.specs_dir` on one line and `execution.task.enabled`
four lines below it. A half-migrated docstring reads as migrated. Search by
the *old* key, never by eye.

Corollary for the debt inventory: an item scoped from one file's grep is a
lower bound. Re-run the search across every language in the repo before
believing the count — `--include=*.py` alone would have missed the two
client surfaces and left the VSCode extension teaching a dead key.

## Related

- `docs/decisions/0010-config-shape-review.md` §"Implementation note
  (v1.19.1)" — the six keys that moved, and why the dual-read plan in that
  ADR's own Migration section was not what shipped.
- `ppxai/config/execution.py` — the `execution.*` axis accessors, including
  the fail-safe rule (an unreadable config resolves capabilities OFF).
- [config-source-resolution.md](config-source-resolution.md) — the *other*
  silent config failure: editing the wrong file entirely.
- Lesson promotion criteria: [README.md](README.md).
