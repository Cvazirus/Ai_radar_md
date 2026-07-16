import json
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Penalty:
    code: str
    value: float
    reason: str

    def to_dict(self):
        return {"code": self.code, "value": self.value, "reason": self.reason}


@dataclass
class ScoreResult:
    base_score: float
    penalties: List[Penalty]
    total_score: float
    score_version: str

    def to_penalties_json(self):
        return [p.to_dict() for p in self.penalties]


def calculate_score(
    relevance_score: int,
    practicality_score: int,
    novelty_score: int,
    credibility_score: int,
    confidence: float,
    is_promotional: bool,
    has_tech_claims: bool,
    final_is_primary_source: bool,
    has_high_uncertainty: bool,
    score_version: str = "1.0",
) -> ScoreResult:
    base_score = (
        relevance_score * 0.35 +
        practicality_score * 0.30 +
        novelty_score * 0.20 +
        credibility_score * 0.15
    )

    penalties = []

    if is_promotional and not has_tech_claims:
        penalties.append(Penalty(
            code="promotional_no_tech_claims",
            value=-3.0,
            reason="Promotional material without technical claims"
        ))

    if not final_is_primary_source:
        penalties.append(Penalty(
            code="secondary_source",
            value=-2.0,
            reason="Not a primary source"
        ))

    if confidence < 0.60:
        penalties.append(Penalty(
            code="low_confidence",
            value=-2.0,
            reason=f"Confidence {confidence:.2f} below 0.60 threshold"
        ))

    if has_high_uncertainty:
        penalties.append(Penalty(
            code="high_uncertainty",
            value=-3.0,
            reason="Contains high severity uncertainties"
        ))

    penalty_total = sum(p.value for p in penalties)
    total_score = max(0.0, min(10.0, base_score + penalty_total))

    return ScoreResult(
        base_score=round(base_score, 2),
        penalties=penalties,
        total_score=round(total_score, 2),
        score_version=score_version,
    )
