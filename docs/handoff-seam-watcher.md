# Handoff — standing seam-watcher role for the ppxai-sre session

**Written:** 2026-08-08, from the Windows host, at `bbba6fbc` on
`bugfix/v1.19.1` (tree clean).
**For:** the parallel Claude Code session working
`C:\git\utils\ppxai-sre` (on `master`), and for whoever runs the next
ppxai session on this host.

This file is the **coordination protocol** between the two sessions plus
the **steering prompt** to paste into the consumer side. It is not about
any one change; it stays valid until the seam itself changes.

---

## Why this exists (read once)

Two Claude Code sessions run concurrently on this Windows host: one on
this repo (producer), one on `ppxai-sre` (consumer). **They cannot talk
to each other.** Claude Code's cross-session messaging is unavailable on
native Windows — delivery rides a per-session Unix domain socket, so the
feature is macOS/Linux only (including WSL 2). Verified on this host at
v2.1.226 by three independent negatives: no `ListAgents` tool, no
`CLAUDE_CODE_MESSAGING_SOCKET` export, no `~/.claude/teams/`.

Do not promise, plan around, or re-investigate direct session-to-session
messaging here. The relay is the human, and the medium is this file plus
`docs/handoff-<topic>.md` notes.

Agent teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) are *not*
OS-gated and would work — but a team only ever **spawns** teammates and
can never adopt an already-running session, so it does not solve this.

## The protocol (agreed 2026-08-08)

1. **Relay lives in this repo only.** Producer-side findings go in
   `docs/handoff-<topic>.md` here. Neither session writes into the
   other's tree, even where working directories permit it — two sessions
   writing one tree with no coordination is exactly the hazard being
   avoided.
2. **Stop before committing** when a seam check trips. Do not
   proceed-and-log. Write the note, hand the human a summary, wait for
   the consumer verdict relayed back.
3. **The loop closes through the human, or not at all.** Silence from the
   other session is not an all-clear.

### Producer-side gate (this repo, before any seam-touching commit)

| Check | Command |
|---|---|
| `/v1/oneshot` wire shape | `scripts/gateway-smoke.py` (needs a running `ppxai-server`; take a green baseline *before* changing code — a lone green run after the fact proves little) |
| Stale config keys | `/doctor` → `Config shape (ADR 0010, v1.19.1)` section, which scans the config **file** because nothing at runtime reads the old paths |

### The seam

| Surface | Status | Consumer |
|---|---|---|
| `POST /v1/oneshot` req/resp + bearer auth | **frozen, byte-identical since v1.18.4** | `agents/outlook-monitor/*.md` |
| `/v1/agent/*` C1–C4 fields | LOAD-BEARING, agreed in writing | `libs/core/` |
| `NETWORK_POLICY_DENIED`/`_ALLOWED`, `AGENT_RUN_START{run_id,parent_run_id}`, `AGENT_BEAT` | committed wire shapes | `AuditLogger`, `policy.py`; `heartbeat.py` **emits** these (`:99`, `:133` via `events.py:56`) rather than parsing our stream — the contract is "the enum member and its data shape keep existing", not "we consume your feed" |
| `~/.ppxai/runs/<run_id>/agent-<n>/` + `state.json`/`meta.json` | namespace shape — **frozen as a planned dependency, NOT a live reader** | *nothing in ppxai-sre reads it today.* Corrected 2026-08-08 by the consumer session: `libs/core/src/ppxai_sre_core/agent.py::AgentRegistry` is a 25-line `dict[str, type[SREAgent]]` class registry (`register`/`get`/`list_agents`/`create`) that never touches the filesystem; the only fs hit in `libs/core/src/` is `config.py:9`, a docstring naming `~/.ppxai/sre-config.yaml`. Keep the freeze, but don't price a change as if it had a live consumer |
| `execution.*` / `tools.agent.*` keys | clean break, no dual-read → **fails silently** | k8s ConfigMap (this repo's verified clear; ppxai-sre unverified) |

Authoritative consumer-side contract:
`../ppxai-sre/docs/PPXAI-INTEGRATION-V1.19.md` (C1–C4 + A1–A3) and
ADR 0003 §6–§12 in this repo.

## The steering prompt

Paste verbatim into the ppxai-sre session:

```text
STANDING ROLE — ppxai seam watcher (for this ppxai-sre session)

A parallel Claude Code session is working the ppxai producer repo at
C:\git\utils\ppxai (branch bugfix/v1.19.1, unreleased). You are the
consumer side. Our two sessions CANNOT message each other — Claude Code
cross-session messaging is unavailable on native Windows — so the human
relays between us. Do not wait for or expect direct contact.

BOUNDARY: do not write to C:\git\utils\ppxai. Read it freely. All your
output lands in ppxai-sre or in your reply to the human. The ppxai session
is under the mirror-image rule and will not write here.

WHEN THE HUMAN HANDS YOU A HANDOFF NOTE
They'll point you at C:\git\utils\ppxai\docs\handoff-<topic>.md. For each
one, answer exactly one question: does this break ppxai-sre? Check, in
this order, and cite file:line for anything you find:

  1. agents/outlook-monitor/{AGENT,TOOLS,RUNBOOKS,README}.md
     — consumes POST /v1/oneshot. That wire shape (request, response,
       bearer auth) has been byte-identical since ppxai v1.18.4. Any
       change to it is a hard break, not a migration.
  2. libs/core/
     — agent.py::AgentRegistry reads ~/.ppxai/runs/<run_id>/agent-<n>/
       plus state.json / meta.json (namespace shape is load-bearing)
     — heartbeat.py consumes EventType.AGENT_BEAT
     — policy.py wraps the per-run network-policy primitive
     — AuditLogger consumes NETWORK_POLICY_DENIED / _ALLOWED and
       AGENT_RUN_START{run_id, parent_run_id}
  3. Any chart, ConfigMap, or Helm values under mcp-servers/, scripts/,
     or deploy paths that set ppxai config keys.
  4. docs/PPXAI-INTEGRATION-V1.19.md — C1–C4 are marked LOAD-BEARING and
     were agreed in writing. If a handoff contradicts one, say so
     explicitly; that's a broken agreement, not a preference.

Report back to the human as: VERDICT (breaks / does not break / unclear),
then the evidence, then the migration needed if any. If a claim in the
handoff note is wrong, say that plainly — the last one contained a
warning that turned out to be broader than reality, and catching it
avoided a bad ConfigMap edit. Verify, don't assume: run the grep, open
the file. Don't reason from import surface or filenames.

FIRST TASK, do this now — it is already outstanding
ADR 0010 moved six ppxai config keys off tools.agent.* with NO dual-read.
There is no grace period and no warning: a key left at an old location is
silently ignored and the setting reverts to its default. The ppxai session
verified its own repo but could never verify this one.

  grep -rn "task_tier_enabled\|spawn_consent\|consent_ttl_s\|result_retention_s\|default_subagent" C:\git\utils\ppxai-sre

Empty result = ppxai-sre needs nothing; report that. Any hit = report the
file:line and migrate per the table in
C:\git\utils\ppxai\docs\handoff-adr0010-k8s.md before any v1.19.1 server
rolls. Also note: GET /agent/config changed shape in that commit (six tier
keys dropped). It's an internal endpoint, not /v1/*, but if anything here
scrapes it, flag it.
```

Two properties of that prompt are deliberate and should survive edits:

- **It is told to push back.** `docs/handoff-adr0010-k8s.md` exists
  because the first verbal warning was wrong and broader than reality. A
  watcher that only ever confirms is worth nothing.
- **Its first task is concrete work, not a posture.** The ADR 0010 grep
  has been open since 2026-08-06, is one command, and doubles as a live
  test of whether the relay loop functions — before anything depends on
  it mid-change.

## The captured baseline — where it is

**Taken 2026-08-08. It is NOT in this repo**, which is why a reviewer looking
for `*.normalized.json` under version control correctly found nothing and
reasonably concluded it had never been captured. It had. An artifact nobody
can locate is functionally missing, so its location is recorded here:

```
C:\tmp\ppxai-seam-baseline\        # 8 *.normalized.json + *.raw.json
```

Outside the repo on purpose — it is machine state, not source, and the raw
bodies carry per-host run ids and a minted bearer. `C:\tmp` survives across
sessions.

| Property | Value |
|---|---|
| Captured with | `python scripts/gateway-smoke.py --record <dir> --port <p>` |
| Result | 6 passed, 0 failed, 0 skipped |
| Reproducibility | **8/8 normalized files byte-identical** across two independent captures |
| Server under test | installed `~/.ppxai/bin/ppxai-server.exe`, built 2026-08-06 14:51:47 |
| Currency | that build postdates `573b76ff` (last server/engine commit, 14:09:39) by 42 min, so it carries ADR 0010; the only engine commit since is the grammar port, which nothing imports |

**Trap worth knowing:** without `--base-url`, `gateway-smoke.py` spawns the
**installed binary**, not the repo tree. A baseline is therefore of whatever
is installed — check its mtime against the last `ppxai/server` /
`ppxai/engine` commit before trusting it, exactly as above.

After `build_task_runner` moves, capture again to a fresh dir and compare:

```bash
for f in /c/tmp/ppxai-seam-baseline/*.normalized.json; do
  cmp -s "$f" "/c/tmp/ppxai-seam-after/$(basename "$f")" || echo "DIFFERS: $(basename "$f")"
done
```

Expect zero output. Anything listed is a seam change and stops the commit.

## Open at time of writing

- The ADR 0010 grep above has **never been run** against ppxai-sre.
