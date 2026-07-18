"""Long-poll moderation callbacks without publication or personal feedback behavior."""
import signal
import time
from html import escape
from typing import Callable, Optional

import structlog

from app.config import settings
from app.publishers.telegram import TelegramPublisher
from app.services.moderation_decision_service import ModerationDecisionService

logger = structlog.get_logger()


class TelegramModerationPollingService:
    def __init__(self, publisher: TelegramPublisher, decisions: ModerationDecisionService, poll_timeout_seconds: Optional[int] = None, batch_limit: Optional[int] = None):
        self.publisher = publisher
        self.decisions = decisions
        self.poll_timeout_seconds = poll_timeout_seconds or settings.TELEGRAM_MODERATION_POLL_TIMEOUT_SECONDS
        self.batch_limit = batch_limit or settings.TELEGRAM_MODERATION_BATCH_LIMIT
        self.offset = None
        self._running = True

    def _stop(self, *_args) -> None:
        self._running = False

    @staticmethod
    def _answer(result) -> str:
        if result.applied:
            return {"approve": "Одобрено", "reject": "Отклонено", "defer": "Отложено"}.get(result.action, "Сохранено")
        if result.reason == "details":
            return "Подробности отправлены"
        return "Уже обработано" if result.duplicate else "Недоступно"

    @staticmethod
    def _escaped_text(value, limit: int) -> str:
        text = str(value or "-").strip()
        escaped = escape(text)
        if len(escaped) <= limit:
            return escaped
        for end in range(len(text), 0, -1):
            escaped = escape(text[:end]).rstrip()
            if len(escaped) <= limit - 3:
                return f"{escaped}..."
        return "..."

    @classmethod
    def _details_text(cls, details) -> str:
        details = details or {}
        title = cls._escaped_text(details.get("title"), 500)
        summary = cls._escaped_text(details.get("summary"), 2500)
        url = cls._escaped_text(details.get("url"), 800)
        return (
            f"<b>Модерация #{details.get('queue_id', '-')}</b>\n<b>{title}</b>\n\n"
            f"{summary}\n\n<b>URL:</b> {url}\n<b>Оценка:</b> {cls._escaped_text(details.get('score'), 100)}"
        )

    def poll_once(self) -> bool:
        result = self.publisher.get_updates(offset=self.offset, timeout=self.poll_timeout_seconds, limit=self.batch_limit)
        if not result.success:
            logger.warning("telegram_moderation_poll_failed", error=result.error, error_code=result.error_code)
            return False
        for update in result.data or []:
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                continue
            self.offset = update_id + 1
            callback = update.get("callback_query")
            if not isinstance(callback, dict) or not str(callback.get("data", "")).startswith("moderation:"):
                continue
            message = callback.get("message") or {}
            chat, sender = message.get("chat") or {}, callback.get("from") or {}
            callback_id, sender_id = callback.get("id"), sender.get("id")
            if not callback_id or not isinstance(sender_id, int):
                continue
            decision = self.decisions.apply_decision(update_id=update_id, telegram_user_id=sender_id, callback_data=callback.get("data", ""), chat_id=chat.get("id"), message_id=message.get("message_id"))
            if decision.reason == "details" and isinstance(chat.get("id"), int):
                details_sent = self.publisher.send_html(self._details_text(decision.details), chat_id=str(chat["id"]))
                self.publisher.answer_callback_query(
                    callback_id,
                    text="Подробности отправлены" if details_sent.success else "Не удалось отправить подробности",
                )
            else:
                self.publisher.answer_callback_query(callback_id, text=self._answer(decision))
            if decision.applied and isinstance(chat.get("id"), int) and isinstance(message.get("message_id"), int):
                edited = self.publisher.edit_message_reply_markup(chat["id"], message["message_id"], None)
                if not edited.success:
                    logger.warning("telegram_moderation_edit_failed_after_commit", update_id=update_id, error=edited.error)
        return True

    def run_forever(self, before_poll: Optional[Callable[[], int]] = None) -> None:
        previous = {signal.SIGINT: signal.signal(signal.SIGINT, self._stop), signal.SIGTERM: signal.signal(signal.SIGTERM, self._stop)}
        try:
            while self._running:
                if before_poll is not None:
                    before_poll()
                if not self.poll_once():
                    time.sleep(1)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
