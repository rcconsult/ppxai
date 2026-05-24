# ppxai Debt Inventory — Open Items

**Status:** Rolling. This file holds the **currently open** deferred items
across all branches. When an item lands, it moves to "## Closed" with the
commit hash + date. New deferred work added during a branch lands here at
that branch's commit.

This is the canonical location replacing the per-version
`DEBT-INVENTORY-v1.18.2.md` / `DEBT-INVENTORY-v1.18.3.md` pattern (those
are now archived under [docs/archive/](archive/) as historical snapshots).

---

## How to use this file

- **Update on every release branch.** When an item lands, move it under
  "## Closed" with commit hash + date. When new debt surfaces, add it
  to the appropriate section with a `**Planned:**` tag.
- **Tag every open item with where it'll be addressed.** Either a target
  release (`v1.19.x`), a target branch (`feat/<name>`), or a trigger
  condition (`when k8s context`). Untagged items become invisible in
  release planning.
- **Don't mix in feature work.** Debt is bug-class follow-up. Roadmap
  features (Anthropic provider, multi-model routing, etc.) live in
  [ROADMAP.md](../ROADMAP.md).
- **Don't mix in TODOs scoped to a specific in-flight version.** Those
  describe in-flight planning (`TODO-v1.18.x-*.md`); debt describes
  work intentionally **not** in any version's plan yet.
- **Keep entries scannable.** Lead with one short paragraph + the
  `**Planned:**` and `**Trigger to revisit:**` lines + an effort
  estimate. Long context goes in linked docs / archive snapshots.

---

## Open

### Item 3 — k8s session-manager security tests [originally Critique #8 in v1.18.2]

**Affected files:** `deploy/images/session-manager/main.py` (~648 LOC),
`deploy/images/session-manager/ldap_auth.py` (~130 LOC).

**What's wrong:** untested high-risk functions in the multi-tenant
deployment service: `_list_sessions` (risk 0.85), `_teardown_session`
(risk 0.7), `create_session`, `delete_session`, `heartbeat`, `startup`,
`LDAPAuthenticator._hash_password`, `authenticate`. Recommended
scenarios: auth failure, timing-safe hash comparison, K8s resource
naming validation (escape via `..` / `/` in usernames), teardown
idempotency, stale heartbeat cleanup, permissions/secrets handling.

**Why deferred:** zero blast radius for single-user macOS / Windows
ppxai installs (the mainline use case). Only deployers running the
Helm chart in a multi-tenant K8s cluster touch this code.

**Planned:** trigger-deferred — no version target. Open until at least
one of the three triggers fires.

**Branch when ready:** `feat/k8s-session-manager-tests`.

**Trigger to revisit:** when a third-party deploys ppxai multi-tenant,
OR when a security audit demands LDAP/RBAC test coverage, OR when CVE
disclosure procedures need this code to have minimum test coverage.

**Effort:**
- Quick pass (~1 hour): 10 unit tests around `_hash_password`
  (timing-safe), `authenticate` (denial fail-closed), naming validation.
- Full pass (~half day): 30-50 tests with mocked `kubernetes.client`,
  covering all 8 functions.
- Defensive sweep (+ ~half day): LDAP injection patterns, secret-in-log
  scrubbing, kubeconfig path validation.

**Original entry (full design rationale):**
[docs/archive/DEBT-INVENTORY-v1.18.2.md](archive/DEBT-INVENTORY-v1.18.2.md#item-3--k8s-session-manager-security-tests-critique-8).

---

## Recently moved out of debt scope

These items left the debt inventory because they're not bug-fix-class
follow-up — they're feature work belonging on the roadmap, or they
shipped already.

- **Item 14 — Anthropic provider** → moved to roadmap 2026-05-05.
  See [ROADMAP.md §"v1.19.x - Anthropic Provider (planned)"](../ROADMAP.md#v119x---anthropic-provider-planned).
  Original v1.18.2 entry preserved at
  [docs/archive/DEBT-INVENTORY-v1.18.2.md](archive/DEBT-INVENTORY-v1.18.2.md#item-14--add-anthropic-provider-with-explicit-tos-aware-auth-fallback)
  for full design rationale (TOS warning text, OAuth fallback caveats).

---

## Closed (recent)

For full closed-item rationale with commit references, see the per-version
archived snapshots:

- **Item 20 — v1.19.x alignment paperwork (closed 2026-05-24):** merged to
  master as `56bc2d38` (Stage-2 fold rebased from `42ed8f00`) + `7a2ea268`
  (C5 §13 + `AGENT_SERVICE_DOWN`) + `45e352fe` (ROADMAP "Pending alignment
  paperwork" subsection removal). Folds all consumer caveats C1–C5 and asks
  A1–A3 into ADR 0003 §6–§13 with Phase 1/5/7 ROADMAP commitments inline.
  `feat/agent-platform-stage-2` (Phase 1 implementation branch) is now
  unblocked.

- **v1.18.3 branch (closed 2026-05-02):** Items 12 (Node.js 20 → v5),
  13 (release.py step 14 silent-failure), 15 (`deploy/shared/AGENTS.md`
  stale copy), 16 (throttle counters in `/usage`), 17 (qwen3-coder-480b
  excluded after rerun confirmed contamination), 18 (NIM probe rerun),
  19 (Qwen3.5 `enable_thinking` config example), plus Tier 1 #1-3 and
  Tier 2 #4-5 from the v1.18.3 NIM engine work. See
  [docs/archive/DEBT-INVENTORY-v1.18.3.md](archive/DEBT-INVENTORY-v1.18.3.md).

- **v1.18.2 branch (closed 2026-04-29):** Items 1 (god-node refactoring
  narrowed to session_restore_ops), 2 (resolveWebviewView contract
  refactor), 4 (focused-subtree graphify runs), 5 (esbuild VSIX bundle),
  6 (Windows `code` CLI shim), 7-9 (Tier 1 observability), 10
  (EngineClientProtocol), 11 (agent.py logger AttributeError). See
  [docs/archive/DEBT-INVENTORY-v1.18.2.md](archive/DEBT-INVENTORY-v1.18.2.md).

---

## Related documents

- [ROADMAP.md](../ROADMAP.md) — feature work + future direction (multi-model
  routing, Anthropic provider, prompt analyzer, etc.)
- [CHANGELOG.md](../CHANGELOG.md) — what shipped per release
- [docs/archive/](archive/) — frozen historical snapshots, including the
  per-version debt inventories
- `docs/TODO-*.md` — in-flight planning for the current branch (kept
  separate from debt — those are not "deferred", they're "planned now")
