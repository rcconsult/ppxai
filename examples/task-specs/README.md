# Example `/task` spec files (v1.19.0, T3)

Ready-to-use agent **spec files** for the `/task` command family. A spec
declares a tool-capable run — grant, provider/model, budget, egress, system
prompt — so you launch with `--spec <name>` instead of a long flag line.

| File | Shows |
|---|---|
| [`triage.md`](triage.md) | `.md` front-matter + body-as-system; grant + budget + egress |
| [`summarize.json`](summarize.json) | `.json` spec with an explicit `system` |
| [`batch.jsonl`](batch.jsonl) | one spec per line (batch fan-out — client `--batch`, T3.b) |
| [`rejected-shell.md`](rejected-shell.md) | the **ceiling clamp** — a spec-supplied shell grant is rejected 400 |

## Enable the spec surface

Specs resolve **by name** under `tools.agent.sandbox.specs_dir` (name only — no
paths). In `~/.ppxai/ppxai-config.json`:

```jsonc
{
  "tools": {
    "agent": {
      "task_tier_enabled": true,                 // the tool-capable /task tier is default-off
      "default_subagent": { "provider": "nvidia", "model": "qwen" },
      "sandbox": {
        "specs_dir": "/path/to/ppxai/examples/task-specs"
      }
    }
  }
}
```

(Replace `provider`/`model` with a tool-calling model you have configured. The
spec files above name `nvidia`/`qwen` as a placeholder; a spec's own
provider/model override the default, and an explicit request flag overrides the
spec.)

## Live trial

Run the web client against live source and launch by spec name:

```bash
PPXAI_WEB_DIR=$PWD/ppxai/web uv run ppxai-server
# then in the web UI:
/task run "the CI job is red" --spec triage
/task run "explain docs/README.md" --spec summarize
/task run "x" --spec rejected-shell        # → ❌ rejected: shell grant (400)
```

Confirm the run pane shows the **grant + budget from the file** (not the flag
line) — that is the T3 acceptance signal. `--model foo --spec triage` proves
precedence: the flag wins, the spec fills the rest.

Or hit the API directly:

```bash
curl -s localhost:54320/v1/agent/task \
  -H 'content-type: application/json' \
  -d '{"task":"the CI job is red","spec":"triage"}'
# rejected shell grant:
curl -s localhost:54320/v1/agent/task -H 'content-type: application/json' \
  -d '{"task":"x","spec":"rejected-shell"}'      # 400, "shell ... not permitted"
```

## Notes

- **Precedence:** explicit request field > spec field > `default_subagent`.
- **Ceiling:** the merged grant faces the same guards as a direct request —
  no `execute_shell_command`, `task_tier_enabled` required. A spec cannot widen
  what the operator allows.
- **`--system-file` / `--batch`** (browser file reads) are T3.b; `batch.jsonl`
  is included now so it's ready when that client glue lands. The server loader
  already parses it (`ppxai.engine.agent_spec.load_batch_lines`).
