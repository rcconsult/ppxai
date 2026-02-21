#!/usr/bin/env python3
"""One-time script to recalculate historical usage costs with corrected pricing.

Reads ~/.ppxai/usage/usage.json, recalculates estimated_cost for every session
using the correct per-1M-token rates, and writes back. Creates a backup first.
"""

import json
import os
import shutil
from datetime import datetime

# Corrected pricing (USD per 1M tokens) — verified against provider invoices
PRICING = {
    # Perplexity (verified Feb 2026 invoice)
    "perplexity/sonar":               {"input": 1.00,  "output": 1.00},
    "perplexity/sonar-pro":           {"input": 3.00,  "output": 15.00},
    "perplexity/sonar-reasoning-pro": {"input": 2.00,  "output": 8.00},
    "perplexity/sonar-deep-research": {"input": 2.00,  "output": 8.00},
    # Gemini (verified Feb 2026 GCP billing)
    "gemini/gemini-2.0-flash":        {"input": 0.10,  "output": 0.40},
    "gemini/gemini-2.5-flash":        {"input": 0.30,  "output": 2.50},
    "gemini/gemini-2.5-flash-lite":   {"input": 0.075, "output": 0.30},
    "gemini/gemini-2.5-pro":          {"input": 1.25,  "output": 10.00},
    "gemini/gemini-3-flash-preview":  {"input": 0.50,  "output": 3.00},
    "gemini/gemini-3-pro-preview":    {"input": 2.00,  "output": 12.00},
    # OpenAI (verified Feb 2026 billing CSV)
    "openai/gpt-5.2":                {"input": 1.75,  "output": 14.00},
    "openai/gpt-5":                  {"input": 1.25,  "output": 10.00},
    "openai/gpt-5-mini":             {"input": 0.25,  "output": 2.00},
    "openai/gpt-5-nano":             {"input": 0.05,  "output": 0.40},
    "openai/gpt-5.1-codex":          {"input": 1.25,  "output": 10.00},
    "openai/gpt-5.1-codex-mini":     {"input": 0.25,  "output": 2.00},
    "openai/gpt-4.1":                {"input": 2.00,  "output": 8.00},
    "openai/gpt-4.1-mini":           {"input": 0.40,  "output": 1.60},
    "openai/gpt-4.1-nano":           {"input": 0.10,  "output": 0.40},
    "openai/o4-mini":                {"input": 1.10,  "output": 4.40},
    "openai/o3-mini":                {"input": 1.10,  "output": 4.40},
    "openai/gpt-4o":                 {"input": 2.50,  "output": 10.00},
    "openai/gpt-4o-mini":            {"input": 0.15,  "output": 0.60},
    # Local / custom (free)
    "custom/openai/gpt-oss-120b":    {"input": 0.0,   "output": 0.0},
    "asusai-vllm/Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8": {"input": 0.0, "output": 0.0},
}


def calc_cost(prompt_tokens: int, completion_tokens: int, model_key: str) -> float:
    pricing = PRICING.get(model_key)
    if not pricing:
        return 0.0
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


def main():
    usage_path = os.path.expanduser("~/.ppxai/usage/usage.json")

    if not os.path.exists(usage_path):
        print(f"Usage file not found: {usage_path}")
        return

    with open(usage_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    # Backup
    backup = usage_path + ".bak-" + datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(usage_path, backup)
    print(f"Backup: {backup}")

    # Recalculate
    total_old = 0.0
    total_new = 0.0
    changes = 0

    for session in data.get("sessions", []):
        session_cost = 0.0
        for model_key, usage in session.get("usage_by_model", {}).items():
            old_cost = usage.get("estimated_cost", 0.0)
            new_cost = calc_cost(
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                model_key,
            )
            if abs(old_cost - new_cost) > 0.000001:
                changes += 1
                sid = session["session_id"]
                delta = new_cost - old_cost
                print(f"  {sid} | {model_key}: ${old_cost:.6f} -> ${new_cost:.6f} (delta: ${delta:+.6f})")
            usage["estimated_cost"] = new_cost
            session_cost += new_cost
            total_old += old_cost
            total_new += new_cost

        session["total_cost"] = round(session_cost, 6)

    # Write back
    with open(usage_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print()
    print(f"Changes: {changes} model entries across {len(data['sessions'])} sessions")
    print(f"Old total: ${total_old:.4f}")
    print(f"New total: ${total_new:.4f}")
    print(f"Delta:     ${total_new - total_old:+.4f}")


if __name__ == "__main__":
    main()
