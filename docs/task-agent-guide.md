# Task Agent User Guide (`/task`)

**Applies to**: v1.19.0+ · **Clients**: Web + VSCode (TUIs: not yet — the
in-process TUIs have no channel to the run registry; their autocomplete
deliberately does not offer `/task`)
**Status**: Shipped (T1–T8a), live-trial-verified · API surface under the
`/v1/agent/*` in-development exemption — see
[api-gateway.md](api-gateway.md)

`/task` launches **tool-capable, sandboxed, durable background agent runs**.
Unlike the in-session [`/agent` mode](session-agent-guide.md) (which drives
tools inside your current chat) and the tool-free `/agentrun` one-off, a
`/task` run executes on the server with an explicit **capability grant**,
survives client disconnects and server restarts, and has a full lifecycle:
consent parks, held results, and resume.

| Surface | Tools | Where it runs | Guide |
|---|---|---|---|
| `/agent` session mode | session's tools | inside your chat session | [session-agent-guide.md](session-agent-guide.md) |
| `/agentrun` one-off | none (tool-free) | background, fire-and-forget | [api-gateway.md](api-gateway.md) |
| **`/task` (this guide)** | **explicit grant** | **background, durable, sandboxed** | here |

---

## 1. Enable the tier

The tool-capable tier ships **default-off** (trusted-operator opt-in). In
`~/.ppxai/ppxai-config.json`:

```jsonc
{
  "tools": {
    "agent": {
      "task_tier_enabled": true,
      "default_subagent": { "provider": "gemini", "model": "gemini-3.1-pro-preview" }
    }
  }
}
```

`default_subagent` is the fallback provider/model when neither the request
nor a spec names one (pick any tool-calling model you have configured).
Without `task_tier_enabled`, `POST /v1/agent/task` returns 403 with an
enable hint.

## 2. First run

```
/task "summarize README.md" --tools read_file
```

- **Direct launch** (v1.19.1, ADR 0011): there is no `run` subcommand —
  the prompt (+ flags) IS the launch. Quoting the prompt is recommended,
  never required.
- The run id (`run_xxxxxxxxxxxx`) prints immediately; the chat stays usable.
- A live watcher tails the run's events into the transcript (web: a
  right-panel pane; VSCode: transcript lines like `→ read_file`).
- Relative paths resolve against **your session's working directory** by
  default (v1.19.0 workdir alignment) — the same place `/pwd` shows.
- When it finishes, the result is **held** (`completed_pending_ack`) until
  you collect it: `/task collect <id>` (or the Collect button).

## 3. Command reference

```
/task "<desc>" --tools a,b,c [flags]       launch a run (direct — no verb)
/task ls | list                            list runs, newest first
/task get <id> | watch                     print meta/result + (re)watch
/task respond <id> approve|deny|"<text>"   answer a waiting (consent) park
/task collect <id>                         collect a held result → finalized
/task resume <id>                          continue an interrupted run
/task cancel <id>                          cooperative cancel
/task help                                 this summary
```

Disambiguation: a first token that is a lifecycle verb counts as one only
when followed by a run id (`run_` + 12 hex) or nothing — anything else
launches (`/task get the weather --tools web_search` launches). `show`,
`open` and `ack` still work as aliases of `get`/`collect`; the v1.19.0
verbs `task run`, and `show`/`ack` as *canonical* names, are retired
(v1.19.1 breaking change).

### Launch flags

| Flag | Meaning |
|---|---|
| `--tools a,b,c` | **Capability grant** — the ONLY tools the run may call. Required unless a `--spec`/`--skill` supplies it. `execute_shell_command` is always rejected (it would bypass the egress allowlist). |
| `--spec <name>` | Load a spec file from `tools.agent.sandbox.specs_dir` (name only, no paths). Spec fields fill anything you didn't pass; explicit flags win. |
| `--skill <name>` | Mount a skill from `tools.agent.sandbox.skills_dir`: its `SKILL.md` acts as a spec and its directory (incl. `references/`) is mounted into the run's read scope. Repeatable / comma-separated; skills compose. |
| `--allow host[/prefix]` | Per-run egress allowlist entry (comma-separated). Network tools are **deny-by-default**: no `--allow`, no outbound. HTTPS-only, private/loopback IPs blocked. |
| `--provider p` / `--model m` | Per-run intent. Precedence: flag > spec > skill > `default_subagent`. |
| `--budget iters=20,time=300,tokens=100k` | Resource caps (any subset). A capped run stops at a clean checkpoint as `interrupted` (resumable), not `failed`. |
| `--system "…"` | Extra agent framing appended to the run's system prompt. |
| `--work-dir <path>` | Working directory for relative tool paths. Default: **your session's working dir** rides along automatically. Must exist (400 otherwise). With the sandbox seal ON the per-run jail wins and you get a warning instead. |

## 4. Auth: the `/token` command

On hosts with a token store configured (`server.secrets.providers` includes
`{"type": "file", ...}`), the whole `/v1/agent/*` surface requires a bearer —
even from localhost. Both clients manage it in-chat:

```
/token status    show whether a token is attached (masked)
/token mint      self-provision via the loopback bootstrap (local server)
/token set       paste one (masked prompt; VSCode opens the palette input)
/token clear     detach
```

A 401 from any `/task` verb tells you exactly this ("run `/token mint` …").
Web stores the token in `localStorage`; VSCode in `SecretStorage` (shared
with the **"ppxai: Set API Token"** palette entry). Minting remotely isn't
possible — ask the operator for a token and use `/token set`.

## 5. Lifecycle: consent → hold → resume

**Waiting (consent parks, T5).** A run that needs a human decision — e.g. a
`spawn_subagent` under `tools.agent.spawn_consent: "deny"` (the default) —
parks as `waiting`, and the watcher raises a consent card (web) or QuickPick
(VSCode). Answer inline or with `/task respond <id> approve|deny|"note"`.
An unanswered park **denies when its TTL expires**
(`tools.agent.consent_ttl_s`, default 300 s — fail-closed), and the run
continues without the action.

> **Consent gates `spawn_subagent` only.** Interactive consent applies to the
> spawn capability, not to filesystem or other granted tools. A run granted
> `--tools read_file` reads **silently** — the `--tools` allowlist *is* the
> consent. Where those reads may go is a separate question, governed by the
> sandbox seal (§9), which ships **off by default**. So a `/task … --tools
> read_file` on an unsealed host can read any file the process can reach with
> no prompt. See **Item 46** in [debt-inventory.md](debt-inventory.md).

**Held results (T6).** A successful top-level run lands in
`completed_pending_ack`: the run has exited (budget freed, sandbox torn
down) but the result is held until `/task collect <id>` collects it →
`finalized`. A disconnected UI never loses a result. Uncollected holds are
finalized by a lazy reaper after `tools.agent.result_retention_s` (default
3600 s; `0` = hold until explicit ack; data is never deleted, only marked
collected).

**Resume (T7).** `interrupted` / `cancelled` runs whose checkpoint is
conclusive can continue under the same run id: `/task resume <id>` (or the
Resume button). The runner is rebuilt from the run's persisted inputs —
grant, egress, budget, system, skill mounts, **workdir** — and events append
to the same log. Inconclusive checkpoints are refused with a 409 and the
reason. Runs orphaned by a server restart are swept to `interrupted`
(resumable) at startup.

## 6. Spec files (`--spec`)

A spec is an operator-authored file declaring a run shape — grant,
provider/model, budget, egress, system prompt — resolved by name under
`tools.agent.sandbox.specs_dir`. See
[`examples/task-specs/`](../examples/task-specs/README.md) for ready-to-use
`.md` (front-matter + body-as-system) and `.json` examples.

- Precedence: explicit flag > spec > skill > `default_subagent`.
- The merged result faces the same ceiling as a direct request: no shell
  tool, `task_tier_enabled` still required — a spec cannot widen what the
  operator allows.

## 7. Skills (`--skill`)

A skill is a directory under `tools.agent.sandbox.skills_dir` containing a
`SKILL.md` (a spec, T3 loader) plus reference material. Granting a skill
mounts its directory into the run's **read scope** (when the seal is on),
so the agent can read `references/…`. Multiple skills compose: tool grants
union, read roots union. Skills with `scripts/` are refused unless
`allow_skill_scripts: true` (scripts stay inert until the container tier).
Examples: [`examples/task-skills/`](../examples/task-skills/README.md).

## 8. Working directory semantics

Deterministic, never "wherever the server happened to start":

1. `--work-dir <path>` — explicit per-run intent (400 if it doesn't exist).
2. Otherwise your **session working dir** is threaded automatically — so
   `"summarize README.md"` means the same thing in chat and in a task run.
3. Otherwise the server default: `server.working_dir` config, else home.
4. **Seal ON**: the per-run jail always wins; a requested workdir is
   ignored with a "⚠️ sandbox seal active" warning (warn-don't-fail, so the
   same command works across sealed and unsealed hosts).

`/task get <id>` prints the effective `wd:`; resume reuses it; spawned
children inherit it.

## 9. The sandbox seal (operator posture)

The filesystem jail is **per-deployment operator posture**, not a per-run
flag (there is deliberately no "unseal this run"):

```jsonc
"sandbox": {
  "enforcement": "in_process",          // "off" (default) | "in_process"
  "workdir":   { "root": "~/.ppxai/runs", "writable": true, "cleanup": "keep" },
  "read_paths": { "allow": ["~/projects"], "deny": [], "follow_symlinks": false },
  "specs_dir": "/path/to/task-specs",
  "skills_dir": "/path/to/task-skills",
  "allow_skill_scripts": false
}
```

Sealed runs get an empty per-run `work/` dir as their only writable root;
reads are confined to `read_paths.allow` + skill mounts; denials surface as
`path_denied` events. Typical postures: **desktop = seal off** (you are the
trust boundary; the assistant works your repo), **k8s coder pod = seal off**
(the pod is the boundary), **embedded unattended agents = seal on**
(least-privilege over untrusted input). Details + rationale:
[api-gateway.md](api-gateway.md) §"Run working directory".

## 10. Troubleshooting

| Symptom | Cause → fix |
|---|---|
| `403 … task_tier_enabled` | Tier is default-off → enable it in config (§1). |
| `401 Missing or malformed Authorization` | Token store enforces auth → `/token mint` (local) or `/token set`. |
| `422 tools is required` / `400 Empty tool grant` | No grant and no spec/skill supplying one → pass `--tools`. |
| `400 execute_shell_command is not permitted` | By design — shell escapes the egress allowlist; grant specific tools instead. |
| `400 workdir does not exist` | `--work-dir` points at a missing directory. |
| `⚠️ sandbox seal active — --work-dir ignored` | Expected on sealed hosts; the jail wins. |
| Agent says a file "does not exist" | Check `wd:` in `/task get` — pass `--work-dir` or an absolute path. |
| Perplexity `/task` refuses, confabulates, or summarizes an *external* URL | `sonar-pro` is prompt-based and does not reliably call granted tools on `/task` (**Item 43**). Use a native-tool provider (e.g. `nvidia/deepseek-v4-pro`) for tool-capable runs. |
| Gemini 3.x `/task` fails with `400 … missing a thought_signature` | Known gap (**Item 45**): ppxai doesn't yet replay Gemini 3.x `thought_signature`. Use Gemini 2.5 or another native-tool provider for now. |
| Run stuck `waiting` | Answer the card / `/task respond <id> …`, or let the TTL deny it. |
| Result seems missing after finish | It's held — `/task collect <id>`. |
| `409 cannot be resumed: …` | The refusal reason is verbatim (not resumable, in flight, tier off…). |
| `⛔ egress denied host/…` | Host/path not in `--allow` — egress is deny-by-default. |

## 11. HTTP API

Everything above is a thin client over `POST /v1/agent/task`,
`GET /v1/agent/runs[/<id>]`, `…/events?live=1`, and
`POST …/{respond,ack,resume,cancel}` — see
[api-gateway.md](api-gateway.md) (note the `/v1/agent/*` stability
exemption) and
[agent-platform-call-graphs.md](agent-platform-call-graphs.md) for
route→event call graphs.
