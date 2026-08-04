# Example `/task` skill directories (v1.19.0, T4)

Ready-to-use agent **skills** for the `/task` command family. A *skill* is a
directory that packages a reusable capability:

```
ci-triage/
  SKILL.md              # a spec (T3 front-matter): tool grant, budget, body → system
  references/*.md       # → mounted into the run READ-SCOPE (read_file/grep reach these)
  scripts/*.sh          # INERT — need a shell grant + the container tier (T9)
```

`--skill <name>` composes with T3: the skill's `SKILL.md` is parsed by the same
loader as a `--spec`, and the skill directory is added to the run's read-scope
so the agent can actually read `references/`.

| Skill | Shows |
|---|---|
| [`ci-triage/`](ci-triage/) | happy path — grant + budget + `references/checklist.md` mounted into read-scope |
| [`secrets-scan/`](secrets-scan/) | a skill with **no provider/model** — grant unions with another skill or with `--tools` |
| [`needs-scripts/`](needs-scripts/) | the **scripts gate** — a `scripts/` skill is refused 400 unless `allow_skill_scripts` is on |

## Enable the skill surface

Skills resolve **by name** under `tools.agent.sandbox.skills_dir` (name only — no
paths). The seal must be engaged (`enforcement: "in_process"`) for the read-scope
mount to mean anything. In `~/.ppxai/ppxai-config.json`:

```jsonc
{
  "tools": {
    "agent": {
      "task_tier_enabled": true,
      "default_subagent": { "provider": "nvidia", "model": "qwen" },
      "sandbox": {
        "enforcement": "in_process",                 // engage the T2 seal
        "skills_dir": "/path/to/ppxai/examples/task-skills",
        "allow_skill_scripts": false                 // needs-scripts is refused while false
      }
    }
  }
}
```

(Replace `provider`/`model` with a tool-calling model you have configured. The
skills name `nvidia`/`qwen` as a placeholder; a skill's own provider/model fill
gaps, and an explicit request flag overrides.)

## Live trial

```bash
PPXAI_WEB_DIR=$PWD/ppxai/web uv run ppxai-server
# then in the web UI:
/task "the CI job is red" --skill ci-triage
/task "audit this repo for secrets" --skill secrets-scan --skill ci-triage   # grants union
/task "x" --skill needs-scripts        # → ❌ refused: scripts/ (400) unless allow_skill_scripts
```

**Acceptance signal (the T4 point):** with the seal on, confirm the agent can
read `ci-triage/references/checklist.md` **but a read of a sibling outside the
skill dir is denied**. That "readable inside / denied outside" pair proves the
mount is scoped, not a hole in the seal.

Or hit the API directly (auth **off** — no `server.secrets` file store):

```bash
curl -s localhost:54320/v1/agent/task \
  -H 'content-type: application/json' \
  -d '{"task":"the CI job is red","skills":["ci-triage"]}'
# scripts gate:
curl -s localhost:54320/v1/agent/task -H 'content-type: application/json' \
  -d '{"task":"x","skills":["needs-scripts"]}'     # 400, "scripts ... cannot run"
```

### Auth-enabled host (a `server.secrets` file token store)

`POST /v1/agent/task` needs a bearer even on loopback (only `/v1/oneshot` and
`POST /v1/agent/run` stay exempt). Bootstrap-mint one, then carry it:

```bash
TOKEN=$(curl -s localhost:54320/v1/tokens -H 'content-type: application/json' \
  -d '{"owner":"trial"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -s localhost:54320/v1/agent/task \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"task":"the CI job is red","skills":["ci-triage"]}'
```

In the **web / VSCode** clients, `/token mint` (or "ppxai: Set API Token")
stores the bearer once and every `/task` verb carries it.

## Notes

- **Grant = union.** Skills ADD capability: the effective grant is the
  request/spec grant ∪ every skill's grant, de-duped, still ⊆ the operator
  ceiling (no `execute_shell_command`, `task_tier_enabled` required).
- **Scalars** (provider/model/system/budget) take precedence
  request > spec > first skill that sets it > `default_subagent`.
- **Scripts are inert.** `scripts/` never run in the in-process tier; the gate
  just makes that explicit instead of silently defanging a skill that expects
  them. They become runnable only with the container tier (T9).
- **Mount is scoped.** `--skill ci-triage` mounts `ci-triage/` — not the whole
  `skills_dir` sibling-by-sibling — into this run's read-scope.
