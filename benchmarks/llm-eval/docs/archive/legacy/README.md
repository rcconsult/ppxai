# Legacy Benchmarks (Pre-v1.15)

This directory contains archived benchmark results from early experiments before the unified `llm-eval` suite was created.

## Files

### Tool Routing Benchmarks
- `tool-routing-*.json` (13 files)
- **Purpose:** Test small models (0.5B-4B params) for tool selection accuracy
- **Format:** JSON with `correct_tool`, `wrong_tool`, `false_positive` counts
- **Status:** Superseded by `llm-eval` tool_calling category
- **Date:** Pre-v1.15 (2025)

### Description Comparison Tests
- `description-comparison-*.json` (2 files)
- **Purpose:** Compare tool description quality impact on routing
- **Status:** Experiment completed
- **Date:** Pre-v1.15 (2025)

### Latency Log
- `latency-log.json`
- **Purpose:** Track TTFT (time to first token) and throughput metrics
- **Format:** Timestamped entries with provider/model/performance data
- **Status:** Active (still in use)
- **Note:** Should remain accessible for historical performance tracking

## Current Benchmark System

The active benchmark system is now in `benchmarks/llm-eval/`:
- **Location:** `benchmarks/llm-eval/`
- **Suite:** 28 tests across 7 categories
- **Results:** Stored in `benchmarks/llm-eval/results/`
- **Documentation:** See `benchmarks/BENCHMARKS.md`

These legacy files are kept for historical reference but are no longer actively maintained.

---

**Archived:** 2026-02-14
**Reason:** Consolidation into unified llm-eval benchmark suite
