"""Send unbound moderation cards and persist their Telegram message linkage."""
from typing import Optional

import structlog
from sqlalchemy.sql import func

from app.config import settings
from app.database.models import ModerationQueue, ModerationQueueStatus, TelegramModerationMessage
from app.publishers.telegram_moderation import TelegramModerationPublisher

logger = structlog.get_logger()


class ModerationTelegramDispatchService:
    def __init__(
        self,
        db,
        publisher: TelegramModerationPublisher,
        chat_id: Optional[int] = None,
        batch_limit: Optional[int] = None,
    ):
        self.db = db
        self.publisher = publisher
        self.chat_id = int(settings.TELEGRAM_MODERATION_CHAT_ID if chat_id is None else chat_id)
        self.batch_limit = batch_limit or settings.TELEGRAM_MODERATION_BATCH_LIMIT

    def _reserve_next_pending_queue(self):
        queue = (
            self.db.query(ModerationQueue)
            .filter(
                ModerationQueue.queue_status == ModerationQueueStatus.pending,
                ModerationQueue.telegram_chat_id.is_(None),
                ModerationQueue.telegram_message_id.is_(None),
                ModerationQueue.telegram_dispatch_started_at.is_(None),
            )
            .order_by(ModerationQueue.queued_at)
            .with_for_update()
            .first()
        )
        if queue is not None:
            queue.telegram_dispatch_started_at = func.now()
            self.db.commit()
        return queue

    def dispatch_pending(self) -> int:
        sent = 0
        for _ in range(self.batch_limit):
            queue = self._reserve_next_pending_queue()
            if queue is None:
                break

            result = self.publisher.publish(queue)
            if not result.success or not isinstance(result.message_id, int):
                if result.error_code is not None:
                    queue.telegram_dispatch_started_at = None
                    self.db.commit()
                logger.warning(
                    "telegram_moderation_dispatch_failed",
                    queue_id=queue.id,
                    error=result.error,
                    error_code=result.error_code,
                )
                break

            queue.telegram_chat_id = self.chat_id
            queue.telegram_message_id = result.message_id
            self.db.add(TelegramModerationMessage(
                moderation_queue_id=queue.id,
                telegram_chat_id=self.chat_id,
                telegram_message_id=result.message_id,
            ))
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                logger.exception("telegram_moderation_dispatch_link_persistence_failed", queue_id=queue.id)
                break
            sent += 1

        return sent
