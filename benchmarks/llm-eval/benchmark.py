#!/usr/bin/env python3
"""
LLM Agentic Coding Assistant Benchmark Suite

Evaluates LLM models on capabilities critical for coding assistants:
- Tool calling reliability
- Code editing accuracy (apply_patch)
- Format compliance and instruction following
- Error recovery and self-correction
- Multi-step reasoning

Uses ppxai Engine for consistent tool handling across all providers.
Results are stored per provider/model pair with historical comparison.

Usage:
    python benchmark.py --provider perplexity --model sonar-pro
    python benchmark.py --provider gemini --model gemini-2.5-flash
    python benchmark.py --provider custom --model openai/gpt-oss-120b
    python benchmark.py --list-results
    python benchmark.py --compare perplexity/sonar-pro gemini/gemini-2.5-flash
"""

import argparse
import io
import json
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

# Fix Windows console encoding: force UTF-8 for stdout/stderr to prevent
# 'charmap' codec errors when model responses contain Unicode characters
# (e.g., \u2713 checkmark, \u2011 non-breaking hyphen in model output)
if sys.platform == "win32" and not os.environ.get("PYTHONIOENCODING"):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, io.UnsupportedOperation):
        # Fallback for older Python or non-standard streams
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True
        )

from engine_runner import EngineBenchmarkRunner
from results import ResultsStore, BenchmarkResult


class OutputFormat(Enum):
    TEXT = "text"
    JSON = "json"
    MARKDOWN = "markdown"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LLM Agentic Coding Assistant Benchmark Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run benchmark against any provider (uses ppxai Engine)
  python benchmark.py --provider perplexity --model sonar-pro
  python benchmark.py --provider gemini --model gemini-2.5-flash
  python benchmark.py --provider openai --model gpt-4o

  # Run against custom providers (vLLM, Ollama, etc.)
  python benchmark.py --provider custom --model openai/gpt-oss-120b

  # Run specific test categories
  python benchmark.py --provider openai --model gpt-4o --categories tool_calling,code_editing

  # List all historical results
  python benchmark.py --list-results

  # Compare two provider/model pairs
  python benchmark.py --compare openai/gpt-4o custom/openai/gpt-oss-120b

  # Show ranking across all tested models
  python benchmark.py --ranking
        """
    )

    # Run mode
    run_group = parser.add_argument_group("Run Benchmark")
    run_group.add_argument("--provider", type=str, help="Provider name (e.g., perplexity, gemini, openai, custom)")
    run_group.add_argument("--model", type=str, help="Model name/ID")
    run_group.add_argument("--categories", type=str, help="Comma-separated test categories to run")
    run_group.add_argument("--timeout", type=int, default=120, help="Timeout per test in seconds (default: 120)")
    run_group.add_argument("--retries", type=int, default=1, help="Number of retries per test (default: 1)")
    run_group.add_argument(
        "--tool-calling-method", type=str,
        choices=["native", "prompt_based", "auto"],
        default="auto",
        help="Force tool calling method: native (API function calling), "
             "prompt_based (inject tools in prompt), auto (detect from provider caps)"
    )
    run_group.add_argument(
        "--agents-md", type=str,
        choices=["with", "without", "both"],
        default="with",
        help="AGENTS.md mode: 'with' (default, load bootstrap context), "
             "'without' (skip AGENTS.md), 'both' (run twice, report delta)"
    )

    # Analysis mode
    analysis_group = parser.add_argument_group("Analysis")
    analysis_group.add_argument("--list-results", action="store_true", help="List all stored results")
    analysis_group.add_argument("--compare", nargs=2, metavar=("PAIR1", "PAIR2"), help="Compare two provider/model pairs")
    analysis_group.add_argument("--ranking", action="store_true", help="Show ranking across all models")
    analysis_group.add_argument("--history", type=str, metavar="PAIR", help="Show history for a provider/model pair")

    # Output options
    output_group = parser.add_argument_group("Output")
    output_group.add_argument("--format", type=str, choices=["text", "json", "markdown"], default="text", help="Output format")
    output_group.add_argument("--output", type=str, help="Output file (default: stdout)")
    output_group.add_argument("--verbose", "-v", action="store_true", help="Verbose output (show error summaries)")
    output_group.add_argument("--debug", "-d", action="store_true", help="Debug mode (save detailed logs to debug/)")
    output_group.add_argument("--results-dir", type=str, help="Results directory (default: ./results)")

    return parser


def run_benchmark(args: argparse.Namespace) -> int:
    """Run benchmark suite against specified provider/model."""
    if not args.provider or not args.model:
        print("Error: --provider and --model are required for running benchmarks", file=sys.stderr)
        return 1

    results_dir = Path(args.results_dir) if args.results_dir else Path(__file__).parent / "results"
    store = ResultsStore(results_dir)

    # Parse categories if specified
    categories = None
    if args.categories:
        categories = [c.strip() for c in args.categories.split(",")]

    agents_md_mode = getattr(args, 'agents_md', 'with')
    runs_to_do = []  # list of (label, skip_agents_md)
    if agents_md_mode == "both":
        runs_to_do = [("WITH AGENTS.md", False), ("WITHOUT AGENTS.md", True)]
    elif agents_md_mode == "without":
        runs_to_do = [("WITHOUT AGENTS.md", True)]
    else:
        runs_to_do = [("WITH AGENTS.md", False)]

    results = []
    for label, skip_agents in runs_to_do:
        runner = EngineBenchmarkRunner(
            provider=args.provider,
            model=args.model,
            timeout=args.timeout,
            retries=args.retries,
            verbose=args.verbose,
            debug=args.debug,
            tool_calling_method=getattr(args, 'tool_calling_method', 'auto'),
            skip_agents_md=skip_agents,
        )

        print(f"\n{'='*60}")
        print(f"LLM Agentic Coding Assistant Benchmark — {label}")
        print(f"{'='*60}")
        print(f"Provider: {args.provider}")
        print(f"Model:    {args.model}")
        print(f"Timeout:  {args.timeout}s per test")
        print(f"{'='*60}\n")

        result = runner.run(categories=categories)
        result.metadata["agents_md_mode"] = "without" if skip_agents else "with"
        results.append(result)

        # Store result
        store.save(result)

        # Display results
        print_result(result, args.format, args.verbose)

    # If "both" mode, show delta comparison
    if agents_md_mode == "both" and len(results) == 2:
        result_with, result_without = results[0], results[1]
        print(f"\n{'='*60}")
        print("AGENTS.md Delta Comparison")
        print(f"{'='*60}")
        delta = result_with.overall_score - result_without.overall_score
        direction = "+" if delta >= 0 else ""
        print(f"  With AGENTS.md:    {result_with.overall_score:.1f}%")
        print(f"  Without AGENTS.md: {result_without.overall_score:.1f}%")
        print(f"  Delta:             {direction}{delta:.1f}%")
        print()
        print("  Per-category delta:")
        all_cats = sorted(set(list(result_with.category_scores.keys()) + list(result_without.category_scores.keys())))
        for cat in all_cats:
            s_with = result_with.category_scores.get(cat, 0)
            s_without = result_without.category_scores.get(cat, 0)
            cat_delta = s_with - s_without
            d = "+" if cat_delta >= 0 else ""
            print(f"    {cat:<30} {d}{cat_delta:.1f}%")

        # Store delta in the "with" result metadata
        result_with.metadata["agents_md_delta"] = {
            "overall": delta,
            "categories": {
                cat: result_with.category_scores.get(cat, 0) - result_without.category_scores.get(cat, 0)
                for cat in all_cats
            },
        }

        # Use the "with" result as the primary result for history/ranking
        result = result_with
    else:
        result = results[0]

    # Show comparison with previous runs
    pair_key = f"{args.provider}/{args.model}"
    history = store.get_history(pair_key)

    if len(history) > 1:
        print(f"\n{'='*60}")
        print("Comparison with Previous Runs")
        print(f"{'='*60}")
        print_history_comparison(result, history)

    # Show ranking
    print(f"\n{'='*60}")
    print("Overall Ranking (All Models)")
    print(f"{'='*60}")
    ranking = store.get_ranking()
    print_ranking(ranking, pair_key)

    return 0


def print_result(result: BenchmarkResult, format: str, verbose: bool):
    """Print benchmark result in specified format."""
    print(f"\nOverall Score: {result.overall_score:.1f}%")
    print(f"Tests Passed:  {result.tests_passed}/{result.tests_total}")
    print(f"Duration:      {result.duration_seconds:.1f}s")
    print()

    # Category breakdown
    print("Category Scores:")
    print("-" * 40)
    for category, score in sorted(result.category_scores.items()):
        bar = "#" * int(score / 5) + "-" * (20 - int(score / 5))
        print(f"  {category:20} [{bar}] {score:5.1f}%")

    if verbose:
        print("\nDetailed Results:")
        print("-" * 40)
        for test in result.test_results:
            status = "PASS" if test["passed"] else "FAIL"
            print(f"  {status:4} [{test['category']}] {test['name']}")
            if not test["passed"] and test.get("error"):
                print(f"        Error: {test['error'][:80]}")


def print_history_comparison(current: BenchmarkResult, history: list[BenchmarkResult]):
    """Print comparison with previous runs."""
    if len(history) < 2:
        return

    previous = history[-2]  # Second to last (last is current)

    delta = current.overall_score - previous.overall_score
    direction = "^" if delta > 0 else "v" if delta < 0 else "="

    print(f"\nCurrent:  {current.overall_score:.1f}%")
    print(f"Previous: {previous.overall_score:.1f}%")
    print(f"Change:   {direction} {abs(delta):.1f}%")

    # Category changes
    print("\nCategory Changes:")
    for category in current.category_scores:
        curr = current.category_scores.get(category, 0)
        prev = previous.category_scores.get(category, 0)
        delta = curr - prev
        if abs(delta) > 0.1:
            direction = "^" if delta > 0 else "v"
            print(f"  {category:20} {direction} {abs(delta):.1f}%")


def print_ranking(ranking: list[tuple[str, float, int]], current_pair: Optional[str] = None):
    """Print ranking table."""
    if not ranking:
        print("  No results stored yet.")
        return

    print(f"\n{'Rank':<6} {'Provider/Model':<40} {'Score':>8} {'Runs':>6}")
    print("-" * 62)

    for i, (pair, score, runs) in enumerate(ranking, 1):
        marker = " <- current" if pair == current_pair else ""
        print(f"{i:<6} {pair:<40} {score:>7.1f}% {runs:>6}{marker}")


def list_results(args: argparse.Namespace) -> int:
    """List all stored results."""
    results_dir = Path(args.results_dir) if args.results_dir else Path(__file__).parent / "results"
    store = ResultsStore(results_dir)

    pairs = store.list_pairs()
    if not pairs:
        print("No benchmark results stored yet.")
        return 0

    print(f"\n{'Provider/Model':<40} {'Latest Score':>12} {'Runs':>6} {'Last Run':<20}")
    print("-" * 80)

    for pair in pairs:
        history = store.get_history(pair)
        if history:
            latest = history[-1]
            print(f"{pair:<40} {latest.overall_score:>11.1f}% {len(history):>6} {latest.timestamp[:19]:<20}")

    return 0


def compare_pairs(args: argparse.Namespace) -> int:
    """Compare two provider/model pairs."""
    results_dir = Path(args.results_dir) if args.results_dir else Path(__file__).parent / "results"
    store = ResultsStore(results_dir)

    pair1, pair2 = args.compare

    history1 = store.get_history(pair1)
    history2 = store.get_history(pair2)

    if not history1:
        print(f"No results found for: {pair1}", file=sys.stderr)
        return 1
    if not history2:
        print(f"No results found for: {pair2}", file=sys.stderr)
        return 1

    r1, r2 = history1[-1], history2[-1]

    print(f"\n{'Category':<25} {pair1[:20]:>20} {pair2[:20]:>20} {'Delta':>10}")
    print("-" * 77)

    all_categories = set(r1.category_scores.keys()) | set(r2.category_scores.keys())
    for category in sorted(all_categories):
        s1 = r1.category_scores.get(category, 0)
        s2 = r2.category_scores.get(category, 0)
        delta = s1 - s2
        direction = "+" if delta > 0 else "" if delta < 0 else " "
        print(f"{category:<25} {s1:>19.1f}% {s2:>19.1f}% {direction}{delta:>9.1f}%")

    print("-" * 77)
    delta = r1.overall_score - r2.overall_score
    direction = "+" if delta > 0 else "" if delta < 0 else " "
    print(f"{'OVERALL':<25} {r1.overall_score:>19.1f}% {r2.overall_score:>19.1f}% {direction}{delta:>9.1f}%")

    return 0


def show_ranking(args: argparse.Namespace) -> int:
    """Show ranking across all models."""
    results_dir = Path(args.results_dir) if args.results_dir else Path(__file__).parent / "results"
    store = ResultsStore(results_dir)

    ranking = store.get_ranking()
    print("\nOverall Ranking (Best Score per Provider/Model)")
    print_ranking(ranking)

    return 0


def show_history(args: argparse.Namespace) -> int:
    """Show history for a provider/model pair."""
    results_dir = Path(args.results_dir) if args.results_dir else Path(__file__).parent / "results"
    store = ResultsStore(results_dir)

    history = store.get_history(args.history)
    if not history:
        print(f"No results found for: {args.history}", file=sys.stderr)
        return 1

    print(f"\nHistory for: {args.history}")
    print(f"\n{'Run':<4} {'Timestamp':<20} {'Score':>8} {'Passed':>8} {'Duration':>10}")
    print("-" * 54)

    for i, r in enumerate(history, 1):
        print(f"{i:<4} {r.timestamp[:19]:<20} {r.overall_score:>7.1f}% {r.tests_passed:>3}/{r.tests_total:<3} {r.duration_seconds:>9.1f}s")

    return 0


def main():
    parser = create_parser()
    args = parser.parse_args()

    # Determine mode
    if args.list_results:
        return list_results(args)
    elif args.compare:
        return compare_pairs(args)
    elif args.ranking:
        return show_ranking(args)
    elif args.history:
        return show_history(args)
    elif args.provider and args.model:
        return run_benchmark(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
