# Multimodal API Models Reference
*Research date: April 3, 2026 — for ppxai provider integration*

---

## Gemini API — Most Comprehensive Multimodal

Built multimodal from day one. All major models handle text, image, audio, video, and PDF in a unified architecture.

### Multimodal Model Matrix

| Model String | Text | Image In | Audio In | Video In | Image Out | Notes |
|---|---|---|---|---|---|---|
| `gemini-3.1-pro-preview` | ✅ | ✅ | ✅ | ✅ | ❌ | Flagship; 1M context; 77.1% ARC-AGI-2 |
| `gemini-2.5-flash` | ✅ | ✅ | ✅ | ✅ | ❌ | Best price/perf; production-stable |
| `gemini-3.1-flash-lite` | ✅ | ✅ | ❌ | ❌ | ❌ | Cheapest Gemini 3 tier (GA 2026-05; preview alias retires 2026-05-25) |
| `gemini-3.1-flash-image-preview` | ✅ | ✅ | ❌ | ❌ | ✅ | Image gen/edit (Nano Banana 2); 4K output |
| `gemini-3-pro-image-preview` | ✅ | ✅ | ❌ | ❌ | ✅ | Nano Banana Pro; highest quality image gen |
| `gemini-live-*` | ✅ | ❌ | ✅ bidirectional | ✅ | ❌ | Real-time streaming via WebSocket |
| `gemini-embedding-2-preview` | ✅ | ✅ | ✅ | ✅ | ❌ | Multimodal embeddings; unified vector space |

### Gemma 4 (Open Weights — Same API Key)

| Model String | Text | Image In | Audio In | Notes |
|---|---|---|---|---|
| `gemma-4-31b-it` | ✅ | ✅ | ❌ | Dense 31B; 256K context |
| `gemma-4-26b-a4b-it` | ✅ | ✅ | ❌ | MoE 26B; 256K context |
| `gemma-4-e4b-it` | ✅ | ✅ | ✅ | Edge 4B; 128K; native audio |
| `gemma-4-e2b-it` | ✅ | ✅ | ✅ | Edge 2B; 128K; native audio |

### Deprecation Notes
- `gemini-3-pro-preview` — shut down March 9, 2026; use `gemini-3.1-pro-preview`
- `gemini-2.0-flash` / `gemini-2.0-flash-lite` stable — shutting down June 1, 2026
- All Imagen models — shutting down June 24, 2026; migrate to Nano Banana models
- `gemini-2.5-flash-lite-preview-09-2025` — shut down March 31, 2026

### Pricing (Google AI Studio, as of late March 2026)
- Gemini 3.1 Pro Preview: input costs double above 200K tokens
- Gemini 2.5 Flash: best value for production workloads
- Gemini 3.1 Flash-Lite Preview: lowest cost in Gemini 3 family
- Free tier: ~15 RPM / 1,500 RPD for Gemini 2.0 Flash

---

## OpenAI API — Vision Native, Audio Separate

All GPT-5.x models support image+text input natively. Audio requires the separate **Realtime API** (different endpoint/models). No native video input on any current model.

### Multimodal Model Matrix

| Model String | Text | Image In | Audio | Video | Notes |
|---|---|---|---|---|---|
| `gpt-5.4` | ✅ | ✅ | ❌* | ❌ | Flagship; 1M context; computer use; tool search |
| `gpt-5.4-pro` | ✅ | ✅ | ❌* | ❌ | More compute for harder problems |
| `gpt-5.4-mini` | ✅ | ✅ | ❌* | ❌ | High-volume; faster |
| `gpt-5.4-nano` | ✅ | ✅ | ❌* | ❌ | Cheapest; simple tasks |
| `gpt-5.2` | ✅ | ✅ | ❌* | ❌ | Still available; more affordable than 5.4 |
| `gpt-5.3-codex` | ✅ | ✅ | ❌ | ❌ | Agentic coding specialist |

*Audio available via separate Realtime API endpoint (bidirectional streaming, different integration path)

### Key API Notes
- All models available via Chat Completions API and Responses API
- `gpt-5.4` snapshot: `gpt-5.4-2026-03-05`
- `gpt-5.4-mini` snapshot: `gpt-5.4-mini-2026-03-17`
- Reasoning effort parameter: `none`, `low`, `medium`, `high`, `xhigh`
- Context window: 1.05M tokens on gpt-5.4 / gpt-5.4-pro
- Prompts >272K tokens on gpt-5.4: 2x input + 1.5x output pricing

### Deprecation Notes
- `gpt-5.1` and variants — removed from ChatGPT March 11, 2026; still in API but migrate to 5.4
- Assistants API — sunset anticipated in 2026; migrate to Responses API

### Pricing (as of March 2026)
- `gpt-5.4`: $1.75/1M input, $14/1M output (90% discount on cached inputs)
- `gpt-5.4-mini`: lower cost tier for high-volume

---

## Perplexity API — Image Input + Web-Grounded Search

Sonar models support image input alongside their core real-time web search capability. No audio, no video, no image generation. Primary value is search-grounded responses with citations.

### Multimodal Model Matrix

| Model String | Text | Image In | Audio | Video | Web Search | Notes |
|---|---|---|---|---|---|---|
| `sonar` | ✅ | ✅ | ❌ | ❌ | ✅ | Fast; $1/1M tokens |
| `sonar-pro` | ✅ | ✅ | ❌ | ❌ | ✅ | Deep retrieval; 200K context; $3/1M tokens |
| `sonar-reasoning` | ✅ | ❌ | ❌ | ❌ | ✅ | Multi-step reasoning; $1/1M tokens |
| `sonar-deep-research` | ✅ | ❌ | ❌ | ❌ | ✅ | Long-form research; $2/1M input, $8/1M output |

### Image Input Specs (sonar / sonar-pro)
- Formats: PNG, JPEG, WEBP, GIF
- Delivery: base64 data URI or public HTTPS URL
- Size limit: 50MB per image
- Token pricing: `(width × height) / 750` tokens per image, billed at model's input rate
- Use cases: screenshot analysis, diagram interpretation, visual Q&A + web context

### Key API Notes
- OpenAI-compatible format — base URL + model name change only
- Endpoint: `https://api.perplexity.ai/chat/completions`
- Responses include inline citations by default
- `return_images: true` available (Tier-2 users and above) — returns relevant web images in response
- File attachments (PDF, docs) supported on Sonar models

### March 2026 API Additions
- **Agent API** — multi-step agentic workflows
- **Search API** — raw web search index access (200B+ pages)
- **Embeddings API** — `pplx-embed-v1` and `pplx-embed-context-v1` (0.6B and 4B scales, MIT license)
- MCP server available for Claude Code / Cursor / VS Code integration

---

## Provider Comparison Summary

| Capability | Gemini API | OpenAI API | Perplexity API |
|---|---|---|---|
| Image input | ✅ All models | ✅ All GPT-5.x | ✅ sonar / sonar-pro |
| Audio input | ✅ Flash, Live API | ❌ (Realtime API only) | ❌ |
| Video input | ✅ Flash, Live API | ❌ | ❌ |
| Image generation | ✅ Nano Banana models | ❌ | ❌ |
| Real-time streaming | ✅ Gemini Live (WS) | ✅ Realtime API | ❌ |
| Web-grounded answers | ✅ (grounding tool) | ✅ (web search tool) | ✅ Native/core feature |
| Multimodal embeddings | ✅ Embedding 2 | ❌ | ❌ |
| Open weights | ✅ Gemma 4 | ❌ | ❌ |
| OAI-compatible format | ✅ | ✅ | ✅ |

---

## ppxai Integration Notes

- **Gemini**: Full multimodal stack through one API key — image/audio/video input, image generation, real-time streaming, open-weight Gemma 4 models, all same SDK
- **OpenAI**: Image vision integrates cleanly into standard Chat Completions; audio requires separate Realtime API integration path if needed
- **Perplexity**: Image input useful for "search + analyze this screenshot" patterns; Sonar is primarily a search-grounded text model with image support bolted on

*Model strings and pricing should be verified against official docs before production deployment — this landscape changes monthly.*
