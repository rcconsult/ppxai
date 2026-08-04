# Qwen3.5-27B-FP8 and Qwen3.6-27B-FP8 empirically accept image_url content — FIXED 2026-06-08

**TL;DR:** `ppxai/engine/model_profiles.py` had no entry for either
`Qwen/Qwen3.5-27B-FP8` or `Qwen/Qwen3.6-27B-FP8`, so both fell through to
the default `supports_vision=False` even though the models genuinely accept
`image_url` content through vLLM. **Fixed 2026-06-08** — see
`model_profiles.py:481-505` for the glob entry and the resolved evidence
trail below.

**Verify with:**

```bash
# In ppxai repo — the entry exists as a single glob covering both models:
grep -n "Qwen/Qwen3.\[56\]-27B-FP8" ppxai/engine/model_profiles.py
# Expected: model_profiles.py:481:    "Qwen/Qwen3.[56]-27B-FP8*": ModelProfile(
#           ...with supports_vision=True at the entry (~line 505)
```

```python
# Confirms current (fixed) ppxai detection — verified by execution:
from ppxai.engine.model_profiles import supports_vision
assert supports_vision("Qwen/Qwen3.5-27B-FP8") is True
assert supports_vision("Qwen/Qwen3.6-27B-FP8") is True
```

## Why this tripped people up

Before the fix, the chat-attach pipeline sent a text placeholder for image
attachments on these models, and the downstream model (which CAN in fact see
images via vLLM) was left without input and tended to hallucinate a
confident-looking but fabricated description. The HuggingFace card for 3.5
says "Text-only" — that label was (and remains) empirically wrong for how
the model behaves through vLLM, which is exactly the trap: the obvious
source of truth (the model card) disagreed with observed behavior, and
`model_profiles.py`'s default (`supports_vision=False`) silently sided with
the card.

The user's first reaction to a wrong description was "ppxai lied about VL
support." The chat warning did say "sent as a text placeholder," but the
model's confident hallucination on top of that was the failure mode that
got reported.

## What's actually true (fix + evidence)

The fix is the one-glob `ModelProfile` entry at
`ppxai/engine/model_profiles.py:481-505` — `"Qwen/Qwen3.[56]-27B-FP8*"`
with `supports_vision=True` — backed by the empirical evidence below.

### Empirical evidence (cross-repo)

The sister `trad-ai-chat` repo has a self-contained 9-test VL probe that
generates 3 fixture images inline via Pillow and POSTs OpenAI-style
`image_url` content blocks against an arbitrary vLLM/OpenAI endpoint.

| | |
|---|---|
| Script | `trad-ai-chat/scripts/test-vl-capabilities.sh` |
| Commit | `916772c` (2026-04-23) |
| Baseline | `https://codeai.internal/qwen35/v1` model `Qwen/Qwen3.5-27B-FP8` |
| Score | **8/9 PASS** |
| One fail | Test 2b — arithmetic-over-OCR'd-data reasoning, NOT a vision failure (OCR was correct per Test 2a) |
| Use as | Gate A for the Qwen3-VL-8B-Instruct decommission (CR-v4.0.0 Part 2 Phase 6) |

Per-test result table is captured in the sister-session memory at
`~/.claude/projects/<trad-ai-chat-slug>/memory/project_vllm_vl_capabilities_test.md`.

The architecture-comparison doc at
`trad-ai-chat/doc/research/qwen35-vs-qwen36-27b-comparison.md` (2026-04-30)
states Qwen3.6-27B-FP8 has an **explicit vision encoder** in the
architecture ("Text + image + video"). The fix comment block in
`model_profiles.py` (immediately above the entry) records a third,
in-cluster confirmation on 2026-06-08: a 256x128 PNG containing
"VL TEST 8472" returned the correct `"8472"` from both endpoints
(`chat_template_kwargs={"enable_thinking": False}`, finish_reason=stop) —
closing the "rerun 3.6 against current cluster" gap this lesson originally
flagged as open.

### How to reproduce on this cluster

```bash
# Pull the API key the same way the sister script does:
export API_KEY=$(/snap/kubectl/current/kubectl get secret vllm-qwen35-api-key \
    -n vllm -o jsonpath='{.data.api-key}' | base64 -d)

# Then point at whichever endpoint you want to probe. For coder.internal:
cd /path/to/trad-ai-chat
./scripts/test-vl-capabilities.sh \
    http://vllm-qwen35-27b-fp8-worker.vllm.svc.cluster.local/v1 \
    Qwen/Qwen3.5-27B-FP8

# Exit code 0 = required tests pass. Exit code 1 = one or more required failed.
# Test 3 (chart comprehension) is OPTIONAL — don't fail the build on those.
```

The script needs `curl`, `python3`, and Pillow (auto-detected from
`<repo>/.venv` per the script). No external network. No
sudo. Fixtures generated inline.

## Related

- Debt: [Item 24 in docs/debt-inventory.md](../debt-inventory.md) — closed;
  full resolution detail (including the secondary `auto_caption` VL-sidecar
  fallback fix) archived in
  [docs/archive/DEBT-INVENTORY-CLOSED.md](../archive/DEBT-INVENTORY-CLOSED.md).
- [Two-tier memory rule](README.md) — this lesson belongs here in
  `docs/lessons/` (cross-host, grep-verifiable) rather than per-host
  memory because the evidence trail spans two repos, even though the bug
  itself is now resolved — the trail is what future re-derivation risk
  needs.
