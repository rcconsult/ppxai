"""
Results storage and historical comparison for LLM benchmarks.
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class BenchmarkResult:
    """Result of a benchmark run."""
    provider: str
    model: str
    timestamp: str
    overall_score: float
    tests_passed: int
    tests_total: int
    duration_seconds: float
    category_scores: dict[str, float]
    test_results: list[dict]
    metadata: dict = field(default_factory=dict)

    @property
    def pair_key(self) -> str:
        """Get provider/model pair key."""
        return f"{self.provider}/{self.model}"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BenchmarkResult":
        """Create from dictionary."""
        return cls(**data)


class ResultsStore:
    """Persistent storage for benchmark results."""

    def __init__(self, results_dir: Path):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.results_dir / "index.json"
        self._load_index()

    def _load_index(self):
        """Load or create index."""
        if self.index_file.exists():
            with open(self.index_file, "r", encoding="utf-8") as f:
                self.index = json.load(f)
            # Ensure "runs" key exists (may be missing from older index files)
            if "runs" not in self.index:
                self.index["runs"] = []
        else:
            self.index = {"pairs": {}, "runs": []}

    def _save_index(self):
        """Save index to disk."""
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=2)

    def _get_result_filename(self, result: BenchmarkResult) -> str:
        """Generate unique filename for result."""
        # Hash of provider/model/timestamp for uniqueness
        key = f"{result.provider}/{result.model}/{result.timestamp}"
        hash_suffix = hashlib.md5(key.encode()).hexdigest()[:8]
        safe_provider = result.provider.replace("/", "_").replace("\\", "_")
        safe_model = result.model.replace("/", "_").replace("\\", "_")
        return f"{safe_provider}_{safe_model}_{result.timestamp[:10]}_{hash_suffix}.json"

    def save(self, result: BenchmarkResult):
        """Save benchmark result."""
        filename = self._get_result_filename(result)
        filepath = self.results_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2)

        # Update index
        pair_key = result.pair_key
        if pair_key not in self.index["pairs"]:
            self.index["pairs"][pair_key] = []

        agents_md_mode = result.metadata.get("agents_md_mode", "with")

        self.index["pairs"][pair_key].append({
            "filename": filename,
            "timestamp": result.timestamp,
            "overall_score": result.overall_score,
            "agents_md_mode": agents_md_mode,
        })

        self.index["runs"].append({
            "pair": pair_key,
            "filename": filename,
            "timestamp": result.timestamp,
            "overall_score": result.overall_score,
            "agents_md_mode": agents_md_mode,
        })

        self._save_index()

    def get_history(self, pair_key: str) -> list[BenchmarkResult]:
        """Get all results for a provider/model pair."""
        if pair_key not in self.index["pairs"]:
            return []

        results = []
        for entry in self.index["pairs"][pair_key]:
            filepath = self.results_dir / entry["filename"]
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    results.append(BenchmarkResult.from_dict(data))

        # Sort by timestamp
        results.sort(key=lambda r: r.timestamp)
        return results

    def get_latest(self, pair_key: str) -> Optional[BenchmarkResult]:
        """Get latest result for a provider/model pair."""
        history = self.get_history(pair_key)
        return history[-1] if history else None

    def list_pairs(self) -> list[str]:
        """List all provider/model pairs with results."""
        return list(self.index["pairs"].keys())

    def get_ranking(self, agents_md_mode: Optional[str] = None) -> list[tuple[str, float, int]]:
        """
        Get ranking of all provider/model pairs by best score.
        Args:
            agents_md_mode: Filter by 'with', 'without', or None for all.
        Returns list of (pair_key, best_score, num_runs).
        """
        ranking = []
        for pair_key in self.index["pairs"]:
            entries = self.index["pairs"][pair_key]
            if agents_md_mode:
                entries = [e for e in entries if e.get("agents_md_mode", "with") == agents_md_mode]
            if entries:
                best_score = max(e["overall_score"] for e in entries)
                ranking.append((pair_key, best_score, len(entries)))

        # Sort by score descending
        ranking.sort(key=lambda x: x[1], reverse=True)
        return ranking

    def get_category_ranking(self, category: str) -> list[tuple[str, float]]:
        """
        Get ranking for a specific category.
        Returns list of (pair_key, best_category_score).
        """
        ranking = []
        for pair_key in self.index["pairs"]:
            latest = self.get_latest(pair_key)
            if latest and category in latest.category_scores:
                ranking.append((pair_key, latest.category_scores[category]))

        ranking.sort(key=lambda x: x[1], reverse=True)
        return ranking

    def get_all_runs(self, limit: int = 100) -> list[dict]:
        """Get all runs sorted by timestamp (most recent first)."""
        runs = sorted(self.index["runs"], key=lambda r: r["timestamp"], reverse=True)
        return runs[:limit]

    def rebuild_index(self):
        """Rebuild index from result files, backfilling agents_md_mode."""
        new_index = {"pairs": {}, "runs": []}

        for filepath in sorted(self.results_dir.glob("*.json")):
            if filepath.name == "index.json":
                continue
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                result = BenchmarkResult.from_dict(data)
                pair_key = result.pair_key
                agents_md_mode = result.metadata.get("agents_md_mode", "with")
                entry = {
                    "filename": filepath.name,
                    "timestamp": result.timestamp,
                    "overall_score": result.overall_score,
                    "agents_md_mode": agents_md_mode,
                }
                if pair_key not in new_index["pairs"]:
                    new_index["pairs"][pair_key] = []
                new_index["pairs"][pair_key].append(entry)
                new_index["runs"].append({"pair": pair_key, **entry})
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        self.index = new_index
        self._save_index()

    def delete_pair(self, pair_key: str) -> bool:
        """Delete all results for a provider/model pair."""
        if pair_key not in self.index["pairs"]:
            return False

        # Delete files
        for entry in self.index["pairs"][pair_key]:
            filepath = self.results_dir / entry["filename"]
            if filepath.exists():
                filepath.unlink()

        # Update index
        del self.index["pairs"][pair_key]
        self.index["runs"] = [r for r in self.index["runs"] if r["pair"] != pair_key]
        self._save_index()

        return True
