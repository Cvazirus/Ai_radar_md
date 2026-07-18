"""Transactional handling of allowlisted Telegram moderation callbacks."""
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import func

from app.config import settings
from app.database.models import ItemStatus, ModerationDecisionLog, ModerationQueue, ModerationQueueStatus, TelegramModerationMessage, TelegramModerationUpdateReceipt
from app.pipeline.moderation_state_machine import is_transition_allowed

logger = structlog.get_logger()
_CALLBACK_RE = re.compile(r"^moderation:(approve|reject|defer|details):([1-9][0-9]*)$")
_CLOSED = {ModerationQueueStatus.approved, ModerationQueueStatus.rejected, ModerationQueueStatus.needs_revision, ModerationQueueStatus.expired, ModerationQueueStatus.cancelled}


@dataclass
class ModerationDecisionResult:
    applied: bool
    action: Optional[str] = None
    reason: Optional[str] = None
    duplicate: bool = False
    details: Optional[Dict[str, Any]] = None


class ModerationDecisionService:
    def __init__(self, db, enabled: Optional[bool] = None, allowed_user_ids: Optional[str] = None, callback_prefix: Optional[str] = None, moderation_chat_id: Optional[int] = None):
        self.db = db
        self.enabled = settings.TELEGRAM_MODERATION_ENABLED if enabled is None else enabled
        self.allowed_user_ids = settings.TELEGRAM_MODERATION_ALLOWED_USER_IDS if allowed_user_ids is None else allowed_user_ids
        self.callback_prefix = settings.TELEGRAM_MODERATION_CALLBACK_PREFIX if callback_prefix is None else callback_prefix
        self.moderation_chat_id = int(settings.TELEGRAM_MODERATION_CHAT_ID if moderation_chat_id is None else moderation_chat_id)

    @staticmethod
    def parse_callback(callback_data: str) -> Optional[Tuple[str, int]]:
        match = _CALLBACK_RE.fullmatch(callback_data) if isinstance(callback_data, str) else None
        return (match.group(1), int(match.group(2))) if match else None

    def _allowed_ids(self) -> set[int]:
        return {int(value.strip()) for value in self.allowed_user_ids.split(",") if value.strip().isdigit() and int(value.strip()) > 0}

    @staticmethod
    def _details(queue: ModerationQueue) -> Dict[str, Any]:
        return {"queue_id": queue.id, "status": queue.queue_status.value, "title": queue.item.title, "url": queue.item.url, "summary": queue.analysis.summary_ru, "score": queue.analysis.total_score}

    def _reserve_receipt(self, update_id: int, telegram_user_id: int, queue_id: int) -> bool:
        statement = insert(TelegramModerationUpdateReceipt).values(update_id=update_id, telegram_user_id=telegram_user_id, moderation_queue_id=queue_id).on_conflict_do_nothing(index_elements=["update_id"])
        return self.db.execute(statement).rowcount == 1

    def apply_decision(self, update_id: int, telegram_user_id: int, callback_data: str, chat_id: Optional[int] = None, message_id: Optional[int] = None) -> ModerationDecisionResult:
        if not self.enabled:
            return ModerationDecisionResult(False, reason="disabled")
        if self.callback_prefix != "moderation" or telegram_user_id not in self._allowed_ids():
            return ModerationDecisionResult(False, reason="unauthorized")
        parsed = self.parse_callback(callback_data)
        if not parsed:
            return ModerationDecisionResult(False, reason="invalid_callback")
        action, queue_id = parsed
        try:
            queue = self.db.query(ModerationQueue).filter(ModerationQueue.id == queue_id).with_for_update().first()
            if not queue:
                self.db.rollback()
                return ModerationDecisionResult(False, action, "queue_not_found")
            message = self.db.query(TelegramModerationMessage).filter(
                TelegramModerationMessage.moderation_queue_id == queue.id,
                TelegramModerationMessage.telegram_chat_id == chat_id,
                TelegramModerationMessage.telegram_message_id == message_id,
            ).first()
            if message is not None and getattr(message, "is_active", True) is False:
                self.db.rollback()
                return ModerationDecisionResult(False, action, "message_mismatch")
            if queue.telegram_chat_id is None or queue.telegram_message_id is None:
                if (
                    queue.telegram_dispatch_started_at is None
                    or chat_id != self.moderation_chat_id
                    or not isinstance(message_id, int)
                ):
                    self.db.rollback()
                    return ModerationDecisionResult(False, action, "message_mismatch")
                queue.telegram_chat_id = chat_id
                queue.telegram_message_id = message_id
                self.db.add(TelegramModerationMessage(
                    moderation_queue_id=queue.id,
                    telegram_chat_id=chat_id,
                    telegram_message_id=message_id,
                ))
            elif chat_id != queue.telegram_chat_id or message_id != queue.telegram_message_id:
                self.db.rollback()
                return ModerationDecisionResult(False, action, "message_mismatch")
            if action != "details" and not self._reserve_receipt(update_id, telegram_user_id, queue_id):
                self.db.rollback()
                return ModerationDecisionResult(False, action, "duplicate", True)
            if action == "details":
                details = self._details(queue)
                self.db.commit()
                return ModerationDecisionResult(False, action, "details", details=details)
            if queue.queue_status in _CLOSED:
                self.db.rollback()
                return ModerationDecisionResult(False, action, "closed")
            target = {"approve": ModerationQueueStatus.approved, "reject": ModerationQueueStatus.rejected, "defer": ModerationQueueStatus.needs_revision}[action]
            if not is_transition_allowed(queue.queue_status, target):
                self.db.rollback()
                return ModerationDecisionResult(False, action, "conflict")
            previous = queue.queue_status
            queue.queue_status, queue.reviewed_by, queue.reviewed_at = target, str(telegram_user_id), func.now()
            if action == "defer":
                queue.review_notes = "deferred from Telegram moderation"
            elif action == "approve":
                queue.item.status = ItemStatus.manual_review_approved
            else:
                queue.item.status = ItemStatus.rejected
            self.db.add(ModerationDecisionLog(queue_id=queue.id, previous_status=previous, new_status=target, action=action, actor=str(telegram_user_id), reason="Telegram moderation decision", metadata_json={"telegram_update_id": update_id, "telegram_user_id": telegram_user_id}))
            self.db.commit()
            logger.info("telegram_moderation_applied", queue_id=queue.id, action=action, telegram_user_id=telegram_user_id)
            return ModerationDecisionResult(True, action)
        except IntegrityError:
            self.db.rollback()
            return ModerationDecisionResult(False, action, "duplicate", True)
        except Exception:
            self.db.rollback()
            raise
