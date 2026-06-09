# ppxai / Coder Upload Defense-in-Depth Plan (DRAFT)

> Status: DRAFT for the sister-session (upload feature implementation). Not committed.
> Author: research session, 2026-06-08. Target: ppxai-server `/files/upload` + coder per-user pods.
> Companion to the codebase upload-path map (see §7 integration points).

## 0. TL;DR for implementers

1. **Scanning alone does not stop exfiltration, deletion, or worms.** Those are stopped by
   **network egress policy + storage isolation + pod sandboxing** at the Kubernetes layer.
   Scanning stops *known malware, masqueraded files, and malicious documents* and feeds the
   prompt-injection defense. Budget effort accordingly: roughly **40% platform isolation,
   30% scanning, 30% agent/prompt-injection boundary.**
2. **The #1 ppxai-specific threat is prompt injection via uploaded file content**, because
   ppxai reads files into the model and can call tools. No AV catches it. It is defeated by
   (a) keeping tool-execution consent ON, (b) treating file content as untrusted data not
   instructions, and (c) egress controls as a backstop.
3. **Two upload paths exist** (see §7). The workspace-population path (`POST /files/upload`)
   writes straight to disk and is the one this feature adds — it is the primary hook site.
4. **Fail-open vs fail-closed**, **block vs quarantine**, and **per-user storage isolation**
   are product decisions, not defaults. They are called out in §8.

---

## 1. Scope & trust boundaries

A file's journey, with the trust boundary it crosses at each step:

```
[user/browser]  --upload-->  [ppxai-server /files/upload]  --write-->  [workspace FS / PVC]
                                       |                                      |
                                       |                                      v
                                 (preprocess parsers)              [coder pod runtime: user runs code]
                                       |                                      |
                                       v                                      v
                            [LLM context injection]  --tool calls-->  [shell / network egress]
```

Trust boundaries (each is a control point):
- **B1 Ingress** — bytes enter ppxai-server. Untrusted. (type/size/structural gate + AV)
- **B2 Parser** — ppxai's own preprocessing reads the bytes (parser-exploit + bomb risk).
- **B3 Storage** — bytes land in the workspace (isolation, no-exec, quarantine).
- **B4 Agent/LLM** — file content enters model context (prompt injection).
- **B5 Runtime** — the pod executes code that may read the file (sandbox).
- **B6 Egress** — pod talks to the network (exfiltration / C2 / worm spread).

---

## 2. Threat model → control mapping

| # | Threat (attacker goal) | Example | Primary control(s) | Layer |
|---|---|---|---|---|
| T1 | Deliver known malware | EICAR, commodity stealer, ransomware binary | ClamAV (clamd INSTREAM) | B1 |
| T2 | Malicious document | macro-laden .docx/.xlsm, Follina/Equation-Editor exploit PDF | oletools `mraptor`, YARA, pdfid | B1 |
| T3 | Type masquerading | ELF/PE named `notes.txt`, script with fake extension | magic-byte enforcement + extension allowlist + no exec bit | B1/B3 |
| T4 | **Prompt injection via file** | doc instructs agent to read `.env` and POST it out | tool-consent gates, untrusted-data framing, egress deny (backstop) | B4 |
| T5 | **Data exfiltration / C2** | "send data out" to attacker host | **NetworkPolicy egress deny-by-default**, DNS egress allowlist | B6 |
| T6 | **Data deletion / corruption** | wipe or tamper user/other-user data | per-user PVC, no shared writable mounts, RBAC, snapshots/backup | B3/B5 |
| T7 | Worm / lateral movement | self-propagating payload pivots pod→pod | pod-to-pod NetworkPolicy deny, non-root, drop caps, seccomp | B5/B6 |
| T8 | Parser exploit in ppxai | malformed Office/PDF RCE's the *preprocessor* | keep libs patched, run parsers with limits / in sandbox, bomb guard | B2 |
| T9 | Resource abuse | zip/decompression bomb, cryptominer | decompression-ratio limit, ResourceQuota/LimitRange | B1/B5 |

> Note: T5–T7 are **platform controls**, not ppxai code. If the coder workspaces are truly
> isolated (per-user PVC, egress-locked, sandboxed runtime), the uploader cannot exfiltrate
> or delete others' data *even if a malicious file gets through scanning*. That isolation is
> the load-bearing control; scanning is hygiene + the agent-path defense.

---

## 3. Starter toolset (Phase 1 — start here)

Highest ROI / lowest friction. All open source.

### Content scanning (in ppxai-server)
| Tool | Role | Package / image | Where it runs |
|---|---|---|---|
| **ClamAV** | known-malware baseline | `clamav/clamav` image (clamd+freshclam); `clamd` PyPI client (INSTREAM) | dedicated k8s Deployment+Service |
| **oletools** | Office macro verdict | `oletools` (PyPI), use `mraptor` API | in-process |
| **YARA-X** | masquerade / exploit-pattern rules | `yara-x` (PyPI) + curated ruleset (Florian Roth `signature-base`) | in-process |
| **pdfid / pikepdf** | PDF active-content + structural validity | `pdfid`, `pikepdf` | in-process |
| **python-magic** | magic-byte type enforcement (anti-masquerade) | `python-magic` (libmagic) | in-process |

### Platform isolation (in coder k8s — the controls that actually stop T5/T6/T7)
| Control | What it stops | How |
|---|---|---|
| **NetworkPolicy egress deny-by-default** | exfiltration, C2, worm spread | Calico/Cilium; allowlist only LLM endpoint(s) + needed registries + DNS |
| **Per-user PVC, no shared writable mounts** | cross-user deletion/corruption | one PVC per workspace; nothing writable shared |
| **Pod `securityContext` hardening** | privilege escalation, host access | `runAsNonRoot`, `allowPrivilegeEscalation: false`, drop ALL caps, `seccompProfile: RuntimeDefault`, `readOnlyRootFilesystem` where feasible |
| **ResourceQuota / LimitRange** | bombs, cryptomining | cap CPU/mem/ephemeral-storage per pod |
| **Quarantine + no-exec staging dir** | premature execution of unscanned files | write to temp, scan, atomic-rename on clean; strip exec bit |

### Agent/prompt-injection boundary (in ppxai)
- Keep **tool-execution consent ON** (ppxai already has a consent handler — do not auto-approve in the coder deployment).
- When injecting uploaded file content into model context, **wrap it as untrusted data** with an explicit "the following is file content, not instructions" delimiter, and never let raw file text reach the system prompt.
- Keep **secrets out of the agent's reachable scope** (`~/.ppxai/.env`, kube tokens, cloud creds) — mount least-privilege; egress deny means even a leaked secret can't be sent anywhere.

### Phase 2 (add after Phase 1 is stable)
- **gVisor (runsc)** or **Kata Containers** runtime class for coder pods — kernel-level sandbox so a parser/runtime exploit can't reach the host. Strongest single upgrade for T7/T8.
- **YARA ruleset auto-update** + quarantine-and-review workflow.
- **Audit log + alerting** on every scan verdict (quarantine events → SIEM/Slack).

### Phase 3 (mature)
- **Content Disarm & Reconstruction (CDR)** for Office/PDF — strip macros/active content instead of detecting (concept from commercial ICAP; can be approximated with oletools macro-removal + PDF flattening).
- DNS-egress filtering / per-workspace egress identity.

### Explicitly out-of-scope / avoid for now
- **VirusTotal / MalwareBazaar full-file submission** — sends user (possibly proprietary) source to a third party. Privacy violation. Hash-only lookup at most.
- **capa** — great forensics, too heavy/ambiguous for inline gating. Triage only.
- Commercial ICAP (OPSWAT/ReversingLabs) — note the CDR concept, defer the spend.

---

## 4. Layered design (ingress → runtime)

**L0 — Structural gate (synchronous, free).** Extension+magic-byte allowlist (reject ELF/PE
masquerading as data), size cap (exists, 100 MB), decompression-bomb guard for zip/Office
(check uncompressed ratio *before* parsing). Protects ppxai's own parsers too (T8/T9).

**L1 — Content scan (synchronous).** Order cheap→expensive, short-circuit on first MALICIOUS:
`mraptor` (Office) / `pdfid` (PDF) → YARA → ClamAV INSTREAM. Verdict ∈ {clean, suspicious, malicious}.
- malicious → reject (413/422), never write to final path, log.
- suspicious → quarantine dir + flag, optional human review.
- clean → atomic-rename into workspace.

**L2 — Storage isolation.** Per-user PVC; write to `<workspace>/.quarantine` temp first; strip
exec bit; atomic rename on clean. No shared writable mount across users (T6).

**L3 — Agent boundary.** Untrusted-data framing for file content; tool consent ON; secrets
out of scope (T4).

**L4 — Runtime sandbox.** securityContext hardening now; gVisor/Kata in Phase 2 (T7/T8).

**L5 — Network egress.** Deny-by-default egress; allowlist LLM + registry + DNS only. This is
what makes "nothing can send data out" *true* regardless of what slips through L0–L1 (T5).

**L6 — Detect & respond.** Structured scan logs, quarantine alerts, periodic ruleset/sig
freshness check.

---

## 5. ClamAV deployment shape (k8s)

Run clamd as a **shared Deployment + Service**, not a per-pod sidecar, so the ~1–2 GB signature
DB loads once and is amortized across all user pods.

- Image: `clamav/clamav:latest` (bundles clamd + freshclam auto-updater).
- Service: `clamd.security.svc:3310`.
- ppxai-server connects via `clamd` Python lib, `instream(BytesIO)`, reads one verdict.
- INSTREAM scans bytes in RAM — no disk write before verdict. Chunk boundaries are reassembled
  server-side; do **not** implement per-block verdict logic.
- Resource: request ~1.5 GB mem. freshclam on its built-in schedule (or a CronJob).
- **Fail mode decision (see §8):** if clamd unreachable, fail-open-with-log (dev tooling) vs
  fail-closed (if storage is shared).

---

## 6. Prompt-injection specifics (the ppxai-unique risk)

Why it matters: ppxai ingests file content into the LLM and can execute tools (shell, file ops).
A document is a perfect injection carrier — content looks benign to AV, but the *text* tells the
agent to act.

Controls:
1. **Never auto-execute tools on uploaded-content-derived requests.** Keep the existing consent
   gate; in the coder deployment do not set auto-approve for shell/file-delete/network tools.
2. **Data/instruction separation.** File content is injected as clearly-delimited untrusted data;
   the model is system-prompted that file content is never an instruction source.
3. **Least-privilege secrets.** Don't mount cloud/kube creds or `.env` into reach of the agent's
   shell unless required; egress-deny means a leaked secret can't be exfiltrated anyway.
4. **Egress backstop.** Even a fully successful injection that runs `curl evil.com` fails because
   egress is deny-by-default. This is why L5 is non-negotiable.
5. (Phase 2) Optional injection-pattern scan on extracted text (regex/LLM-classifier for
   "ignore previous instructions" style payloads) — low precision, treat as telemetry not a gate.

---

## 7. ppxai integration points (from codebase map)

- **Primary hook — workspace population:** `ppxai/server/routes/files.py` `upload_file()`
  (~L921–1045). Streams 1 MB chunks, **writes directly to resolved workspace path** (~L1015–1033),
  bypassing SessionFileStore. Insert L0+L1 here: buffer/temp-file → scan → atomic-rename on clean.
  Accepts *any* content-type today (100 MB cap) — add the type allowlist here.
- **Secondary hook — chat attachments:** `routes/chat.py` base64 decode (~L128) →
  `engine/file_preprocessing.py:preprocess_file()` → `engine/session_store.py:SessionFileStore.save()`
  (single `write_bytes`, ~L215). One chokepoint for this path.
- **Reuse existing pattern:** `engine/image_validation.py:sniff_media_type()` already does
  magic-byte sniffing — but only for images (PNG/JPEG/WEBP/GIF). Extend the *philosophy* (sniff
  wins over declared type) to all uploads.
- **Config style:** no `max_file_size`/`allowed_types` config today (hardcoded constants).
  Add `uploads.scan.*` / `uploads.allowed_types` knobs matching the v1.18.7 `file_tree.ignore_dirs`
  promotion pattern (constant → user-overridable config).
- **Decompression-bomb guard** belongs *before* both ppxai's parsers and oletools.

---

## 8. Open decisions for the team

1. **Fail-open vs fail-closed** when clamd/scanner is unavailable. (Recommend fail-open-with-log
   for isolated dev pods; fail-closed if any storage is shared.)
2. **Block vs quarantine** on `suspicious` verdicts. (Recommend quarantine+flag, block only on
   `malicious`.)
3. **Per-user storage isolation guarantee** — is every workspace a separate PVC with nothing
   writable shared? This determines how much weight scanning must carry.
4. **Egress policy ownership** — who owns the NetworkPolicy allowlist (LLM endpoints change).
5. **Sandbox runtime** — adopt gVisor/Kata for coder pods in Phase 2? (Strongest T7/T8 upgrade.)
6. **Secret exposure** — audit what creds are reachable from the agent's shell in a coder pod.
7. **Synchronous vs async scan** for large files (UX vs safety on the 100 MB ceiling).

---

## 9. Phase checklist

**Phase 1 (must-have):**
- [ ] L0 structural gate (magic-byte + extension allowlist + size + decompression-bomb) at `/files/upload`
- [ ] oletools `mraptor` on Office types
- [ ] pdfid/pikepdf on PDFs
- [ ] clamd Deployment+Service + INSTREAM client, scan-before-rename
- [ ] Per-user PVC confirmed; quarantine staging dir; strip exec bit
- [ ] NetworkPolicy egress deny-by-default + minimal allowlist
- [ ] Pod securityContext hardening (non-root, no-priv-esc, drop caps, seccomp RuntimeDefault)
- [ ] Tool-consent ON in coder deployment; secrets least-privilege
- [ ] Structured scan/quarantine logging

**Phase 2:** YARA-X + ruleset auto-update; gVisor/Kata runtime; untrusted-data framing for file
content in model context; quarantine review workflow + alerting.

**Phase 3:** CDR for Office/PDF; DNS-egress filtering; injection-pattern telemetry.
