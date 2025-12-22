# 400 Error Root Cause Analysis

**Error**: "After the (optional) system message(s), user or tool message(s) should alternate with assistant message(s)."

**When It Occurs**: After tools are enabled and you try to send a follow-up message

---

## The Problem

### Scenario from Terminal Output

```
[Perplexity AI | Sonar Pro | Tools: OFF]
You: review the roadmap items...
Assistant: (response with table)  ← Works fine

[Perplexity AI | Sonar Pro | Tools: OFF]
You: /tools enable
✓ Tools enabled!

[Perplexity AI | Sonar Pro | Tools: ON]
You: use tools to review the current project