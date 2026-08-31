#!/usr/bin/env python3
"""
Benchmark tool-calling accuracy for small models.

Tests whether models can correctly identify when/which tool to call
for various user queries. Based on ppxai's tool schema.

Supports:
1. Native tool calling (via OpenAI API tool_calls)
2. Content parsing (ppxai's fallback parser for JSON in content)
3. Configurable tool descriptions (test different wordings)
4. Multiple test profiles (coding, general, filesystem)

Usage:
    # Basic benchmark
    python benchmark_tool_routing.py --model qwen2.5-coder:0.5b --parse-content

    # Compare models
    python benchmark_tool_routing.py --compare --parse-content

    # Test with enhanced descriptions
    python benchmark_tool_routing.py --model qwen2.5-coder:0.5b --parse-content --descriptions enhanced

    # Run specific test profile
    python benchmark_tool_routing.py --model qwen2.5-coder:0.5b --profile filesystem
"""

import json
import re
import time

from openai import OpenAI

# Tool description variants - allows testing different wordings
TOOL_DESCRIPTIONS = {
    "default": {
        "shell": "Execute a shell command in the current working directory",
        "read_file": "Read the contents of a file",
        "write_file": "Write content to a file, creating it if it doesn't exist",
        "edit_file": "Edit a file by replacing old text with new text",
        "list_directory": "List contents of a directory",
        "search_files": "Search for files matching a pattern in a directory",
    },
    "enhanced": {
        "shell": "Execute shell/terminal commands (git, npm, python, ls, cd, etc.) - use for ANY command-line operation",
        "read_file": "Read and display the contents of a specific file by path",
        "write_file": "Create a new file or overwrite existing file with content",
        "edit_file": "Modify an existing file by finding and replacing specific text",
        "list_directory": "Show ALL files and folders in a directory - use when you want to see directory contents",
        "search_files": "Find files by glob pattern (*.py, test*, *config*) - use when searching for files by NAME pattern",
    },
    "minimal": {
        "shell": "Run command",
        "read_file": "Read file",
        "write_file": "Write file",
        "edit_file": "Edit file",
        "list_directory": "List directory",
        "search_files": "Search files by pattern",
    },
    "explicit": {
        "shell": "SHELL COMMAND: Run terminal commands like 'git status', 'npm install', 'python script.py', 'ls -la'",
        "read_file": "FILE READ: Get contents of a file given its path (e.g., config.json, main.py)",
        "write_file": "FILE WRITE: Save content to a file path",
        "edit_file": "FILE EDIT: Replace old_text with new_text in a file",
        "list_directory": "DIRECTORY LIST: Show what's inside a folder (not for searching)",
        "search_files": "FILE SEARCH: Find files matching a glob pattern like *.py or test* (for finding files by name)",
    },
}


def get_tool_definitions(description_set: str = "default"):
    """Get tool definitions with specified descriptions."""
    descs = TOOL_DESCRIPTIONS.get(description_set, TOOL_DESCRIPTIONS["default"])

    return [
        {
            "type": "function",
            "function": {
                "name": "shell",
                "description": descs["shell"],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute"}
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": descs["read_file"],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to read"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": descs["write_file"],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to write"},
                        "content": {"type": "string", "description": "Content to write to the file"}
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": descs["edit_file"],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to edit"},
                        "old_text": {"type": "string", "description": "Text to replace"},
                        "new_text": {"type": "string", "description": "Replacement text"}
                    },
                    "required": ["path", "old_text", "new_text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": descs["list_directory"],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path to list"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_files",
                "description": descs["search_files"],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern to match (e.g., *.py, test*, *config*)"},
                        "path": {"type": "string", "description": "Directory to search in"}
                    },
                    "required": ["pattern"]
                }
            }
        }
    ]


# Test profiles for different use cases
TEST_PROFILES = {
    "all": None,  # Use all test cases
    "shell": [
        ("run git status", "shell", "git status"),
        ("execute npm install", "shell", "npm install"),
        ("list running processes", "shell", "ps"),
        ("check disk usage", "shell", "df"),
        ("show current directory", "shell", "pwd"),
        ("run python script.py", "shell", "python"),
        ("compile the project", "shell", None),
        ("start the server", "shell", None),
    ],
    "filesystem": [
        ("show me the contents of config.json", "read_file", "config.json"),
        ("what's in README.md?", "read_file", "README.md"),
        ("read the package.json file", "read_file", "package.json"),
        ("cat main.py", "read_file", "main.py"),
        ("what files are in src/", "list_directory", "src"),
        ("show me the contents of the tests folder", "list_directory", "tests"),
        ("list all files in the current directory", "list_directory", None),
        ("find all python files", "search_files", "*.py"),
        ("search for files named test*", "search_files", "test*"),
        ("find config files in the project", "search_files", "config"),
    ],
    "editing": [
        ("create a new file called test.txt with hello world", "write_file", "test.txt"),
        ("write 'print(1)' to script.py", "write_file", "script.py"),
        ("save this code to output.js", "write_file", "output.js"),
        ("replace 'old' with 'new' in file.txt", "edit_file", "file.txt"),
        ("change the port from 3000 to 8080 in config.json", "edit_file", "config.json"),
        ("fix the typo in README.md", "edit_file", "README.md"),
    ],
    "conversational": [
        ("what is python?", None, None),
        ("explain async/await", None, None),
        ("how do I use git?", None, None),
        ("what's the best practice for error handling?", None, None),
        ("tell me about REST APIs", None, None),
    ],
}

# Full test suite
TEST_CASES = [
    # Shell commands
    ("run git status", "shell", "git status"),
    ("execute npm install", "shell", "npm install"),
    ("list running processes", "shell", "ps"),
    ("check disk usage", "shell", "df"),
    ("show current directory", "shell", "pwd"),

    # Read file
    ("show me the contents of config.json", "read_file", "config.json"),
    ("what's in README.md?", "read_file", "README.md"),
    ("read the package.json file", "read_file", "package.json"),
    ("cat main.py", "read_file", "main.py"),

    # Write file
    ("create a new file called test.txt with hello world", "write_file", "test.txt"),
    ("write 'print(1)' to script.py", "write_file", "script.py"),
    ("save this code to output.js", "write_file", "output.js"),

    # Edit file
    ("replace 'old' with 'new' in file.txt", "edit_file", "file.txt"),
    ("change the port from 3000 to 8080 in config.json", "edit_file", "config.json"),
    ("fix the typo in README.md", "edit_file", "README.md"),

    # List directory
    ("what files are in src/", "list_directory", "src"),
    ("show me the contents of the tests folder", "list_directory", "tests"),
    ("list all files in the current directory", "list_directory", None),

    # Search files
    ("find all python files", "search_files", "*.py"),
    ("search for files named test*", "search_files", "test*"),
    ("find config files in the project", "search_files", "config"),

    # No tool needed (conversational)
    ("what is python?", None, None),
    ("explain async/await", None, None),
    ("how do I use git?", None, None),
]

# Tool name mapping (model output -> expected)
TOOL_NAME_MAP = {
    "shell": "shell",
    "execute_shell_command": "shell",
    "read_file": "read_file",
    "write_file": "write_file",
    "edit_file": "edit_file",
    "list_directory": "list_directory",
    "search_files": "search_files",
}


def parse_tool_from_content(content: str) -> tuple[str | None, dict | None]:
    """Parse tool call from model content (ppxai-style parsing).

    Returns (tool_name, arguments) or (None, None) if no tool found.
    """
    if not content:
        return None, None

    # Try to extract JSON from code blocks
    code_block_pattern = r'```(?:json)?\s*([\s\S]*?)```'
    matches = re.findall(code_block_pattern, content)

    for match in matches:
        match_stripped = match.strip()
        if match_stripped.startswith('{') and match_stripped.endswith('}'):
            try:
                data = json.loads(match_stripped)
                tool_name = data.get("tool") or data.get("name")
                if tool_name:
                    # Normalize tool name
                    tool_name = TOOL_NAME_MAP.get(tool_name, tool_name)
                    args = data.get("arguments", {})
                    return tool_name, args
            except json.JSONDecodeError:
                pass

    # Try entire content as JSON
    content_stripped = content.strip()
    if content_stripped.startswith('{') and content_stripped.endswith('}'):
        try:
            data = json.loads(content_stripped)
            tool_name = data.get("tool") or data.get("name")
            if tool_name:
                tool_name = TOOL_NAME_MAP.get(tool_name, tool_name)
                args = data.get("arguments", {})
                return tool_name, args
        except json.JSONDecodeError:
            pass

    return None, None


def benchmark_model(
    base_url: str,
    model: str,
    api_key: str = "ollama",
    parse_content: bool = False,
    description_set: str = "default",
    profile: str = "all",
    verbose: bool = True
):
    """Run tool-calling benchmark on a model.

    Args:
        base_url: API base URL
        model: Model name
        api_key: API key
        parse_content: If True, also parse tool calls from content (ppxai-style fallback)
        description_set: Which tool descriptions to use (default, enhanced, minimal, explicit)
        profile: Test profile to run (all, shell, filesystem, editing, conversational)
        verbose: Print detailed results
    """
    client = OpenAI(base_url=base_url, api_key=api_key)
    tools = get_tool_definitions(description_set)

    # Select test cases based on profile
    if profile == "all" or profile not in TEST_PROFILES:
        test_cases = TEST_CASES
    else:
        test_cases = TEST_PROFILES[profile]

    results = {
        "model": model,
        "mode": "native+content_parse" if parse_content else "native_only",
        "description_set": description_set,
        "profile": profile,
        "total": len(test_cases),
        "correct_tool": 0,
        "correct_args": 0,
        "false_positive": 0,  # Called tool when shouldn't
        "false_negative": 0,  # Didn't call tool when should
        "wrong_tool": 0,
        "latencies_ms": [],
        "per_tool_accuracy": {},
        "details": []
    }

    # Track per-tool stats
    tool_stats = {}

    if verbose:
        mode_str = "Native + Content Parsing" if parse_content else "Native Only"
        print(f"\n{'='*60}")
        print(f"Benchmarking: {model}")
        print(f"Mode: {mode_str}")
        print(f"Descriptions: {description_set}")
        print(f"Profile: {profile}")
        print(f"Base URL: {base_url}")
        print(f"Test cases: {len(test_cases)}")
        print(f"{'='*60}\n")

    for i, (query, expected_tool, expected_in_args) in enumerate(test_cases):
        start = time.perf_counter()

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a coding assistant with access to tools. Use tools when appropriate."},
                    {"role": "user", "content": query}
                ],
                tools=tools,
                tool_choice="auto",
                max_tokens=256,
                temperature=0.1
            )

            latency_ms = (time.perf_counter() - start) * 1000
            results["latencies_ms"].append(latency_ms)

            # Check response
            message = response.choices[0].message
            tool_calls = message.tool_calls

            actual_tool = None
            actual_args = None

            # First try native tool calls
            if tool_calls and len(tool_calls) > 0:
                actual_tool = tool_calls[0].function.name
                try:
                    actual_args = json.loads(tool_calls[0].function.arguments)
                except:
                    actual_args = tool_calls[0].function.arguments

            # If no native tool call and parse_content enabled, try parsing from content
            if actual_tool is None and parse_content and message.content:
                parsed_tool, parsed_args = parse_tool_from_content(message.content)
                if parsed_tool:
                    actual_tool = parsed_tool
                    actual_args = parsed_args

            # Evaluate
            tool_correct = actual_tool == expected_tool
            args_match = False

            if expected_in_args and actual_args:
                args_str = json.dumps(actual_args).lower() if isinstance(actual_args, dict) else str(actual_args).lower()
                args_match = expected_in_args.lower() in args_str
            elif expected_in_args is None and actual_args is None:
                args_match = True
            elif expected_in_args is None and tool_correct:
                # Tool correct but no specific args expected
                args_match = True

            # Update per-tool stats
            if expected_tool:
                if expected_tool not in tool_stats:
                    tool_stats[expected_tool] = {"correct": 0, "total": 0}
                tool_stats[expected_tool]["total"] += 1
                if tool_correct:
                    tool_stats[expected_tool]["correct"] += 1

            if tool_correct:
                results["correct_tool"] += 1
                if args_match:
                    results["correct_args"] += 1
            elif expected_tool is None and actual_tool is not None:
                results["false_positive"] += 1
            elif expected_tool is not None and actual_tool is None:
                results["false_negative"] += 1
            else:
                results["wrong_tool"] += 1

            if verbose:
                status = "✓" if tool_correct and args_match else "✗"
                print(f"{status} [{i+1:2d}/{len(test_cases)}] {query[:40]:<40}")
                print(f"    Expected: {expected_tool or 'no tool':<15} Got: {actual_tool or 'no tool':<15} ({latency_ms:.0f}ms)")

                if not tool_correct or not args_match:
                    if actual_args:
                        print(f"    Args: {json.dumps(actual_args)[:60]}")
                    if message.content:
                        print(f"    Content: {message.content[:60]}...")

            results["details"].append({
                "query": query,
                "expected_tool": expected_tool,
                "actual_tool": actual_tool,
                "expected_args_contains": expected_in_args,
                "actual_args": actual_args,
                "tool_correct": tool_correct,
                "args_match": args_match,
                "latency_ms": latency_ms
            })

        except Exception as e:
            if verbose:
                print(f"✗ [{i+1:2d}/{len(test_cases)}] {query[:40]:<40}")
                print(f"    ERROR: {str(e)[:60]}")
            results["details"].append({
                "query": query,
                "error": str(e)
            })

    # Calculate per-tool accuracy
    for tool_name, stats in tool_stats.items():
        if stats["total"] > 0:
            results["per_tool_accuracy"][tool_name] = {
                "correct": stats["correct"],
                "total": stats["total"],
                "accuracy": round(100 * stats["correct"] / stats["total"], 1)
            }

    # Summary
    avg_latency = sum(results["latencies_ms"]) / len(results["latencies_ms"]) if results["latencies_ms"] else 0

    if verbose:
        print(f"\n{'='*60}")
        print(f"RESULTS: {model} ({description_set} descriptions)")
        print(f"{'='*60}")
        print(f"Tool Selection Accuracy: {results['correct_tool']}/{results['total']} ({100*results['correct_tool']/results['total']:.1f}%)")
        print(f"Argument Accuracy:       {results['correct_args']}/{results['total']} ({100*results['correct_args']/results['total']:.1f}%)")
        print(f"False Positives:         {results['false_positive']} (called tool when shouldn't)")
        print(f"False Negatives:         {results['false_negative']} (missed tool call)")
        print(f"Wrong Tool:              {results['wrong_tool']}")
        print(f"Average Latency:         {avg_latency:.0f}ms")

        if results["per_tool_accuracy"]:
            print("\nPer-Tool Accuracy:")
            for tool_name, stats in sorted(results["per_tool_accuracy"].items()):
                print(f"  {tool_name:<20} {stats['correct']}/{stats['total']} ({stats['accuracy']}%)")

        print(f"{'='*60}\n")

    return results


def compare_descriptions(base_url: str, model: str, api_key: str = "ollama"):
    """Compare different description sets for a model."""
    print(f"\n{'='*80}")
    print(f"COMPARING DESCRIPTION SETS FOR: {model}")
    print(f"{'='*80}")

    all_results = []
    for desc_set in ["default", "enhanced", "minimal", "explicit"]:
        results = benchmark_model(
            base_url, model, api_key,
            parse_content=True,
            description_set=desc_set,
            verbose=False
        )
        all_results.append(results)
        tool_acc = f"{100*results['correct_tool']/results['total']:.1f}%"
        args_acc = f"{100*results['correct_args']/results['total']:.1f}%"
        avg_lat = f"{sum(results['latencies_ms'])/len(results['latencies_ms']):.0f}ms" if results['latencies_ms'] else "N/A"
        print(f"  {desc_set:<12} Tool: {tool_acc:<8} Args: {args_acc:<8} Latency: {avg_lat}")

    return all_results


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Benchmark tool-calling accuracy for LLMs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic benchmark with content parsing
  python benchmark_tool_routing.py --model qwen2.5-coder:0.5b --parse-content

  # Compare multiple models
  python benchmark_tool_routing.py --compare --parse-content

  # Test different description styles
  python benchmark_tool_routing.py --model qwen2.5-coder:0.5b --compare-descriptions

  # Test with enhanced descriptions
  python benchmark_tool_routing.py --model qwen2.5-coder:0.5b --descriptions enhanced

  # Run only filesystem tests
  python benchmark_tool_routing.py --model qwen2.5-coder:0.5b --profile filesystem
        """
    )
    parser.add_argument("--model", default="qwen2.5-coder:0.5b", help="Model to benchmark")
    parser.add_argument("--base-url", default="http://localhost:11434/v1", help="API base URL")
    parser.add_argument("--api-key", default="ollama", help="API key")
    parser.add_argument("--compare", action="store_true", help="Compare multiple models")
    parser.add_argument("--compare-descriptions", action="store_true", help="Compare description sets for one model")
    parser.add_argument("--parse-content", action="store_true", help="Also parse tool calls from content (ppxai-style)")
    parser.add_argument("--descriptions", default="default", choices=["default", "enhanced", "minimal", "explicit"],
                        help="Tool description set to use")
    parser.add_argument("--profile", default="all", choices=["all", "shell", "filesystem", "editing", "conversational"],
                        help="Test profile to run")
    parser.add_argument("--output", type=str, help="Save results to JSON file")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")
    args = parser.parse_args()

    if args.compare_descriptions:
        all_results = compare_descriptions(args.base_url, args.model, args.api_key)
        if args.output:
            with open(args.output, 'w', encoding="utf-8") as f:
                json.dump(all_results, f, indent=2)
            print(f"\nResults saved to {args.output}")

    elif args.compare:
        # Compare small models
        models = [
            "qwen2.5-coder:0.5b",
            "qwen2.5-coder:3b",
        ]
        all_results = []
        for model in models:
            try:
                results = benchmark_model(
                    args.base_url, model, args.api_key, args.parse_content,
                    description_set=args.descriptions,
                    profile=args.profile,
                    verbose=not args.quiet
                )
                all_results.append(results)
            except Exception as e:
                print(f"Failed to benchmark {model}: {e}")

        # Summary table
        print("\n" + "="*80)
        print("COMPARISON SUMMARY")
        print("="*80)
        print(f"{'Model':<25} {'Tool Acc':<12} {'Args Acc':<12} {'FP':<6} {'FN':<6} {'Latency':<12}")
        print("-"*80)
        for r in all_results:
            tool_acc = f"{100*r['correct_tool']/r['total']:.1f}%"
            args_acc = f"{100*r['correct_args']/r['total']:.1f}%"
            avg_lat = f"{sum(r['latencies_ms'])/len(r['latencies_ms']):.0f}ms" if r['latencies_ms'] else "N/A"
            print(f"{r['model']:<25} {tool_acc:<12} {args_acc:<12} {r['false_positive']:<6} {r['false_negative']:<6} {avg_lat:<12}")

        if args.output:
            with open(args.output, 'w', encoding="utf-8") as f:
                json.dump(all_results, f, indent=2)
            print(f"\nResults saved to {args.output}")
    else:
        results = benchmark_model(
            args.base_url, args.model, args.api_key, args.parse_content,
            description_set=args.descriptions,
            profile=args.profile,
            verbose=not args.quiet
        )

        if args.output:
            with open(args.output, 'w', encoding="utf-8") as f:
                json.dump(results, f, indent=2)
            print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
