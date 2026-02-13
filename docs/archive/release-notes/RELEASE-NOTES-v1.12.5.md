# Release Notes - v1.12.5

**Release Date:** January 3, 2026

## Summary

Native Gemini provider with Google Search Grounding support. Gemini responses now include real-time web search citations, similar to Perplexity's native search capability.

## What's New

### Native Gemini Provider
- **Google Search Grounding** - Gemini responses now include real-time web search with citations
- **Native SDK Integration** - Direct integration with `google-genai` package for enhanced features
- **Streaming Support** - Full async streaming like Perplexity provider
- **Usage Tracking** - Detailed token counts from Gemini API (prompt, completion, total)
- **Graceful Fallback** - Works without `google-genai` installed (uses OpenAI-compatible API)

### Installation

For enhanced Gemini support with Google Search Grounding:
```bash
pip install ppxai[gemini]
# or
uv pip install ppxai[gemini]
```

Without the optional dependency, Gemini continues to work via OpenAI-compatible API (no grounding/citations).

## Technical Details

- New provider: `ppxai/engine/providers/gemini.py`
- Uses `google-genai>=1.0.0` SDK (not deprecated `google-generativeai`)
- Citations appended as "**Sources:**" section in responses
- Provider auto-detection: Native if `google-genai` installed, OpenAI-compat otherwise

## Benchmarks

| Provider | TTFT | Total | Throughput | vs Baseline |
|----------|------|-------|------------|-------------|
| Perplexity (sonar-pro) | 1411ms | 3649ms | 60.3 tok/s | 0.62x TTFT |
| Gemini (native) | 1489ms | 2195ms | 42.6 tok/s | 1.01x (same) |

No performance regression from native Gemini provider.

## Files Changed

- `ppxai/engine/providers/gemini.py` - New native Gemini provider
- `ppxai/engine/providers/__init__.py` - Auto-detect native vs OpenAI-compat
- `pyproject.toml` - Added `[gemini]` optional dependency
- `README.md` - Updated Gemini description
- `ROADMAP.md` - Added v1.12.5 section

## Compatibility

- Python 3.10+
- All existing Gemini workflows continue to work
- TUI and VSCode extension both support native Gemini
- No breaking changes

## Upgrade

```bash
pip install --upgrade ppxai[gemini]
```

Or download from [GitHub Releases](https://github.com/rcconsult/ppxai/releases/tag/v1.12.5).
