# Known Issues

Tracked blockers that affect production behavior or have caused regressions.
Each entry includes root cause, workaround status, and upgrade/resolution criteria.

---

## [KI-001] google-genai SDK ≥1.57.0 — Code Editing Regression

**Status:** Open (unresolved upstream) — SDK pinned to `<1.57.0`
**Detected:** February 8, 2026
**Affected versions:** google-genai 1.57.0 through 1.65.0 (latest as of Feb 27, 2026)
**Upstream issues:** [#1789](https://github.com/googleapis/python-genai/issues/1789), [#1818](https://github.com/googleapis/python-genai/issues/1818)

### What broke

Upgrading from SDK 1.56.0 → 1.62.0 caused a **-12.5% overall benchmark regression** on gemini-2.5-flash, with code editing dropping from **57.1% → 0%** — a complete failure.

| Metric | SDK 1.56.0 | SDK 1.62.0 | Delta |
|--------|-----------|-----------|-------|
| Overall score | 76.6% | 64.1% | **-12.5%** |
| Code editing | 57.1% | 0% | **-57.1%** 🚨 |
| Hallucination resistance | 55.6% | 33.3% | -22.3% |
| Tool calling | 85.7% | 85.7% | no change |

### Root cause

**SDK v1.57.0** (Jan 7, 2026) removed validation restrictions on empty text parts:

> "Remove validation for empty text parts on Chat, this will support keeping the history in chat when the API yields back such a part."

This change lets incomplete responses (empty or whitespace-only text parts) pass through unchecked, causing the model's actual code output to be silently swallowed.

### Workarounds in place

**1. Version pin** — `pyproject.toml` constrains both optional and dev dependencies:
```toml
"google-genai>=1.0.0,<1.57.0"
```

**2. Defensive filter** — `_filter_empty_parts()` in `ppxai/engine/providers/gemini.py`
strips empty text parts from all three response paths (streaming, non-streaming, sync).
This remains active even with the pin as a safety net if the pin is ever relaxed.

### How to verify a fix before upgrading

1. Check upstream issues [#1789](https://github.com/googleapis/python-genai/issues/1789) and [#1818](https://github.com/googleapis/python-genai/issues/1818) are closed.
2. Bump the pin in `pyproject.toml` to the candidate version and run `uv lock`.
3. Run the benchmark suite against gemini-2.5-flash (or gemini-3-flash-preview):
   ```bash
   python benchmarks/llm-eval/run_benchmarks.py --model gemini-2.5-flash --runs 3
   ```
4. Verify code editing score ≥50% and overall score ≥75%.
5. If passing, remove the `<1.57.0` upper bound and update this entry.

### Archive

Full analysis, workaround implementation notes, and rollback log:
- `docs/archive/v1.15.3/GEMINI-SDK-REGRESSION-ANALYSIS.md`
- `docs/archive/v1.15.3/GEMINI-SDK-WORKAROUNDS-APPLIED.md`
- `docs/archive/v1.15.3/GEMINI-SDK-ROLLBACK-STATUS.md`

---

*Add new entries above using the `[KI-NNN]` format.*
