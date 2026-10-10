# Decision models and model dispatch — reference notes

**Date:** 2026-10-10
**Status:** Reference (session research; nothing built, no ADR yet)
**Related:** [../decisions/0012-wire-protocol-as-per-model-capability.md](../decisions/0012-wire-protocol-as-per-model-capability.md),
[../decisions/0011-command-taxonomy-streamline.md](../decisions/0011-command-taxonomy-streamline.md)

Prompted by Microsoft's Decision-1 announcement and the question: could ppxai
use a decision model if one session had several model connections and a
routing or dispatch engine?

## Source basis

- Microsoft announcement (2026-10-09):
  <https://commandline.microsoft.com/microsoft-decision-1-model-foundry/>
- OpenRouter public catalog, `GET https://openrouter.ai/api/v1/models`,
  queried 2026-10-10 (458 models).

The catalog moves fast, so model ids and prices below are as of that query.
The durable part is the split between hosted routers and scorers, and what
each one costs ppxai's model-facts layer.

**Nothing here was live-tested.** No candidate was called.

## Microsoft-Decision-1

- A decision-scoring model, not a chat model. It is post-trained from
  Qwen3.5-9B; Microsoft says later versions will be rebased on other models.
- Given a fixed set of options, it returns a calibrated probability for
  each one. It handles yes/no, multiple choice, ratings, and rubric grading
  of AI responses and agent actions.
- Stated use cases: routing (pick a model by quality, cost and latency),
  classification, prioritisation, verification, and workflow control. Model
  routing is a suggested use, not a built-in router.
- Price: $0.042 per million input tokens; output tokens are free.
- Vendor-reported results only, with no independent check:
  - top accuracy across 36 benchmarks (about 150,000 questions held out of
    training);
  - about 35x faster than GPT-6 Sol at P50, and 2.5x faster than the
    runner-up, H2O-Lightning-4B v1.1;
  - decisions change on 1.3% of perturbed inputs, and never when options
    are reordered or paraphrased.
- **Not usable yet:**
  - The announcement gives no request or response schema, context length,
    or open-weights statement, and doesn't say whether the API is
    OpenAI-compatible.
  - It says the model is on OpenRouter, but the public catalog did not list
    it on 2026-10-10.
  - H2O-Lightning-4B is not on OpenRouter either.

## What ppxai has today

- One chat model per session. `/model` switches it by hand, and the history
  carries over.
- Secondary models only for fixed jobs:
  - the vision-language sidecar (`vision_model` in the config,
    `engine/multimodal_ops.py`, `engine/file_preprocessing.py`);
  - `/task` and `/run`, where each run names its model.
- `/cost` counts every model tier ([ADR 0008](../decisions/0008-cross-tier-cost-and-resource-accounting.md)).
- **No component selects a model automatically.** Grepping `ppxai/engine/`
  for router or dispatch code finds only wire-protocol and file-type
  routing.

## Two kinds of decision model

### 1. Hosted routers: they choose the model and run it

| Model id | How it picks |
|---|---|
| `openrouter/auto`, `openrouter/auto-beta` | By what OpenRouter users collectively spend on similar prompts |
| `openrouter/pareto-code` | From a ranked shortlist of coding models, with a `min_coding_score` setting |
| `typesafe/jev-router` | Model and reasoning effort per request, for quality, speed and cost |

- **Upside:** they work today with no code, as model ids under the
  existing `openrouter` provider.
- **Facts cost:**
  - The model behind the id changes per request, so ADR 0012's per-model
    facts can't be stated: tool mode, parallel tool calls and restricted
    sampling parameters.
  - The id resolves to the unmeasured floor: prompt-based tools, serial.
  - Restricted parameters can't be known in advance. The 2026-10-08
    probe showed Claude 5.5 answering 404 to `temperature` or `top_p`
    under `require_parameters`.
- **Other costs:**
  - Cost per request is unpredictable.
  - The choice can't be inspected beforehand, only afterwards from the
    response's `model` field.
  - Delegating the decision means ppxai doesn't make it.

### 2. Scorers: ppxai decides, the model only scores

Decision-1 is this kind. A purpose-built model isn't required: any model
that returns token log-probabilities can score a fixed-choice prompt by
reading the probability of each option label. Candidates as of
2026-10-10:

- **`nvidia/nemotron-3.5-lightning`:**
  - $0.07 per million input tokens;
  - open weights (30B MoE, 3B active), so it can also run locally;
  - returns log-probabilities and supports structured outputs.

  It's the closest available stand-in for Decision-1.
- **Other cheap models with log-probabilities:** 64 under $0.20 per million
  input tokens on OpenRouter, for example `qwen/qwen3.8-flash`,
  `z-ai/glm-5.3-flash` and `ibm-granite/granite-4.2-8b`.
- **A small local model on vLLM,** a provider ppxai already supports. vLLM
  returns log-probabilities, so this option is private, free per call and
  low latency. It's the strongest choice if decisions shouldn't leave the
  host.
- **Classification only:** `openai/gpt-oss-safeguard-20b` (open weights)
  and `meta-llama/llama-guard-4-12b`.

**Caveat:** log-probabilities from a general chat model rank options
reasonably well but aren't calibrated the way Decision-1 claims to be.
Treat them as rankings, not as "right nine times in ten".

## Where a scorer fits in ppxai, best first

1. **Choosing a model for each `/task` or `/run`.** The options are the
   configured models, and the scorer reads the task text. Runs are
   independent, so there's no shared history to corrupt. This is the
   lowest-risk first use.
2. **ppxai-sre's outlook-monitor classifier.** Fixed-category mail
   classification is exactly what these models are built for. It lives in
   ppxai-sre, on the planned `POST /v1/oneshot` path, not in this repo.
3. **Rubric grading in `benchmarks/llm-eval`,** as a cheap, consistent
   judge next to the deterministic checks.
4. **Choosing a model for each chat turn.** This is the hardest:
   - It mixes the three wire protocols (Responses, Chat Completions,
     `generate_content`) and the native vs prompt-based tool modes in one
     transcript.
   - Each switch loses the provider's prompt cache.
   - It's the shape that produced the orphan tool-call bugs fixed in
     v1.19.1.

   Attempt it only after option 1 has proven itself.

**Not a fit:** tool-approval and consent gates. A confidence score is not
a permission check. At most a scorer can add a logged second opinion; the
consent prompt still decides.

## Sketch, if this becomes an ADR

- **One engine-level dispatch interface:** options plus context in, a score
  per option out. Define it as a Protocol in a leaf module, following the
  protocol dependency-inversion pattern.
- **Backends behind that one interface:**
  1. Rule-based, from data ppxai already has: `ModelFacts` (tool mode,
     tier) and pricing. This is the default, with no extra model call.
  2. A log-probability scorer: any OpenAI-compatible model, local or
     OpenRouter.
  3. Decision-1, once its API is published.
- **Hosted routers stay separate.** Using one is a provider and model
  choice, not a dispatch backend. If supported, mark router ids so
  `/doctor` explains why they resolve to the unmeasured floor.
- **Every dispatch decision should be logged** (options, scores, choice)
  and costed under its own `/cost` tier.

## Open next steps (not started)

- Live-test `nvidia/nemotron-3.5-lightning` as a log-probability scorer
  choosing between gpt-6-luna, gpt-5.6-terra and gpt-6-sol on a handful of
  sample tasks, and compare against the rule-based choice.
- Re-check the OpenRouter catalog for `microsoft/...decision...` and look
  for a published Decision-1 API schema.
- Decide whether to draft the ADR.
