"""
Configuration and constants for the ppxai application.
"""

from pathlib import Path

# Directories for data storage
SESSIONS_DIR = Path.home() / ".ppxai" / "sessions"
EXPORTS_DIR = Path.home() / ".ppxai" / "exports"
USAGE_FILE = Path.home() / ".ppxai" / "usage.json"

# Ensure directories exist
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Perplexity API pricing (per million tokens) - approximate values
# Source: https://docs.perplexity.ai/guides/pricing
MODEL_PRICING = {
    "sonar": {"input": 0.20, "output": 0.20},
    "sonar-pro": {"input": 3.00, "output": 15.00},
    "sonar-reasoning": {"input": 1.00, "output": 5.00},
    "sonar-reasoning-pro": {"input": 5.00, "output": 15.00},
    "sonar-deep-research": {"input": 5.00, "output": 15.00},
}

# Available Perplexity models
MODELS = {
    "1": {
        "id": "sonar",
        "name": "Sonar",
        "description": "Lightweight search model with real-time grounding"
    },
    "2": {
        "id": "sonar-pro",
        "name": "Sonar Pro",
        "description": "Advanced search model for complex queries"
    },
    "3": {
        "id": "sonar-reasoning",
        "name": "Sonar Reasoning",
        "description": "Fast reasoning model for problem-solving with search"
    },
    "4": {
        "id": "sonar-reasoning-pro",
        "name": "Sonar Reasoning Pro",
        "description": "Precision reasoning with Chain of Thought capabilities"
    },
    "5": {
        "id": "sonar-deep-research",
        "name": "Sonar Deep Research",
        "description": "Exhaustive research with comprehensive reports"
    },
}

# Best model for coding tasks (using Sonar Pro for advanced reasoning)
CODING_MODEL = "sonar-pro"
