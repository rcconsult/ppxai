# Qwen3.5-27B-FP8 and Qwen3.6-27B-FP8 empirically accept image_url content

**Hazard:** `ppxai/engine/model_profiles.py` has no entry for either
`Qwen/Qwen3.5-27B-FP8` or `Qwen/Qwen3.6-27B-FP8`. Both fall through to the
default `supports_vision=False`. That makes the chat-attach pipeline send a
text placeholder for image attachments, and the downstream model (which CAN
in fact see images via vLLM) is left without input and tends to hallucinate
a description that looks confident but is fabricated.

**Verifies in code:**

```bash
# In ppxai repo:
grep -E "Qwen.*3\.[56]-27B|Qwen3\.[56]-27B" ppxai/engine/model_profiles.py
# Expected output as of this commit: NO MATCH
# When fixed: a glob like "Qwen/Qwen3.[56]-27B-FP8*" with supports_vision=True
```

```python
# Confirms current (wrong) ppxai detection:
from ppxai.engine.model_profiles import supports_vision
assert supports_vision("Qwen/Qwen3.5-27B-FP8") is False  # ← bug
assert supports_vision("Qwen/Qwen3.6-27B-FP8") is False  # ← bug
```

**Why it matters:** the user's first reaction to a wrong description is "ppxai
lied about VL support." The chat warning DOES say "sent as a text placeholder"
but the model's confident hallucination on top of that is the failure mode
that gets reported. The fix is a one-glob `ModelProfile` entry in
`model_profiles.py` — backed by the empirical evidence below.

## Empirical evidence (cross-repo)

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
`~/.claude/projects/-home-itadmin-ai-git-trad-ai-chat/memory/project_vllm_vl_capabilities_test.md`.

The architecture-comparison doc at
`trad-ai-chat/doc/research/qwen35-vs-qwen36-27b-comparison.md` (2026-04-30)
states Qwen3.6-27B-FP8 has an **explicit vision encoder** in the
architecture ("Text + image + video") and recommends running the same
`test-vl-capabilities.sh` script to confirm 3.6 passes natively. The
HuggingFace card for 3.5 says "Text-only" — that label is empirically
wrong for how the model behaves through vLLM.

## How to reproduce on this cluster

```bash
# Pull the API key the same way the sister script does:
export API_KEY=$(/snap/kubectl/current/kubectl get secret vllm-qwen35-api-key \
    -n vllm -o jsonpath='{.data.api-key}' | base64 -d)

# Then point at whichever endpoint you want to probe. For coder.internal:
cd /home/itadmin/ai/git/trad-ai-chat
./scripts/test-vl-capabilities.sh \
    http://vllm-qwen35-27b-fp8-worker.vllm.svc.cluster.local/v1 \
    Qwen/Qwen3.5-27B-FP8

# Exit code 0 = required tests pass. Exit code 1 = one or more required failed.
# Test 3 (chart comprehension) is OPTIONAL — don't fail the build on those.
```

The script needs `curl`, `python3`, and Pillow (auto-detected from
`<repo>/.venv` per the script). No external network. No
sudo. Fixtures generated inline.

## Open: rerun 3.6 against current cluster

The 2026-04-23 baseline is on 3.5. The qwen36-27b-fp8-mig deployment is
newer; nobody has run `test-vl-capabilities.sh` against it yet. The
empirically-derived `supports_vision=True` entry SHOULD be added to
ppxai for 3.6 anyway based on the architecture claim, but rerunning the
script before adding the profile entry is the conservative path.

## Related

- Debt: [Item 24 in docs/debt-inventory.md](../debt-inventory.md) — the
  ppxai-side fix path. Item 24 also covers the secondary
  `auto_caption` VL-sidecar fallback bug that's worth a separate
  diagnose pass.
- [Two-tier memory rule](README.md) — this lesson belongs here in
  `docs/lessons/` (cross-host, grep-verifiable) rather than per-host
  memory because the evidence trail spans two repos.
