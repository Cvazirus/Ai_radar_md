import html
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class ClaimValidationResult:
    valid_claims: list = field(default_factory=list)
    invalid_claims: list = field(default_factory=list)

    @property
    def precision(self) -> float:
        total = len(self.valid_claims) + len(self.invalid_claims)
        if total == 0:
            return 1.0
        return len(self.valid_claims) / total


def _normalize(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    text = text.lower().strip()
    return text


def validate_source_claims(raw_text: str, claims: list) -> ClaimValidationResult:
    if not raw_text or not claims:
        return ClaimValidationResult(
            valid_claims=[],
            invalid_claims=list(claims) if claims else []
        )

    normalized_text = _normalize(raw_text)
    result = ClaimValidationResult()

    for claim in claims:
        evidence = getattr(claim, 'evidence_text', None) or ""

        if not evidence or not evidence.strip():
            result.invalid_claims.append(claim)
            continue

        normalized_evidence = _normalize(evidence)

        if normalized_evidence in normalized_text:
            result.valid_claims.append(claim)
        else:
            result.invalid_claims.append(claim)

    return result
