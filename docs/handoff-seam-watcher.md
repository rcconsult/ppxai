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

**Captures are named by commit, never by role.** A fixed path like
`…\ppxai-seam-baseline` cannot hold both sides of a before/after comparison:
the second capture destroys the first, and a diff whose inputs no longer exist
is a *reported result*, not evidence. That path was silently overwritten four
times in one session — each overwrite an improvement, each destroying its
predecessor — before the pattern was named.

```
C:\tmp\ppxai-seam-<shortsha>\      # MANIFEST.txt  ← read this FIRST
                                   # 9 *.normalized.json   (the diff target)
                                   #   *.raw.json          (forensics)
                                   #   *.contentkeys.json  (provider signal)
```

`--record` now **refuses** to write into a directory that already holds a
`MANIFEST.txt`, printing the commit-named path it should have used.
`--force-record` overrides, for when discarding really is the intent.

Standing captures for the `build_task_runner` extraction — both sides kept,
so the byte-identical claim can be re-checked by anyone:

| Path | Commit | Meaning |
|---|---|---|
| `C:\tmp\ppxai-seam-bb55f5ed\` | `bb55f5ed` (clean) | **pre**-extraction |
| `C:\tmp\ppxai-seam-eeb82076\` | `eeb82076` (clean) | **post**-extraction |

`9 identical, 0 differing`. The pre side was reconstructed after the fact by
`git checkout bb55f5ed` → capture → return, which running from source makes
cheap: the tree *is* the code, so any past commit's wire behaviour is one
checkout away. That recoverability is a property worth knowing — but it is
not a licence to overwrite, since it only works while the commit is reachable
and the environment still resolves.

### What 9/9 does NOT cover — the spawn path

**Do not quote "9/9 byte-identical" as covering child runs.** The diff
evidences the *recorded* surfaces, and the seven steps are `/status`, the
token mint, `GET /v1/agent/runs`, both `/v1/oneshot` variants, and the
`agent/run` + `agent/task` lifecycles. **None of them constructs a child
run** — verified by grep: `spawn_subagent`, `allow_spawn`, `respond` and
`consent` appear in `scripts/gateway-smoke.py` only inside a comment about
normalization keys (`:158`).

That gap sits exactly where the extraction changed meaning.
`runner_builder=build_task_runner` in `engine/task_runner.py` is the line
whose *name resolution* moved, and no captured endpoint reaches it. So the
evidence is asymmetric and worth stating plainly:

| Surface | Evidence |
|---|---|
| `/v1/oneshot`, `/v1/agent/*` lifecycles | **wire-level**, standing artifacts on both sides |
| child-run construction / consent park | **unit-level** (`tests/test_runner_builder_patch_point.py`) |

The unit tests are not weak — they include an anti-vacuous guard and a
positive assertion that the `agent_v1` alias is inert — but they are a
different class of evidence from a byte diff.

**If a spawn step is ever added to the smoke, it is the highest-value
addition remaining**, because child-run construction is where ppxai-sre
plans to sit. It needs more machinery than the other steps: `allow_spawn`,
a grant containing `spawn_subagent`, consent config, and a `respond`
round-trip to clear the park.

**`MANIFEST.txt` is written automatically by `--record`**, not by hand — it
carries the capture time, the commit and clean/dirty state, the branch, which
server answered (spawned binary + build time, or a `--base-url` target), the
provider/model that actually replied, and the per-step results. It shouts
`NOT A USABLE BASELINE` if any step failed.

This exists because the alternative was demonstrated: seven capture
directories accumulated in `C:\tmp` during one session, all with identical
file names, and the only way to tell them apart was mtime and content
diffing. That is inference, not documentation — the same failure as an
artifact nobody can find, wearing a different costume. **Only this one
directory is authoritative; scratch captures should be deleted, not left
beside it.**

Outside the repo on purpose — it is machine state, not source, and the raw
bodies carry per-host run ids and a minted bearer. `C:\tmp` survives across
sessions.

Authoritative values live in `MANIFEST.txt`; the table below is orientation
only and will go stale — trust the file.

| Property | Value |
|---|---|
**The recipe is two steps: commit, then capture.**

```bash
git status --porcelain -- ppxai      # must be empty
uv run python scripts/gateway-smoke.py --record C:\tmp\ppxai-seam-baseline
```

| Captured with | `uv run python scripts/gateway-smoke.py --record <dir>` |
| Result | 7 passed, 0 failed, 0 skipped |
| Reproducibility | **9/9 normalized files byte-identical** across two independent captures |
| Server under test | **ran from source** — the working tree itself |

**Why `uv run`, and why no build.** Under `uv run` the script can import
`ppxai`, so when the resolved binary is stale it spawns
`python -m ppxai.server.http` from the checkout instead. The tree *is* the
code, so the capture's provenance is simply the commit the manifest records
— there is no build artefact whose currency has to be argued. Under a bare
`python` the import fails (the venv holds fastapi/dotenv), the script falls
back to the frozen binary as designed, and the manifest says so.

**The manifest validates this; it does not merely describe it.** A capture
whose server predates the last commit touching `ppxai/` is stamped
`*** WEAK PROVENANCE ***` naming that commit, and so is one taken with
`ppxai/` dirty. Absence of the banner is the check having run, not the check
being absent.

**Do not capture via `--base-url`.** The script cannot identify a server it
did not start and says so in place of provenance. This artifact is the
trusted "before" side of the extraction diff, so a byte-identical claim
inherits whatever provenance it rests on.

**Superseded recipes, for anyone reading older notes.** Earlier baselines
argued currency by reasoning about which commits had touched `ppxai/server`
and `ppxai/engine` since a build; a later one used commit → build → capture
so the binary's mtime provably followed a clean HEAD. Both were sound. Both
are now unnecessary: running from source removes the artefact being reasoned
about. The installed `~/.ppxai/bin/ppxai-server.exe` (2026-08-06 14:51) is
in any case unusable — it predates the Gemini `response_format` fix, and the
default invocation used to spawn it silently.

**The baseline has already moved once, silently.** Before manifests existed,
the documented path was overwritten by a later, better capture (8 files → 9,
after the structured step landed). Coverage improved, but a reader who had
seen the earlier one had no way to know. That is what `MANIFEST.txt` is for.

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
Compare only `*.normalized.json` — `*.raw.json` and `*.contentkeys.json` are
expected to vary (see below).

### Finding (FIXED): the Gemini path dropped `response_format` entirely

Added on consumer request, because the plain call only evidences the envelope
and ppxai-sre's Pattern A classifier depends on the schema-enforced path. The
step found a real defect on its first run.

**What was wrong.** `ppxai/engine/providers/gemini.py::oneshot` accepted
`response_format` to satisfy the `BaseProvider` contract and then never read
it — its own docstring said so ("response_format is not forwarded … out of
scope for this stateless path"). Gemini uses `generate_content`, which has no
such parameter, and nothing mapped it onto the equivalent knobs. So the
schema **never reached Google at all**.

An earlier revision of this note said "enforcement is the provider's and this
provider does not do it". That was wrong, and wrong in a way that would have
sent you looking at the wrong layer — Google never saw the schema. The
measurement that produced it also had a confound: the probe prompt said
"reply with JSON only", so the JSON came from the prompt, and the varying key
sets were ordinary unconstrained generation.

Gemini was the **only** provider affected. `openai_compat.py:591`,
`openai_native.py` and `perplexity.py` all forward `response_format` verbatim
into `request_kwargs`; only the non-OpenAI path needed a mapping and lacked
one. It was also the config default on this host, which is why the baseline
caught it.

**The fix (v1.19.1).** `response_format_to_gemini()` maps the OpenAI shape
onto `response_mime_type` / `response_schema`:

- `{"type":"json_object"}` → JSON mime type, model picks the shape.
- `{"type":"json_schema", …}` → JSON mime type + the schema, run through the
  existing tool-schema sanitizer and then stripped of `additionalProperties`.
  The strip is load-bearing and the mechanism is worth knowing: the
  google-genai SDK's `Schema` model **accepts** that key — so nothing fails
  client-side — while the REST API answers `400 INVALID_ARGUMENT — Unknown
  name "additional_properties" at 'generation_config.response_schema'`. It is
  in virtually every OpenAI-generated schema. **Passing SDK validation is not
  evidence the API will accept a payload**, and only a live call surfaces the
  gap: this one was found by a 502 after unit tests were green.
- A schema **suppresses Google Search grounding** for that call; Gemini
  refuses the combination, the same way it refuses grounding alongside
  function declarations.

Live-verified end to end, not just unit-tested: against
`gemini-3.1-pro-preview` the smoke now reports `schema=enforced`, and the
recorded key set went from the model's invention
`[category, intent, urgency]` to exactly the pinned
`[confidence, intent, reasoning, suggested_action]`.

**No seam change.** A capture from the patched tree matches the installed
baseline on all `/v1/*` artifacts byte for byte. The single differing file is
`01-GET-status`, on `model`/`provider` — session selection, not contract
(one server had `custom`/Qwen selected, the other `perplexity`/sonar-pro).

Recording notes that outlive the fix:

- The smoke step **reports** conformance rather than asserting it: the
  gateway owes you that response_format reaches the model and the envelope
  holds, not that a given provider honours it.
- The key set lives in `*.contentkeys.json`, outside the diff target — it is
  provider behaviour, not seam contract.
- `content` is volatile in the normalized artifact: model output is never a
  wire contract, only its type is.

## Open at time of writing

- The ADR 0010 grep above has **never been run** against ppxai-sre.
