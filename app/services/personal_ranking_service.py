"""Deterministic per-user ranking adjustment derived from persisted preferences."""
from dataclasses import dataclass
from typing import Any, Iterable, List

from app.database.repositories import UserPreferenceRepository


@dataclass(frozen=True)
class PersonalRankingContribution:
    preference_type: str
    preference_key: str
    weight: int
    interactions: int
    confidence: float
    contribution: float


@dataclass(frozen=True)
class PersonalRankingResult:
    base_score: float
    personal_score: float
    final_score: float
    breakdown: List[PersonalRankingContribution]


class PersonalRankingService:
    def __init__(self, preference_repository: UserPreferenceRepository):
        self.preference_repository = preference_repository

    @staticmethod
    def _normalise(value: Any) -> str:
        return str(value).strip().lower() if value is not None else ""

    @classmethod
    def _entity_values(cls, value: Any) -> Iterable[str]:
        if isinstance(value, dict):
            for nested in value.values():
                yield from cls._entity_values(nested)
        elif isinstance(value, (list, tuple, set)):
            for nested in value:
                yield from cls._entity_values(nested)
        elif isinstance(value, str):
            normalised = cls._normalise(value)
            if normalised:
                yield normalised

    def rank(
        self,
        telegram_user_id: int,
        base_score: float,
        topic: Any = None,
        source: Any = None,
        entities: Any = None,
        content_type: Any = None,
    ) -> PersonalRankingResult:
        metadata = {
            "topic": {self._normalise(topic)},
            "source": {self._normalise(source)},
            "entity": set(self._entity_values(entities)),
            "content_type": {self._normalise(content_type)},
        }
        for values in metadata.values():
            values.discard("")

        breakdown = []
        for preference in self.preference_repository.list_for_user(telegram_user_id):
            if preference.preference_key not in metadata.get(preference.preference_type, set()):
                continue
            interactions = preference.positive_count + preference.negative_count
            confidence = min(1.0, interactions / 3.0)
            contribution = max(-3.0, min(3.0, float(preference.weight) * confidence))
            breakdown.append(PersonalRankingContribution(
                preference_type=preference.preference_type,
                preference_key=preference.preference_key,
                weight=preference.weight,
                interactions=interactions,
                confidence=confidence,
                contribution=contribution,
            ))

        personal_score = max(-4.0, min(4.0, sum(entry.contribution for entry in breakdown)))
        return PersonalRankingResult(
            base_score=float(base_score),
            personal_score=personal_score,
            final_score=float(base_score) + personal_score,
            breakdown=breakdown,
        )
