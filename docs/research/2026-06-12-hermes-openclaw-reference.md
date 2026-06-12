# Hermes Agent / OpenClaw — comparative reference (pointer)

**Date:** 2026-06-12
**Status:** Reference research — NOT a decision.

The full comparative reference lives in the **ppxai-sre** repo, where the
agent-runtime research already lives:

→ [`../../../ppxai-sre/docs/HERMES-OPENCLAW-REFERENCE.md`](../../../ppxai-sre/docs/HERMES-OPENCLAW-REFERENCE.md)

## Why this pointer exists

`NousResearch/hermes-agent` (the evolution of the OpenClaw lineage
ppxai-sre cites) is the current state of the art of the design lineage
ppxai-sre was conceived against. The reference doc records
source-verified architectural options worth considering across **both**
repos — recorded as referential evidence, not an adoption plan, and not
a recommendation to copy MIT-licensed code.

## Relevance to ppxai (this repo) specifically

Most relevance is ppxai-sre-side, but two items touch ppxai:

- **Messaging gateway pattern** (`gateway/platform_registry.py` +
  `delivery.py`) — a registry/ABC reference for any future notification
  or multi-client delivery surface. See §4.4 of the full doc.
- **Skill self-improvement / `agentskills.io`** — a marketplace concept
  that is *forbidden* in ppxai-sre but could be relevant to ppxai the
  product. See §5.

Companion to the existing
[`2026-05-10-ppxai-sre-requirements.md`](2026-05-10-ppxai-sre-requirements.md)
gap analysis.
