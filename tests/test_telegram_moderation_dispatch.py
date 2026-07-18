import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.database.models import ModerationQueueStatus
from app.publishers.telegram import TelegramResult
from app.services.moderation_telegram_dispatch_service import ModerationTelegramDispatchService


class FakeQuery:
    def __init__(self, records):
        self.records = records

    def filter(self, *_args):
        return self

    def with_for_update(self):
        return self

    def order_by(self, *_args):
        return self

    def limit(self, _limit):
        return self

    def first(self):
        return next(
            (
                record
                for record in self.records
                if (
                    record.telegram_chat_id is None
                    and record.telegram_message_id is None
                    and record.telegram_dispatch_started_at is None
                )
            ),
            None,
        )

    def all(self):
        return self.records


class FakeSession:
    def __init__(self, records):
        self.records = records
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, _model):
        return FakeQuery(self.records)

    def commit(self):
        self.commits += 1

    def add(self, value):
        self.added.append(value)

    def rollback(self):
        self.rollbacks += 1


def pending_queue():
    return SimpleNamespace(
        id=11,
        queue_status=ModerationQueueStatus.pending,
        telegram_chat_id=None,
        telegram_message_id=None,
        telegram_dispatch_started_at=None,
    )


def test_dispatch_persists_the_message_link_returned_by_telegram():
    queue = pending_queue()
    db = FakeSession([queue])
    publisher = MagicMock()
    publisher.publish.return_value = TelegramResult(success=True, message_id=44)

    sent = ModerationTelegramDispatchService(db, publisher, chat_id=-10011).dispatch_pending()

    assert sent == 1
    assert queue.telegram_chat_id == -10011
    assert queue.telegram_message_id == 44
    assert queue.telegram_dispatch_started_at is not None
    assert db.commits == 2


def test_dispatch_does_not_bind_or_commit_when_telegram_send_fails():
    queue = pending_queue()
    db = FakeSession([queue])
    publisher = MagicMock()
    publisher.publish.return_value = TelegramResult(success=False, error="unavailable")

    sent = ModerationTelegramDispatchService(db, publisher, chat_id=-10011).dispatch_pending()

    assert sent == 0
    assert queue.telegram_chat_id is None
    assert queue.telegram_message_id is None
    assert queue.telegram_dispatch_started_at is not None
    assert db.commits == 1


def test_dispatch_releases_a_reservation_after_a_confirmed_telegram_failure():
    queue = pending_queue()
    db = FakeSession([queue])
    publisher = MagicMock()
    publisher.publish.return_value = TelegramResult(success=False, error="bad request", error_code=400)

    sent = ModerationTelegramDispatchService(db, publisher, chat_id=-10011).dispatch_pending()

    assert sent == 0
    assert queue.telegram_dispatch_started_at is None
    assert db.commits == 2


def test_moderation_requires_a_dedicated_bot_token_when_enabled():
    with pytest.raises(ValueError, match="TELEGRAM_MODERATION_BOT_TOKEN"):
        Settings(TELEGRAM_MODERATION_ENABLED=True, TELEGRAM_MODERATION_BOT_TOKEN="")

    with pytest.raises(ValueError, match="must differ"):
        Settings(
            TELEGRAM_MODERATION_ENABLED=True,
            TELEGRAM_MODERATION_BOT_TOKEN="same-token",
            TELEGRAM_BOT_TOKEN="same-token",
        )


def test_moderation_runner_uses_only_the_dedicated_bot_token():
    from pathlib import Path

    runner = (Path(__file__).resolve().parents[1] / "scripts/run_telegram_moderation.py").read_text()

    assert "bot_token=settings.TELEGRAM_MODERATION_BOT_TOKEN" in runner
    assert "max_retries=0" in runner
    assert "before_poll=dispatcher.dispatch_pending" in runner


def test_card_never_ends_with_a_partial_html_entity():
    from app.publishers.telegram_moderation import TelegramModerationPublisher

    queue = pending_queue()
    queue.item = SimpleNamespace(
        title="Title",
        collected_at=None,
        source=SimpleNamespace(name="Source"),
        url="https://example.test/",
    )
    queue.analysis = SimpleNamespace(
        summary_ru="<" * 3000,
        category="category",
        total_score=8.5,
    )

    card = TelegramModerationPublisher(MagicMock(), chat_id="-10011").format_card(queue)

    assert len(card) <= 4096
    assert re.search(r"&(?!amp;|lt;|gt;|quot;|#x27;)", card) is None
