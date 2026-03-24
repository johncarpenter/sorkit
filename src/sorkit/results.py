"""Results TSV tracking — append, query, and analyze experiment outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


HEADER = "timestamp\tlayer\thypothesis\tscore\toutcome"


@dataclass
class ResultEntry:
    timestamp: str
    layer: str
    hypothesis: str
    score: str  # float string or "PASS"/"FAIL"
    outcome: str  # KEEP, DISCARD, DISCARD FAIL, STOP:reason, etc.


class ResultsStore:
    """Read/write interface for results.tsv."""

    def __init__(self, project_dir: Path) -> None:
        self.path = project_dir / "results.tsv"

    def ensure_exists(self) -> None:
        """Create results.tsv with header if it doesn't exist."""
        if not self.path.exists():
            self.path.write_text(HEADER + "\n")

    def append(self, entry: ResultEntry) -> None:
        """Append a result entry to the TSV."""
        self.ensure_exists()
        line = (
            f"{entry.timestamp}\t{entry.layer}\t{entry.hypothesis}"
            f"\t{entry.score}\t{entry.outcome}\n"
        )
        with open(self.path, "a") as f:
            f.write(line)

    def append_now(
        self, layer: str, hypothesis: str, score: str, outcome: str
    ) -> ResultEntry:
        """Create and append an entry with the current timestamp."""
        entry = ResultEntry(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            layer=layer,
            hypothesis=hypothesis,
            score=score,
            outcome=outcome,
        )
        self.append(entry)
        return entry

    def _load_entries(self) -> list[ResultEntry]:
        """Load all entries from the TSV."""
        if not self.path.exists():
            return []
        entries: list[ResultEntry] = []
        for line in self.path.read_text().splitlines()[1:]:  # skip header
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            entries.append(ResultEntry(
                timestamp=parts[0],
                layer=parts[1],
                hypothesis=parts[2],
                score=parts[3],
                outcome=parts[4],
            ))
        return entries

    def get_all_entries(self, layer: str | None = None) -> list[ResultEntry]:
        """Get all entries, optionally filtered by layer."""
        entries = self._load_entries()
        if layer is not None:
            entries = [e for e in entries if e.layer == layer]
        return entries

    def count_layer_attempts(self, layer: str) -> int:
        """Count total attempts for a layer."""
        return len(self.get_all_entries(layer))

    def get_best_score(self, layer: str) -> float | None:
        """Get the best (highest) score from KEEP entries for a layer."""
        keeps = [
            e for e in self.get_all_entries(layer)
            if e.outcome == "KEEP" and _is_numeric(e.score)
        ]
        if not keeps:
            return None
        return max(float(e.score) for e in keeps)

    def get_keep_count(self, layer: str) -> int:
        """Count KEEP outcomes for a layer."""
        return sum(1 for e in self.get_all_entries(layer) if e.outcome == "KEEP")

    def get_recent_keeps(self, layer: str, n: int) -> list[float]:
        """Get the last N KEEP scores for a layer (oldest first)."""
        keeps = [
            float(e.score)
            for e in self.get_all_entries(layer)
            if e.outcome == "KEEP" and _is_numeric(e.score)
        ]
        return keeps[-n:]

    def get_consecutive_non_improvements(self, layer: str) -> int:
        """Count consecutive non-KEEP outcomes from the tail for a layer."""
        entries = self.get_all_entries(layer)
        count = 0
        for entry in reversed(entries):
            if entry.outcome == "KEEP":
                break
            count += 1
        return count

    def get_consecutive_failures(self, layer: str) -> int:
        """Count consecutive FAIL/ERROR outcomes from the tail for a layer."""
        entries = self.get_all_entries(layer)
        count = 0
        for entry in reversed(entries):
            is_fail = "FAIL" in entry.score or "ERROR" in entry.score
            is_error_outcome = "ERROR" in entry.outcome or "FAIL" in entry.outcome
            if not (is_fail or is_error_outcome):
                break
            count += 1
        return count


def _is_numeric(s: str) -> bool:
    """Check if a string represents a numeric value."""
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False
