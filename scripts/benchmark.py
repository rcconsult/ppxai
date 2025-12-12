#!/usr/bin/env python3
"""
Latency benchmark script for ppxai.

Measures key performance metrics:
- Time to First Token (TTFT) - streaming latency
- Total response time
- Tokens per second (throughput)

Results are stored in benchmarks/latency-log.json for tracking across releases.

Usage:
    # Run benchmark with default provider (perplexity)
    uv run python scripts/benchmark.py

    # Run with specific provider
    uv run python scripts/benchmark.py --provider openai

    # Run with mock (for CI, no API calls)
    uv run python scripts/benchmark.py --mock

    # Specify number of iterations
    uv run python scripts/benchmark.py --iterations 5
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# Load environment variables
load_dotenv(PROJECT_ROOT / ".env")


# Benchmark prompts (varying complexity)
BENCHMARK_PROMPTS = [
    ("simple", "What is 2+2?"),
    ("medium", "Explain the difference between TCP and UDP in 2-3 sentences."),
    ("complex", "Write a Python function to check if a number is prime, with comments."),
]


def get_version() -> str:
    """Get current version from pyproject.toml."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if pyproject.exists():
        import re
        content = pyproject.read_text()
        match = re.search(r'version\s*=\s*"([^"]+)"', content)
        if match:
            return match.group(1)
    return "unknown"


def get_git_info() -> dict:
    """Get current git commit and branch."""
    import subprocess

    info = {"commit": "unknown", "branch": "unknown"}
    try:
        info["commit"] = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        info["branch"] = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        pass
    return info


async def benchmark_streaming(provider_id: str, model: str, prompt: str) -> dict:
    """
    Benchmark a single streaming request.

    Returns:
        dict with ttft_ms, total_ms, tokens, tokens_per_sec
    """
    from ppxai.engine import EngineClient, EventType

    engine = EngineClient()
    engine.set_provider(provider_id)
    engine.set_model(model)

    start_time = time.perf_counter()
    first_token_time = None
    total_tokens = 0

    async for event in engine.chat(prompt):
        if event.type == EventType.STREAM_CHUNK:
            if first_token_time is None:
                first_token_time = time.perf_counter()
            # Rough token count (words + punctuation)
            total_tokens += len(event.data.split())
        elif event.type == EventType.STREAM_END:
            break
        elif event.type == EventType.ERROR:
            raise Exception(f"API Error: {event.data}")

    end_time = time.perf_counter()

    # Calculate metrics
    ttft_ms = (first_token_time - start_time) * 1000 if first_token_time else None
    total_ms = (end_time - start_time) * 1000
    tokens_per_sec = total_tokens / (total_ms / 1000) if total_ms > 0 else 0

    return {
        "ttft_ms": round(ttft_ms, 2) if ttft_ms else None,
        "total_ms": round(total_ms, 2),
        "tokens": total_tokens,
        "tokens_per_sec": round(tokens_per_sec, 2),
    }


async def run_mock_benchmark() -> dict:
    """Run mock benchmark (for CI without API keys)."""
    import random

    results = []
    for prompt_type, prompt in BENCHMARK_PROMPTS:
        for i in range(3):
            # Simulate realistic latencies
            ttft = random.uniform(150, 300)
            total = random.uniform(500, 2000)
            tokens = random.randint(20, 100)

            results.append({
                "prompt_type": prompt_type,
                "iteration": i + 1,
                "ttft_ms": round(ttft, 2),
                "total_ms": round(total, 2),
                "tokens": tokens,
                "tokens_per_sec": round(tokens / (total / 1000), 2),
            })
            await asyncio.sleep(0.01)  # Small delay to simulate work

    return {
        "provider": "mock",
        "model": "mock-model",
        "results": results,
    }


async def run_benchmark(provider_id: str, iterations: int = 3) -> dict:
    """Run full benchmark suite."""
    from ppxai.config import get_default_model

    model = get_default_model(provider_id)
    results = []

    print(f"\nBenchmarking {provider_id} with model {model}")
    print("=" * 50)

    for prompt_type, prompt in BENCHMARK_PROMPTS:
        print(f"\n{prompt_type.upper()} prompt ({iterations} iterations):")

        for i in range(iterations):
            try:
                result = await benchmark_streaming(provider_id, model, prompt)
                result["prompt_type"] = prompt_type
                result["iteration"] = i + 1
                results.append(result)

                print(f"  [{i+1}] TTFT: {result['ttft_ms']:.0f}ms, "
                      f"Total: {result['total_ms']:.0f}ms, "
                      f"Speed: {result['tokens_per_sec']:.1f} tok/s")

                # Small delay between requests
                await asyncio.sleep(0.5)

            except Exception as e:
                print(f"  [{i+1}] ERROR: {e}")
                results.append({
                    "prompt_type": prompt_type,
                    "iteration": i + 1,
                    "error": str(e),
                })

    return {
        "provider": provider_id,
        "model": model,
        "results": results,
    }


def calculate_summary(results: list) -> dict:
    """Calculate summary statistics from results."""
    valid_results = [r for r in results if "error" not in r]

    if not valid_results:
        return {"error": "No valid results"}

    ttft_values = [r["ttft_ms"] for r in valid_results if r.get("ttft_ms")]
    total_values = [r["total_ms"] for r in valid_results]
    speed_values = [r["tokens_per_sec"] for r in valid_results]

    summary = {
        "total_runs": len(results),
        "successful_runs": len(valid_results),
        "failed_runs": len(results) - len(valid_results),
    }

    if ttft_values:
        summary["ttft_ms"] = {
            "mean": round(mean(ttft_values), 2),
            "min": round(min(ttft_values), 2),
            "max": round(max(ttft_values), 2),
            "stdev": round(stdev(ttft_values), 2) if len(ttft_values) > 1 else 0,
        }

    if total_values:
        summary["total_ms"] = {
            "mean": round(mean(total_values), 2),
            "min": round(min(total_values), 2),
            "max": round(max(total_values), 2),
            "stdev": round(stdev(total_values), 2) if len(total_values) > 1 else 0,
        }

    if speed_values:
        summary["tokens_per_sec"] = {
            "mean": round(mean(speed_values), 2),
            "min": round(min(speed_values), 2),
            "max": round(max(speed_values), 2),
        }

    return summary


def save_results(benchmark_data: dict, summary: dict):
    """Save results to latency log file."""
    log_dir = PROJECT_ROOT / "benchmarks"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "latency-log.json"

    # Load existing log
    if log_file.exists():
        with open(log_file) as f:
            log = json.load(f)
    else:
        log = {"entries": []}

    # Create new entry
    git_info = get_git_info()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "version": get_version(),
        "git_commit": git_info["commit"],
        "git_branch": git_info["branch"],
        "provider": benchmark_data["provider"],
        "model": benchmark_data["model"],
        "summary": summary,
        "detailed_results": benchmark_data["results"],
    }

    # Append entry
    log["entries"].append(entry)

    # Save log
    with open(log_file, "w") as f:
        json.dump(log, f, indent=2)

    print(f"\nResults saved to {log_file}")
    return log_file


def print_summary(summary: dict, provider: str, model: str):
    """Print summary to console."""
    print("\n" + "=" * 50)
    print(f"BENCHMARK SUMMARY - {provider} ({model})")
    print("=" * 50)

    if "error" in summary:
        print(f"Error: {summary['error']}")
        return

    print(f"Runs: {summary['successful_runs']}/{summary['total_runs']} successful")

    if "ttft_ms" in summary:
        ttft = summary["ttft_ms"]
        print(f"\nTime to First Token (TTFT):")
        print(f"  Mean: {ttft['mean']:.0f}ms")
        print(f"  Range: {ttft['min']:.0f}ms - {ttft['max']:.0f}ms")
        if ttft['stdev'] > 0:
            print(f"  StdDev: {ttft['stdev']:.0f}ms")

    if "total_ms" in summary:
        total = summary["total_ms"]
        print(f"\nTotal Response Time:")
        print(f"  Mean: {total['mean']:.0f}ms")
        print(f"  Range: {total['min']:.0f}ms - {total['max']:.0f}ms")
        if total['stdev'] > 0:
            print(f"  StdDev: {total['stdev']:.0f}ms")

    if "tokens_per_sec" in summary:
        speed = summary["tokens_per_sec"]
        print(f"\nThroughput:")
        print(f"  Mean: {speed['mean']:.1f} tokens/sec")
        print(f"  Range: {speed['min']:.1f} - {speed['max']:.1f} tokens/sec")


def compare_with_baseline(summary: dict, log_file: Path) -> bool:
    """Compare current results with baseline and warn if regression."""
    if not log_file.exists():
        print("\nNo baseline to compare (first run)")
        return True

    with open(log_file) as f:
        log = json.load(f)

    # Get previous entry for same provider (if exists)
    entries = log.get("entries", [])
    if len(entries) < 2:
        print("\nNo previous baseline to compare")
        return True

    # Find most recent entry before current one (same provider)
    current_provider = entries[-1].get("provider")
    baseline = None
    for entry in reversed(entries[:-1]):
        if entry.get("provider") == current_provider:
            baseline = entry.get("summary", {})
            baseline_version = entry.get("version", "unknown")
            break

    if not baseline or "ttft_ms" not in baseline:
        print("\nNo comparable baseline found")
        return True

    print(f"\n--- Comparison with baseline (v{baseline_version}) ---")

    regression_detected = False
    threshold = 1.2  # 20% regression threshold

    # Compare TTFT
    if "ttft_ms" in summary and "ttft_ms" in baseline:
        current_ttft = summary["ttft_ms"]["mean"]
        baseline_ttft = baseline["ttft_ms"]["mean"]
        ratio = current_ttft / baseline_ttft if baseline_ttft > 0 else 1

        status = "OK" if ratio < threshold else "REGRESSION"
        if ratio >= threshold:
            regression_detected = True

        print(f"TTFT: {baseline_ttft:.0f}ms -> {current_ttft:.0f}ms "
              f"({ratio:.2f}x) [{status}]")

    # Compare total time
    if "total_ms" in summary and "total_ms" in baseline:
        current_total = summary["total_ms"]["mean"]
        baseline_total = baseline["total_ms"]["mean"]
        ratio = current_total / baseline_total if baseline_total > 0 else 1

        status = "OK" if ratio < threshold else "REGRESSION"
        if ratio >= threshold:
            regression_detected = True

        print(f"Total: {baseline_total:.0f}ms -> {current_total:.0f}ms "
              f"({ratio:.2f}x) [{status}]")

    if regression_detected:
        print("\nWARNING: Performance regression detected!")
        return False

    print("\nPerformance is within acceptable range")
    return True


async def main():
    parser = argparse.ArgumentParser(description="ppxai latency benchmark")
    parser.add_argument(
        "--provider",
        default="perplexity",
        help="Provider to benchmark (default: perplexity)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of iterations per prompt (default: 3)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run mock benchmark (no API calls)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't save results to log file",
    )

    args = parser.parse_args()

    print(f"ppxai Latency Benchmark v{get_version()}")
    print(f"Git: {get_git_info()['commit']} ({get_git_info()['branch']})")

    # Run benchmark
    if args.mock:
        benchmark_data = await run_mock_benchmark()
    else:
        benchmark_data = await run_benchmark(args.provider, args.iterations)

    # Calculate summary
    summary = calculate_summary(benchmark_data["results"])

    # Print summary
    print_summary(summary, benchmark_data["provider"], benchmark_data["model"])

    # Save results
    if not args.no_save:
        log_file = save_results(benchmark_data, summary)

        # Compare with baseline
        compare_with_baseline(summary, log_file)

    # Return exit code based on results
    if summary.get("failed_runs", 0) > summary.get("successful_runs", 0):
        return 1
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
