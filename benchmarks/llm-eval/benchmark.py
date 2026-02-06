#!/usr/bin/env python3
"""
LLM Agentic Coding Assistant Benchmark Suite

Evaluates LLM models on capabilities critical for coding assistants:
- Tool calling reliability
- Code editing accuracy (apply_patch)
- Format compliance and instruction following
- Error recovery and self-correction
- Multi-step reasoning

Results are stored per provider/model pair with historical comparison.

Usage:
    python benchmark.py --provider openai --model gpt-4o --base-url https://api.openai.com/v1
    python benchmark.py --provider vllm --model openai/gpt-oss-120b --base-url http://localhost:8000/v1
    python benchmark.py --list-results
    python benchmark.py --compare openai/gpt-4o vllm/openai/gpt-oss-120b
"""

import argparse
import json
import hashlib
import sys
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

from runner import BenchmarkRunner
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
  # Run benchmark against OpenAI (direct API)
  python benchmark.py --provider openai --model gpt-4o

  # Run against local vLLM (direct API)
  python benchmark.py --provider vllm --model openai/gpt-oss-120b --base-url http://localhost:8000/v1

  # Run using ppxai Engine (supports all providers including Perplexity, Gemini)
  python benchmark.py --provider perplexity --model sonar-pro --engine
  python benchmark.py --provider gemini --model gemini-2.5-flash --engine

  # Run specific test categories
  python benchmark.py --provider openai --model gpt-4o --categories tool_calling,code_editing

  # List all historical results
  python benchmark.py --list-results

  # Compare two provider/model pairs
  python benchmark.py --compare openai/gpt-4o vllm/openai/gpt-oss-120b

  # Show ranking across all tested models
  python benchmark.py --ranking
        """
    )

    # Run mode
    run_group = parser.add_argument_group("Run Benchmark")
    run_group.add_argument("--provider", type=str, help="Provider name (e.g., openai, vllm, ollama)")
    run_group.add_argument("--model", type=str, help="Model name/ID")
    run_group.add_argument("--base-url", type=str, help="API base URL (default: provider-specific)")
    run_group.add_argument("--api-key", type=str, help="API key (or set via environment)")
    run_group.add_argument("--categories", type=str, help="Comma-separated test categories to run")
    run_group.add_argument("--timeout", type=int, default=60, help="Timeout per test in seconds (default: 60)")
    run_group.add_argument("--retries", type=int, default=1, help="Number of retries per test (default: 1)")
    run_group.add_argument("--no-ssl-verify", action="store_true", help="Disable SSL certificate verification")
    run_group.add_argument("--ssl-cert-file", type=str, help="Path to custom CA certificate bundle")
    run_group.add_argument("--no-ppxai-config", action="store_true", help="Don't load generation params from ppxai config")
    run_group.add_argument("--engine", action="store_true", help="Use ppxai Engine instead of direct OpenAI API (supports all providers)")

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
    output_group.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
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

    # Choose runner based on --engine flag
    if args.engine:
        # Use ppxai Engine-based runner (supports all providers including native APIs)
        runner = EngineBenchmarkRunner(
            provider=args.provider,
            model=args.model,
            timeout=args.timeout,
            retries=args.retries,
            verbose=args.verbose,
        )
        runner_type = "ppxai Engine"
        base_url = "(via ppxai config)"
        gen_params = "(via ppxai config)"
    else:
        # Use direct OpenAI API runner
        runner = BenchmarkRunner(
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            timeout=args.timeout,
            retries=args.retries,
            verbose=args.verbose,
            ssl_verify=not args.no_ssl_verify,
            ssl_cert_file=args.ssl_cert_file,
            use_ppxai_config=not args.no_ppxai_config,
        )
        runner_type = "OpenAI API"
        base_url = runner.client.base_url
        gen_params = runner.generation_params

    print(f"\n{'='*60}")
    print(f"LLM Agentic Coding Assistant Benchmark")
    print(f"{'='*60}")
    print(f"Runner:   {runner_type}")
    print(f"Provider: {args.provider}")
    print(f"Model:    {args.model}")
    if base_url:
        print(f"Base URL: {base_url}")
    if gen_params:
        print(f"Gen Params: {gen_params}")
    print(f"{'='*60}\n")

    # Run benchmark
    result = runner.run(categories=categories)

    # Store result
    store.save(result)

    # Display results
    print_result(result, args.format, args.verbose)

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
