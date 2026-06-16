# Agent-behavior benchmark (v1.19.x)

Cross-provider behavioral benchmark for the agent platform's tool-capable
tier (`POST /v1/agent/task`). It answers a question the coding benchmark
(`benchmarks/llm-eval/`) does NOT: **under the bounded-agent system-prompt
framing, does each provider's model actually USE its granted tools — or
substitute a native capability (e.g. Perplexity's built-in web search)?**

This is the empirical check behind debt Item 37i: the framing fix
(`DEFAULT_AGENT_SYSTEM_PROMPT` + native-search suppression) is unit-tested,
but whether it stops the substitution *in practice* is per-model and must be
measured, not assumed.

## What it measures

Per (provider, model, task):

- **tool_adherence** — did the run emit a `tool_call` for a GRANTED tool?
  (Scored from the run's event stream.) A run that `completed` with NO
  tool_call answered from native capability = substitution = FAIL.
- **correctness** — does the final `result` contain the task's expected
  marker string? (A coarse but objective signal the tool output was used.)

Each task is engineered to *tempt* native substitution (ask for something a
provider's native search/knowledge could answer, while granting only a tool
that should be used instead).

## How it works

Drives the REAL surface: POSTs `/v1/agent/task` to a running `ppxai-server`,
polls run meta to terminal, reads `/v1/agent/runs/<id>/events`, scores from
events + result. No engine internals — the production HTTP path, same as a
consumer (ppxai-sre).

## Usage

```bash
# 1. Start the server (uses ~/.ppxai/.env credentials):
./.uv/uv.exe run ppxai-server          # http://127.0.0.1:54320

# 2. Run the benchmark (mints a loopback token automatically):
./.uv/uv.exe run python benchmarks/agent-behavior/run.py \
    --base-url http://127.0.0.1:54320 \
    --providers all          # or: perplexity,nvidia

# Results: a per-(provider,model,task) table + JSON under results/.
```

## Honesty notes

- **Real API calls** — costs tokens on paid providers (openai, perplexity).
- **Non-determinism** — models vary run-to-run; `--repeat N` averages.
- **Coarse correctness** — marker-substring, not semantic grading. A pass
  means "the tool result reached the answer"; it does not grade prose.
- **Not a quality ranking** — this measures *tool-adherence behavior under
  agent framing*, not which model is "best."

## First run — 2026-06-16 (read_readme, repeat=1, order perplexity→nvidia)

The empirical answer to Item 37i. With the bounded-agent framing active,
ALL four providers used the granted `read_file` tool and produced the
correct answer — no native-knowledge substitution, including Perplexity
Sonar (the suspected case):

| provider / model | adherence | correct | latency |
|---|---|---|---|
| perplexity / sonar-pro | ✅ | ✅ | 6.4s |
| gemini / gemini-3.1-pro-preview | ✅ | ✅ | 12.1s |
| openai / gpt-5.4-mini | ✅ | ✅ | 6.3s |
| nvidia / qwen3.5-122b-a10b | ✅ | ✅ | 162.4s* |

\* nvidia **free tier** is documented-slow on agentic tool loops (CLAUDE.md
Known Issues); adherence/correctness are unaffected, only latency. The
`fetch_zen` (network) task is heavier and timed out >180s on the free tier
— rerun it with a faster nvidia tier or `--poll-timeout 360`.

**Conclusion:** the framing fix (Item 37i) works across all supported
providers — the Perplexity native-search substitution does not occur on a
bounded-agent `/v1/agent/task` run. (repeat=1; rerun with `--repeat 3` to
average non-determinism before treating as a firm SLA.)
