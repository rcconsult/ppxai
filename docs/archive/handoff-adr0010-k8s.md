# Handoff — ADR 0010 config move vs. the k8s `coder` deployment

**Written:** 2026-08-06, from the Windows host, at `573b76ff` on
`bugfix/v1.19.1` (pushed).
**For:** the Linux host, updating the coder service on k8s to test against
custom local LLMs.
**Read this before touching the ConfigMap.** It replaces a warning I gave
verbally that turned out to be broader than reality.

---

## TL;DR — the k8s ConfigMap is NOT broken by ADR 0010

I initially flagged "k8s ConfigMap templates need the rename in the same
window, no grace period." **I then actually checked, and that is not true
for this repo's coder config.** Verified by running the real detector over
the embedded JSON:

```bash
# from repo root, on the branch
python - <<'PY'
import json
raw = open('deploy/examples/microk8s/server-config.yaml', encoding='utf-8').read()
block = raw.split('ppxai-config.json: |',1)[1]
lines=[]
for ln in block.splitlines()[1:]:
    if ln.strip() and not ln.startswith('    '): break
    lines.append(ln[4:] if ln.startswith('    ') else ln)
cfg = json.loads('\n'.join(lines))
from ppxai.commands.doctor import _format_config_migration_section
print('\n'.join(_format_config_migration_section(cfg)))
print('tools.agent keys:', sorted(cfg.get('tools',{}).get('agent',{})))
PY
```

Result:

```
Config shape (ADR 0010, v1.19.1):
   ✓ no keys at pre-v1.19.1 locations
tools.agent keys: ['checkpoint_backend', 'max_iterations',
                   'max_tool_iterations', 'zombie_threshold']
```

All four keys that ConfigMap sets **stayed** on `tools.agent.*` — they are
tool-intrinsic loop knobs, not tier keys. The deployment never enabled the
task tier, so it has nothing to migrate.

**Do not "fix" the ConfigMap for ADR 0010.** There is nothing to fix, and
adding an `execution` block you don't need only adds surface.

## What DID change (so you can reason about the deployed server)

Six keys moved off `tools.agent.*`, **no dual-read** — the old locations
are ignored, not deprecated:

| Legacy (ignored) | New |
|---|---|
| `tools.agent.task_tier_enabled` | `execution.task.enabled` |
| `tools.agent.sandbox.*` | `execution.task.sandbox.*` |
| `tools.agent.spawn_consent` | `execution.task.consent.spawn_consent` |
| `tools.agent.consent_ttl_s` | `execution.task.consent.consent_ttl_s` |
| `tools.agent.result_retention_s` | `execution.task.budgets.result_retention_s` |
| `tools.agent.default_subagent` | `execution.default_subagent` |

Unchanged and still read from `tools.agent.*`: `max_iterations`,
`max_tool_iterations`, `max_same_tool_calls`, `context_char_limit`,
`min_task_words`, `auto_retry_empty`, `zombie_threshold`. (Also
`checkpoint_backend` / `checkpoint_message`, untouched by this ADR.)

**If you later enable the task tier on the cluster**, write it in the new
shape — the old shape will silently do nothing:

```jsonc
"execution": {
  "task": {
    "enabled": true,
    "sandbox": { "enforcement": "in_process",
                 "read_paths": { "allow": ["/workspace"] } },
    "consent": { "spawn_consent": "deny", "consent_ttl_s": 300 }
  },
  "default_subagent": { "provider": "vllm-qwen36",
                        "model": "Qwen/Qwen3.6-35B-A3B-FP8" }
}
```

## The one real hazard, and how to check it in 10 seconds

Because there is **no dual-read**, a key at an old location produces no
warning anywhere — the accessors don't read those paths at all, so nothing
in the running server can notice. The failure is silent: the setting
reverts to its default and the config file still *looks* correct.

So don't reason about it — ask the tool:

```bash
# in a server pod, or against any config file
ppxai   # then: /doctor
```

`/doctor` gained a `Config shape (ADR 0010, v1.19.1)` section that scans
the config **file** and prints the old→new mapping for anything stale.
That section is the migration path; it exists precisely because the code
is structurally blind to the old keys. Full write-up:
`docs/lessons/clean-break-config-moves-need-a-file-scan.md`.

## Also in this commit (may surprise you on the cluster)

- **Root-level `visualization.*` was deleted.** Its accessor had zero
  production callers — it documented a knob nothing read. If a cluster
  config carries a `visualization` block it is now simply inert (it was
  already inert; the block is just no longer loaded). No action needed.
- **`GET /agent/config` changed shape** — the six tier keys are gone from
  the response. Internal endpoint, not `/v1/*`. Only consumer is the
  bundled VSCode extension, versioned with the server. If anything on the
  cluster scrapes that endpoint, it needs a look.
- **`/v1/oneshot` and `/v1/agent/*` are unchanged** — byte-identical
  request and response. ppxai-sre's outlook-monitor is unaffected.

## Getting your context into the right shape before you start

1. `git fetch && git rebase` — the branch moved to **`573b76ff`**; that
   commit is the whole ADR 0010 change (37 files).
2. Read `docs/decisions/0010-config-shape-review.md` §"Implementation note
   (v1.19.1)" — it records that the shipped approach **deviates** from the
   dual-read plan written in that same ADR's Migration section. Read the
   note, not the plan, for what actually exists.
3. Read `CHANGELOG.md` `[1.19.1]` §"Config shape (BREAKING — ADR 0010)"
   and the matching section in `docs/release-notes-v1.19.1-DRAFT.md` (has
   a before/after JSON diff).
4. Baseline before changing anything on the cluster: **4815 passed, 0
   failed, 26 skipped** on this Windows host with `uv sync --all-extras`.
   Linux typically reports 7 more (the `TestKillPreviewBackend` cases that
   skip on Windows).

## Cross-repo: ppxai-sre

Still worth a grep there, since I could only verify **this** repo:

```bash
grep -rn "task_tier_enabled\|spawn_consent\|consent_ttl_s\|\
result_retention_s\|default_subagent" <ppxai-sre>/
```

If it comes back empty, ppxai-sre needs nothing either — it consumes
`POST /v1/oneshot`, whose contract did not move. If it has any of those
keys in a chart or ConfigMap, migrate them per the table above **before**
rolling a v1.19.1 server, because there is no grace period.

## Unrelated but load-bearing for your session

- `PPXAI_CONFIG_FILE` (often set in a repo-root `.env`) overrides
  `./ppxai-config.json`. Editing the obvious file can silently have no
  effect. `ppxai-server` v1.19.0+ prints `Config: <path>` at startup —
  read that line first. See
  `docs/lessons/config-source-resolution.md`.
- Web assets are served from `~/.ppxai/web`, not the repo tree; use
  `PPXAI_WEB_DIR=<repo>/ppxai/web` to serve a checkout. See
  `docs/lessons/web-assets-served-from-ppxai-home.md`.
