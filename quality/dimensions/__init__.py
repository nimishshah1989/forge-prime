"""Dimension registry — shared types and discovery for the ATLAS quality engine.

Every dimension module exposes a `run() -> DimensionResult` function.
The registry maps dimension names to their runners and gating status.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass
class CheckResult:
    check_id: str
    name: str
    score: int
    max_score: int
    evidence: str
    plain_english: str
    fix: str
    severity: str  # critical | high | medium | low | info
    status: str = "RUN"  # RUN | SKIP | ERROR

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DimensionResult:
    dimension: str
    checks: list[CheckResult] = field(default_factory=list)
    gating: bool = True

    @property
    def passed(self) -> int:
        return sum(c.score for c in self.checks if c.status == "RUN")

    @property
    def eligible(self) -> int:
        return sum(c.max_score for c in self.checks if c.status == "RUN")

    @property
    def score(self) -> int:
        if self.eligible == 0:
            return 100
        return round(self.passed * 100 / self.eligible)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "score": self.score,
            "gating": self.gating,
            "passed": self.passed,
            "eligible": self.eligible,
            "checks": [c.to_dict() for c in self.checks],
        }


DimRunner = Callable[[], DimensionResult]

REGISTRY: dict[str, DimRunner] = {}
GATING: dict[str, bool] = {}


def register(name: str, runner: DimRunner, *, gating: bool = True) -> None:
    REGISTRY[name] = runner
    GATING[name] = gating


def run_dimension(name: str) -> DimensionResult:
    runner = REGISTRY[name]
    result = runner()
    result.gating = GATING.get(name, True)
    return result


def run_all(selected: list[str] | None = None) -> dict[str, Any]:
    names = selected or list(REGISTRY.keys())
    dims: dict[str, dict[str, Any]] = {}
    for name in names:
        result = run_dimension(name)
        dims[name] = result.to_dict()
    return {
        "dims": dims,
        "generated_at": _now_iso(),
    }


def _now_iso() -> str:
    from datetime import datetime, timezone, timedelta

    IST = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(IST).isoformat()
