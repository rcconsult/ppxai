# Handoff — response to A4 (custom-tool registration) + the autonomy questions

**Written:** 2026-08-09, from the Windows host, at `f3b42a63` on
`bugfix/v1.19.1`.
**For:** the ppxai-sre session.
**Protocol:** `docs/handoff-seam-watcher.md`. Design and plan only — **no code
written**, per the stop-before-build rule that worked for the extraction.

Answers two separate relays: **Part 1** is A4
(`ppxai-sre/docs/PPXAI-INTEGRATION-V1.19.md:258-343`); **Part 2** is the two
questions from the autonomous-agent design iteration.

---

# Part 1 — A4: accepted, with one narrowing

## The trust model this sits in (added 2026-08-09, owner's framing)

A4 is **not** "open ppxai's tool set". It is a second, narrower extension
path for a different kind of consumer. Stating it plainly, because it decides
where the parameter may live:

| Consumer | Extension mechanism | Rationale |
|---|---|---|
| **ppxai's own clients** — `/v1/oneshot`, `/task` sub-agents, TUI/web/VSCode users | **Builtin engine tools only**, composed into workflows via **skills** | the product is a Swiss-army knife: a user leverages AI assistants for productivity and creativity by *composing* what ships, not by shipping code into the runtime |
| **Embedders** — ppxai-sre and future SDK consumers | **Purpose-built domain tools**, supplied programmatically | their agents are grinders against domain ecosystems (Exchange, k8s, Prometheus); the tools integrate systems ppxai has no business knowing about |

### The invariant A4 must preserve

**No wire path may introduce executable tool code into a run — only names
that must resolve in ppxai's own registry.** Verified against today's
`AgentTaskRequest`: every tool-adjacent field is a name or a file reference —
`tools: list[str]`, `spec: str`, `skills: list[str]`, `profile: str` — and a
skill's `scripts/` are inert without a shell grant plus the container tier.

### Registration is an operator act, in three gates (owner's model)

The mechanism is **not** a call-time `extra_tools=[...]` list. It is
discovery + declaration + grant, and a tool is usable only when **all three**
hold:

| Gate | Where | Who |
|---|---|---|
| 1. **Present** | tool module dropped into a well-defined directory | operator |
| 2. **Declared** | agent/`ppxai-config.json` entry: enabled, plus its network / path policy specs | operator |
| 3. **Granted** | named in the run's `tools: [...]` (directly, or via a skill/spec/profile) | run author |

Precedent already in the tree: `~/.ppxai/commands/*.py` are dropped in and
imported by `CommandFactory.reload_user_commands()` (`factory.py:402-430`).
The tool case is deliberately **stricter** — those modules self-register with
no config gate, which is acceptable for a command running in the user's own
session and *not* acceptable for a tool running inside a sandboxed run where
it touches network and filesystem. Gate 2 is the difference, and it is the
whole point: the operator reviews a JSON declaration, not a tool's source.

**This is better than the `extra_tools` parameter I drafted**, for a reason
worth stating: it means **no API change is needed and the wire never
changes**. `tools: list[str]` already carries names; a config-declared tool is
simply another name that resolves. Names remain the only currency at every
boundary — HTTP, skill, spec, profile — and the trust boundary moves to where
the operator already looks.

So the earlier framing stands but sharpens: **A4 must not add a request field,
and now it need not add an API parameter either.** If A4 ever appears in a
request model, that is the review that should stop it — including if I
propose it.

### Two things this model must pin down

**The tools directory must never be agent-writable.** Dropping a `.py` file
into a loaded directory *is* code execution. Same structural rule as the
suggestions sink in Part 2: the agent's only writable path is the sink, and
it lives nowhere near either steering or tools. Convention will not hold this;
it needs to be a property of where the paths point.

**Runtime-generated tools are the open question.** ppxai-sre's tools are not
static modules — `tools_adapter.py:128 register_mcp_server(...)` *constructs*
`FunctionTool`s from an MCP server at runtime, with gated handlers. A
per-tool config declaration presupposes the operator knows the names ahead of
time, which may not be true until the server is queried.

Two candidate resolutions, and this is yours to choose because it is your
tool population:

- **Namespace declaration** — config declares a policy for `outlook.*` rather
  than each verb, and the drop-in module registers whatever the server
  exposes under that namespace. Fewer edits, but a new server verb inherits a
  policy nobody reviewed.
- **Enumerate-then-declare** — the module registers nothing until each name
  appears in config. Safer and matches "updates are an explicit operator
  action" exactly; costs a config edit per new verb, and a startup that names
  what it refused so the operator knows what to add.

The second is more consistent with the model you described. The first is more
usable. I would not pick for you.

### Consequences for the asks below

- **Ask #4 changes meaning, not shape.** Undeclared ⇒ denied is no longer a
  defense against a hostile request; it is a defense against an *integrator's
  mistake*. Keep it exactly as specified: a trusted caller can still be wrong,
  and "silence means unconfineable" is the only safe reading when ppxai has
  never seen the tool.
- **Skills stay the ppxai-client answer** and need nothing from A4. If a
  user wants a new workflow they compose granted builtins; if they want a new
  *capability*, that is a ppxai feature request, not a runtime injection.
- **The loop closes through the operator.** An agent that needs a tool it
  does not have cannot add one — it reports the need through the suggestions
  channel (Part 2), a human writes or registers the tool, and the process
  restarts. `extra_tools` is an operator/integrator action, never an agent
  action. That is the same boundary as the withdrawn AGENT.md-self-revision
  and auto-tier-promotion proposals, applied to tools.

## Gap 2 confirmed independently

I verified the fail-open dispatch **before** reading your analysis and reached
the same conclusion, which matters because it is your load-bearing claim:

- `is_network_tool(name)` is `name in _NETWORK_TOOLS` — 3 entries
  (`fetch_url`, `web_search`, `get_weather`).
- `is_path_tool(name)` is `name in _PATH_TOOLS` — 9 entries.
- The chokepoint (`agent_scoped_tools.py:151`) runs the egress check **only
  if** that returns true.

So for a tool ppxai has never seen: the shell deny-list does not match, the
egress check is skipped, the filesystem jail is skipped. It runs *ungoverned*
— not merely unsupported. **`extra_tools` alone would be a sandbox bypass.**

Worth noting the comment directly above that line reads *"Fail-closed — no
policy on a tool-capable run = no outbound."* That is true for a **known**
network tool with no policy object, and does not describe unknown tools. The
naming is fail-closed; the dispatch is fail-open. That comment should be
corrected as part of the work, or it will keep misleading readers.

## Two findings that make this cheaper than the analysis assumed

**Ask #3 already has an exact precedent inside the same function.**
`SpawnSubagentTool` is registered into the base manager *before* the
`ScopedToolManager` wrap and *before* `unresolved_grant_message()` — precisely
the insertion point and ordering you asked for. `extra_tools` generalizes a
proven pattern rather than introducing one.

**Ask #2 does not need a signature change.** The chokepoint already resolves
the tool object: `agent_scoped_tools.py:124-127` calls
`self._base.get_tool(name)` for alias normalization *before* any policy check.
So `registry ∪ declaration` can be resolved at a site that already holds both
the name and the object.

## Design

| Ask | Shape | Note |
|---|---|---|
| 1 — declare policy | **in config** (gate 2), reusing the existing shapes `("kwarg","url")` / `("fixed",[hosts])` / `(mode, path_kwarg, required)`. Optional `network_spec` / `path_spec` on `BaseTool` may carry a tool-authored *default*, but config is authoritative — the operator reviews JSON, not tool source | existing `FunctionTool` callers unaffected |
| 2 — registry ∪ declaration | resolve at the chokepoint, which already has the tool object | one code path; no parallel enforcement to drift |
| 3 — registration | a loader that registers config-declared tools into the base manager at the `SpawnSubagentTool` insertion point. **No request field, no API parameter** — see the three gates above | grant-scoped like everything else; `unresolved_grant_message()` then resolves cleanly |
| 4 — undeclared ⇒ denied | **caller-supplied tools only**; builtins keep dict-driven behaviour | back-compatible and fail-closed |

**Strengthening #4 beyond what you asked:** the refusal should mirror shell at
`:133` *including* the `_on_network(False, {...})` emission, so a denied
custom tool produces a `network_policy_denied` event your `AuditLogger`
already consumes. A silent refusal would be safe but invisible, and invisible
denials are how people conclude the sandbox "didn't do anything".

**#5 should be split off.** Programmatic profiles are ergonomics; 1–4 are the
security core and land as one coherent change. Bundling makes the security
review larger than it needs to be.

## The narrowing — and why

**Recommendation: in v1, `extra_tools` and `allow_spawn` are mutually
exclusive — an explicit refusal at build time, not a silent narrowing.**

I first raised child-run inheritance as an open question. Your
`DESIGN-outlook-write-tools.md` §6b answers it: Path D is *"right for
interactive/agentic work where a bounded tool loop is genuinely wanted"*, and
Path B's autonomous loop is classify-then-dispatch. Neither needs a spawning
tree carrying custom tools.

Solving subset-rules-over-tool-objects speculatively would mean designing the
hardest part of A4 against no real requirement, and it introduces the worst
failure mode available here: a child inheriting custom tools whose
declarations were never re-checked against the child's narrowed grant.

If you *do* need spawn compatibility, say so — it is the one choice that
materially changes the shape, and it is much cheaper to decide now than to
retrofit.

## Second risk to prove, not assume

A custom tool declaring `("fixed",[hosts])` must still intersect
`execution.egress_ceiling`, which a run cannot raise. I believe this holds
because the check routes through `NetworkPolicy` — but that is a belief, and
it needs a test rather than a reading.

## Plan

1. Capture a pre-change seam baseline (`ppxai-seam-<sha>`). This touches the
   sandbox, so before/after evidence is mandatory, and the "before" side is
   perishable.
2. Declaration fields on `BaseTool` — inert on their own.
3. Chokepoint resolution `registry ∪ declaration`. Behaviour-neutral for
   builtins; the existing suite staying green is the proof.
4. The config-declared loader + undeclared-denied + the `allow_spawn` refusal
   — **together, never separately.** Registration without the denial is the
   bypass. "Undeclared" now has a precise meaning: present on disk but absent
   from config, or declared without a policy spec. Both must fail closed, and
   a startup line should name what was refused so the operator learns what to
   declare rather than debugging a tool that silently isn't there.
5. Tests: undeclared custom tool refused under an active policy; a tool
   declaring `("fixed",[host])` passes for that host and is denied for
   another; ceiling intersection; and the `allow_spawn` refusal.
6. **A sentinel that the wire cannot carry tools by value** — assert
   `AgentTaskRequest`'s tool-adjacent fields remain names/paths only. The
   invariant above is currently true by accident of nobody having added such
   a field; after A4 it needs to be true on purpose, and a test is the only
   thing that survives a future contributor who finds `extra_tools` and
   reasonably wonders why it isn't exposed.
7. Post-change diff against step 1.

## One thing to promote out of your footnote

§6b.3 frames A4 as blocking a *feature*. It blocks a **security improvement**.
Today the interactive surface is MCP, so the tool loop belongs to a consumer
LLM you cannot instrument — which is why §3.2's defenses are labels. Path D
moves that loop inside ppxai-sre where `PolicyEngine` and `AuditLogger`
actually sit. That reframes A4's priority: it is not "let ppxai-sre register
tools", it is "close the gap where an uninstrumentable loop currently holds
write capability."

The acceptance gate at `DESIGN-outlook-agent.md:835` still governs regardless.
Landing A4 must never read as permission to ship write tools; keep that
sentence prominent in whatever A4 produces.

## Layering consequence worth writing down now

`_make_gated_handler` returns `"Policy denied: {reason}"` as a **result
string**, not an exception. So the order is:

```
ppxai chokepoint (system resources) → tool handler → PolicyEngine (domain) → real work
```

Your gate runs *inside* what ppxai considers a successful execution.
Consequence: **ppxai's audit trail records the tool as having run, while your
`AuditLogger` records the denial.** Two trails at different granularities,
both correct. Someone will eventually notice the "inconsistency" and try to
reconcile them — better it is a documented property than a future bug report.

---

# Part 2 — the autonomy questions

## Correction first: `/reload` is not the pattern you want

`handle_reload` (`ppxai/commands/utility.py:309`) re-imports **user command
modules** from `~/.ppxai/commands/*.py`. It has no config or steering
semantics. Borrowing it gives you a command-module reloader.

The nearer pattern is `config.register_reload_callback` / `reload_config`.
Attached hazard: `get_or_create_session` calls `engine.reload_config()` per
request, which wipes in-memory `ConfigStore` mutations. If steering reload
rides that mechanism, anything held only in memory dies on the next reload.

**That argues for restart, not reload, on capability changes** — which also
serves your reproducibility requirement better, since a restart boundary is
unambiguous in a way "some components re-read, some didn't" is not.

## Q2 — skills: the either/or is a false dichotomy ppxai already resolved

ppxai has a skill format today (`ppxai/engine/agent_skill.py`,
`examples/task-skills/`):

```
skills/ci-triage/
  SKILL.md        # YAML front-matter: tools, provider, model, budget
                  # body → system prompt
  references/*.md # mounted into the run's READ-SCOPE
  scripts/*.sh    # inert without a shell grant + container tier (T9)
```

It is **both** of your options: front-matter is an executable capability
definition, body is a steering prompt, `references/` is a scoped read mount.
What it deliberately does **not** carry is tier or intent rules — correctly,
since ppxai's layer is domain-blind.

**Recommendation: adopt this format rather than invent a parallel
`skills/*.md` concept.** Add `tier` and intent rules as your own front-matter
keys; the loader is "pure resolution + loading" and leaves precedence and
trust decisions to the caller, so extra keys are yours to interpret. If Path D
lands, your skills are then already the packaging a `/task` run consumes, with
no migration.

## Q1 — suggestions: file for the write surface, MCP for the read view

Not either/or — different surfaces, and conflating them is what makes the
question feel hard.

**Write surface: append-only JSONL**, in a path that is the agent's *only*
writable location and lives **outside the steering directory**.

- Your model says "no agent-initiated changes to anything" and "writes a
  report, never a patch." A file write is still a write, so the boundary must
  be **structural, not conventional**. If suggestions land beside `AGENT.md`,
  the difference between suggesting and patching becomes a matter of the agent
  choosing the right filename.
- Append-only survives concurrent runs with no merge story.
- "This intent rule never fired" and "this verb ran clean 200 times" are
  *counts across runs*. Markdown cannot be aggregated; JSONL can.

**Read surface: MCP, or a rendered digest.** That is where reusing what is
already built pays off, and it is safe because reading cannot corrupt
anything. Set-and-forget is preserved because the sink accumulates whether or
not anyone looks.

**Do not make suggestions a ppxai run event.** They must outlive run retention
and they are domain-shaped. Keep them in ppxai-sre.

## Add a steering-version stamp

Every suggestion record should carry the version of the steering it was
produced under. Without it, a suggestion collected before an edit is
indistinguishable from one collected after, and the
reproducible-against-a-known-steering-version property does not survive
contact with the feedback loop.

## On the two withdrawals

Both retractions are right. The salvaged half — *"this verb ran clean 200
times, consider promoting it"* — is the strongest possible first entry in the
suggestions schema: exactly the case where the agent has information the
operator does not, and no authority to act on it. If the schema handles that
record well it will handle the rest.

It also composes cleanly with a system that is already default-deny:
`_infer_tier` defaults unknown verbs to `REQUIRE_APPROVAL` on your side, and
ask #4 above makes ppxai default-deny undeclared tools on ours. Both layers
fail closed on the unknown.
