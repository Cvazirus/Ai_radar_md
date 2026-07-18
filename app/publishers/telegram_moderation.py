"""Telegram transport for moderation cards; it intentionally has no database imports."""
from datetime import datetime
from html import escape
from typing import Any, Dict, Optional

from app.config import settings
from app.publishers.telegram import TelegramPublisher, TelegramResult


class TelegramModerationPublisher:
    def __init__(self, telegram: TelegramPublisher, chat_id: Optional[str] = None):
        self.telegram = telegram
        self.chat_id = chat_id or settings.TELEGRAM_MODERATION_CHAT_ID

    @staticmethod
    def _escaped_text(value: Any, limit: int) -> str:
        text = str(getattr(value, "value", value) if value is not None else "-").strip()
        escaped = escape(text)
        if len(escaped) <= limit:
            return escaped
        for end in range(len(text), 0, -1):
            escaped = escape(text[:end]).rstrip()
            if len(escaped) <= limit - 3:
                return f"{escaped}..."
        return "..."

    def format_card(self, queue: Any) -> str:
        item, analysis = queue.item, queue.analysis
        collected = getattr(item, "collected_at", None)
        collected = collected.strftime("%Y-%m-%d %H:%M UTC") if isinstance(collected, datetime) else collected
        return (
            f"<b>Модерация #{queue.id}</b>\n<b>{self._escaped_text(item.title, 400)}</b>\n\n"
            f"{self._escaped_text(getattr(analysis, 'summary_ru', None), 2200)}\n\n"
            f"<b>Источник:</b> {self._escaped_text(getattr(getattr(item, 'source', None), 'name', None), 150)}\n"
            f"<b>URL:</b> {self._escaped_text(getattr(item, 'url', None), 500)}\n"
            f"<b>Категория:</b> {self._escaped_text(getattr(analysis, 'category', None), 100)}\n"
            f"<b>Оценка:</b> {self._escaped_text(getattr(analysis, 'total_score', None), 50)}\n"
            f"<b>Собрано:</b> {self._escaped_text(collected, 50)}\n"
            f"<b>Статус:</b> {self._escaped_text(queue.queue_status, 50)}"
        )

    @staticmethod
    def keyboard(queue_id: int) -> Dict[str, Any]:
        return {"inline_keyboard": [
            [{"text": "✅ Одобрить", "callback_data": f"moderation:approve:{queue_id}"}, {"text": "❌ Отклонить", "callback_data": f"moderation:reject:{queue_id}"}],
            [{"text": "⏸ Отложить", "callback_data": f"moderation:defer:{queue_id}"}, {"text": "ℹ️ Подробнее", "callback_data": f"moderation:details:{queue_id}"}],
        ]}

    def publish(self, queue: Any) -> TelegramResult:
        return self.telegram.send_html(self.format_card(queue), chat_id=self.chat_id, reply_markup=self.keyboard(queue.id))
