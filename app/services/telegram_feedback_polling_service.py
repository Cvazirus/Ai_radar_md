"""Long-poll Telegram callback updates without pipeline or ranking dependencies."""
import signal
import time
from typing import Optional

import structlog

from app.config import settings
from app.publishers.telegram import TelegramPublisher
from app.services.feedback_service import FeedbackService

logger = structlog.get_logger()


class TelegramFeedbackPollingService:
    def __init__(
        self,
        publisher: TelegramPublisher,
        feedback_service: FeedbackService,
        poll_timeout_seconds: Optional[int] = None,
        batch_limit: Optional[int] = None,
    ):
        self.publisher = publisher
        self.feedback_service = feedback_service
        self.poll_timeout_seconds = poll_timeout_seconds or settings.TELEGRAM_FEEDBACK_POLL_TIMEOUT_SECONDS
        self.batch_limit = batch_limit or settings.TELEGRAM_FEEDBACK_BATCH_LIMIT
        self.offset: Optional[int] = None
        self._running = True

    def _stop(self, *_args) -> None:
        self._running = False

    def poll_once(self) -> bool:
        result = self.publisher.get_updates(
            offset=self.offset,
            timeout=self.poll_timeout_seconds,
            limit=self.batch_limit,
        )
        if not result.success:
            logger.warning("telegram_feedback_poll_failed", error=result.error, error_code=result.error_code)
            return False
        for update in result.data or []:
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                continue
            self.offset = update_id + 1
            callback = update.get("callback_query")
            if not isinstance(callback, dict):
                continue
            message = callback.get("message") or {}
            chat = message.get("chat") or {}
            sender = callback.get("from") or {}
            callback_id = callback.get("id")
            sender_id = sender.get("id")
            if not callback_id or not isinstance(sender_id, int):
                continue
            feedback = self.feedback_service.apply_feedback(
                update_id=update_id,
                telegram_user_id=sender_id,
                callback_data=callback.get("data", ""),
                chat_id=chat.get("id"),
                message_id=message.get("message_id"),
            )
            answer = "Сохранено" if feedback.applied else "Недоступно"
            self.publisher.answer_callback_query(callback_id, text=answer)
        return True

    def run_forever(self) -> None:
        previous_handlers = {
            signal.SIGINT: signal.signal(signal.SIGINT, self._stop),
            signal.SIGTERM: signal.signal(signal.SIGTERM, self._stop),
        }
        try:
            while self._running:
                if not self.poll_once():
                    time.sleep(1)
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
