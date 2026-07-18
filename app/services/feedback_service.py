"""Transactional Telegram feedback persistence and preference aggregation."""
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Item, ItemAnalysis, AnalysisStatus, Publication, Source, UserFeedback, UserPreference
from app.database.repositories import TelegramUpdateReceiptRepository, UserFeedbackRepository, UserPreferenceRepository

logger = structlog.get_logger()


@dataclass(frozen=True)
class FeedbackResult:
    applied: bool
    action: Optional[str] = None
    reason: Optional[str] = None
    duplicate: bool = False
    feedback: Optional[UserFeedback] = None


class FeedbackService:
    ACTIONS = {"like", "dislike", "favorite", "hide"}

    def __init__(
        self,
        db: Session,
        enabled: Optional[bool] = None,
        allowed_user_ids: Optional[str] = None,
        callback_prefix: Optional[str] = None,
        feedback_repository: Optional[UserFeedbackRepository] = None,
        preference_repository: Optional[UserPreferenceRepository] = None,
        receipt_repository: Optional[TelegramUpdateReceiptRepository] = None,
    ):
        self.db = db
        self.enabled = settings.TELEGRAM_FEEDBACK_ENABLED if enabled is None else enabled
        self.allowed_user_ids = settings.TELEGRAM_ALLOWED_USER_IDS if allowed_user_ids is None else allowed_user_ids
        self.callback_prefix = (callback_prefix or settings.TELEGRAM_FEEDBACK_CALLBACK_PREFIX).rstrip(":")
        self.feedback_repository = feedback_repository or UserFeedbackRepository(db)
        self.preference_repository = preference_repository or UserPreferenceRepository(db)
        self.receipt_repository = receipt_repository or TelegramUpdateReceiptRepository(db)

    def _allowed_ids(self) -> set[int]:
        values = set()
        for raw_value in self.allowed_user_ids.split(","):
            raw_value = raw_value.strip()
            if raw_value.isdigit():
                values.add(int(raw_value))
        return values

    def parse_callback(self, callback_data: Any) -> Optional[Tuple[str, int]]:
        if not isinstance(callback_data, str) or len(callback_data.encode("utf-8")) > 64:
            return None
        parts = callback_data.split(":")
        if len(parts) != 3 or parts[0] != self.callback_prefix or parts[1] not in self.ACTIONS:
            return None
        if not parts[2].isdigit() or int(parts[2]) <= 0:
            return None
        return parts[1], int(parts[2])

    def _get_publication(self, publication_id: int) -> Optional[Publication]:
        return self.db.query(Publication).filter(Publication.item_id == publication_id).first()

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

    def _preference_keys(self, publication_id: int) -> Dict[str, List[str]]:
        item = self.db.query(Item).filter(Item.id == publication_id).first()
        if not item:
            return {}
        source = self.db.query(Source).filter(Source.id == item.source_id).first()
        analysis = self.db.query(ItemAnalysis).filter(
            ItemAnalysis.item_id == publication_id,
            ItemAnalysis.status == AnalysisStatus.success,
        ).order_by(ItemAnalysis.id.desc()).first()
        values: Dict[str, List[str]] = {}
        if analysis and analysis.category:
            category = getattr(analysis.category, "value", analysis.category)
            normalised = self._normalise(category)
            if normalised:
                values["topic"] = [normalised]
        if source:
            source_name = self._normalise(source.name)
            source_type = self._normalise(source.source_type)
            if source_name:
                values["source"] = [source_name]
            if source_type:
                values["content_type"] = [source_type]
        if analysis:
            entities = list(dict.fromkeys(self._entity_values(analysis.entities)))
            if entities:
                values["entity"] = entities
        return values

    @staticmethod
    def _feedback_contributions(feedback: UserFeedback) -> List[int]:
        contributions = []
        if feedback.reaction == "like":
            contributions.append(1)
        elif feedback.reaction == "dislike":
            contributions.append(-1)
        if feedback.is_favorite:
            contributions.append(2)
        if feedback.is_hidden:
            contributions.append(-2)
        return contributions

    def _recalculate_preferences(self, telegram_user_id: int) -> None:
        aggregate: Dict[Tuple[str, str], Dict[str, int]] = {}
        for feedback in self.feedback_repository.list_for_user(telegram_user_id):
            contributions = self._feedback_contributions(feedback)
            if not contributions:
                continue
            for preference_type, keys in self._preference_keys(feedback.publication_id).items():
                for key in keys:
                    entry = aggregate.setdefault((preference_type, key), {"weight": 0, "positive": 0, "negative": 0})
                    for contribution in contributions:
                        entry["weight"] += contribution
                        if contribution > 0:
                            entry["positive"] += 1
                        else:
                            entry["negative"] += 1
        preferences = [
            UserPreference(
                telegram_user_id=telegram_user_id,
                preference_type=preference_type,
                preference_key=key,
                weight=max(-10, min(10, values["weight"])),
                positive_count=values["positive"],
                negative_count=values["negative"],
            )
            for (preference_type, key), values in aggregate.items()
        ]
        self.preference_repository.replace_for_user(telegram_user_id, preferences)

    def apply_feedback(
        self,
        update_id: int,
        telegram_user_id: int,
        callback_data: str,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
    ) -> FeedbackResult:
        if not self.enabled:
            return FeedbackResult(applied=False, reason="disabled")
        if telegram_user_id not in self._allowed_ids():
            logger.info("telegram_feedback_unauthorized", telegram_user_id=telegram_user_id)
            return FeedbackResult(applied=False, reason="unauthorized")
        parsed = self.parse_callback(callback_data)
        if not parsed:
            return FeedbackResult(applied=False, reason="invalid_callback")
        action, publication_id = parsed
        if self.receipt_repository.get(update_id):
            return FeedbackResult(applied=False, action=action, reason="duplicate", duplicate=True)
        publication = self._get_publication(publication_id)
        if not publication:
            return FeedbackResult(applied=False, action=action, reason="publication_not_found")
        if publication.telegram_chat_id is not None and chat_id != publication.telegram_chat_id:
            return FeedbackResult(applied=False, action=action, reason="message_mismatch")
        if publication.telegram_message_id is not None and message_id != publication.telegram_message_id:
            return FeedbackResult(applied=False, action=action, reason="message_mismatch")

        try:
            feedback = self.feedback_repository.get(telegram_user_id, publication_id)
            if not feedback:
                feedback = UserFeedback(telegram_user_id=telegram_user_id, publication_id=publication_id)
            if action in {"like", "dislike"}:
                feedback.reaction = action
            elif action == "favorite":
                feedback.is_favorite = not feedback.is_favorite
            else:
                feedback.is_hidden = True
            self.feedback_repository.save(feedback)
            self._recalculate_preferences(telegram_user_id)
            self.receipt_repository.create(update_id, telegram_user_id, publication_id)
            self.db.commit()
            logger.info("telegram_feedback_applied", update_id=update_id, telegram_user_id=telegram_user_id, publication_id=publication_id, action=action)
            return FeedbackResult(applied=True, action=action, feedback=feedback)
        except IntegrityError:
            self.db.rollback()
            if self.receipt_repository.get(update_id):
                return FeedbackResult(applied=False, action=action, reason="duplicate", duplicate=True)
            raise
        except Exception:
            self.db.rollback()
            raise

    def get_feedback(self, telegram_user_id: int, publication_id: int) -> Optional[UserFeedback]:
        return self.feedback_repository.get(telegram_user_id, publication_id)

    def list_favorites(self, telegram_user_id: int, limit: int = 100) -> List[UserFeedback]:
        return self.feedback_repository.list_favorites(telegram_user_id, limit)

    def hide_publication(self, telegram_user_id: int, publication_id: int, update_id: int) -> FeedbackResult:
        return self.apply_feedback(update_id, telegram_user_id, f"{self.callback_prefix}:hide:{publication_id}")

    def change_reaction(self, telegram_user_id: int, publication_id: int, reaction: str, update_id: int) -> FeedbackResult:
        return self.apply_feedback(update_id, telegram_user_id, f"{self.callback_prefix}:{reaction}:{publication_id}")
