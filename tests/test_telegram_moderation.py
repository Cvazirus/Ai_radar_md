from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.database.models import ItemStatus, ModerationQueueStatus
from app.publishers.telegram import TelegramResult
from app.publishers.telegram_moderation import TelegramModerationPublisher
from app.services.moderation_decision_service import ModerationDecisionService
from app.services.telegram_moderation_polling_service import TelegramModerationPollingService


class FakeQuery:
    def __init__(self, row):
        self.row = row

    def filter(self, *_args):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.row


class FakeSession:
    def __init__(self, queue, receipt_rowcount=1):
        self.queue = queue
        self.receipt_rowcount = receipt_rowcount
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, _statement):
        return SimpleNamespace(rowcount=self.receipt_rowcount)

    def query(self, _model):
        return FakeQuery(self.queue)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def queue(status=ModerationQueueStatus.pending, chat_id=-10011, message_id=22):
    item = SimpleNamespace(
        id=3,
        title="<Unsafe & title>",
        url="https://example.test/news",
        collected_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        source=SimpleNamespace(name="Example <Source>"),
        status=ItemStatus.pending_review,
    )
    analysis = SimpleNamespace(
        summary_ru="<summary> " * 900,
        category=SimpleNamespace(value="news"),
        total_score=8.5,
    )
    return SimpleNamespace(
        id=11,
        queue_status=status,
        telegram_chat_id=chat_id,
        telegram_message_id=message_id,
        telegram_dispatch_started_at=None,
        item=item,
        analysis=analysis,
        review_notes=None,
        reviewed_by=None,
        reviewed_at=None,
    )


def service(db, allowed="7", enabled=True, chat_id=-10011):
    return ModerationDecisionService(
        db,
        enabled=enabled,
        allowed_user_ids=allowed,
        callback_prefix="moderation",
        moderation_chat_id=chat_id,
    )


def apply(decision_service, action, update_id=1, sender=7, queue_id=11, chat_id=-10011, message_id=22):
    return decision_service.apply_decision(
        update_id=update_id,
        telegram_user_id=sender,
        callback_data=f"moderation:{action}:{queue_id}",
        chat_id=chat_id,
        message_id=message_id,
    )


@pytest.mark.parametrize("action,expected", [
    ("approve", ModerationQueueStatus.approved),
    ("reject", ModerationQueueStatus.rejected),
    ("defer", ModerationQueueStatus.needs_revision),
])
def test_decisions_apply_existing_moderation_transitions(action, expected):
    record = queue()
    db = FakeSession(record)

    result = apply(service(db), action)

    assert result.applied is True
    assert record.queue_status == expected
    assert len(db.added) == 1
    assert db.added[0].action == action
    assert db.commits == 1
    if action == "approve":
        assert record.item.status == ItemStatus.manual_review_approved
    if action == "reject":
        assert record.item.status == ItemStatus.rejected


def test_details_returns_card_without_decision_log_or_transition():
    record = queue()
    db = FakeSession(record)

    result = apply(service(db), "details")

    assert result.applied is False
    assert result.reason == "details"
    assert result.details["queue_id"] == 11
    assert record.queue_status == ModerationQueueStatus.pending
    assert db.added == []


@pytest.mark.parametrize("callback", [
    "moderation:approve:0",
    "moderation:unknown:11",
    "moderation:approve:11:extra",
    "feedback:approve:11",
    "moderation:approve: 11",
])
def test_malformed_unknown_or_cross_prefix_callbacks_do_not_write(callback):
    db = FakeSession(queue())

    result = service(db).apply_decision(1, 7, callback, -10011, 22)

    assert result.reason == "invalid_callback"
    assert db.added == []
    assert db.commits == 0


def test_empty_or_unauthorized_allowlist_does_not_write():
    db = FakeSession(queue())
    assert apply(service(db, allowed=""), "approve").reason == "unauthorized"
    assert apply(service(db, allowed="8"), "approve").reason == "unauthorized"
    assert db.added == []


def test_absent_queue_and_message_mismatch_are_safe():
    missing = FakeSession(None)
    assert apply(service(missing), "approve").reason == "queue_not_found"
    mismatch = FakeSession(queue())
    assert apply(service(mismatch), "approve", chat_id=-10012).reason == "message_mismatch"
    assert mismatch.rollbacks == 1


def test_callback_recovers_a_reserved_card_before_applying_the_decision():
    record = queue(chat_id=None, message_id=None)
    record.telegram_dispatch_started_at = object()
    db = FakeSession(record)

    result = apply(service(db), "approve")

    assert result.applied is True
    assert record.telegram_chat_id == -10011
    assert record.telegram_message_id == 22


def test_duplicate_update_is_idempotent_without_log_or_commit():
    db = FakeSession(queue(), receipt_rowcount=0)

    result = apply(service(db), "approve")

    assert result.duplicate is True
    assert result.reason == "duplicate"
    assert db.added == []
    assert db.commits == 0


def test_duplicate_same_decision_and_conflicting_moderator_are_safe_conflicts():
    record = queue(ModerationQueueStatus.approved)
    db = FakeSession(record)

    same = apply(service(db, allowed="7,8"), "approve")
    conflict = apply(service(db, allowed="7,8"), "reject", update_id=2, sender=8)

    assert same.reason == "closed"
    assert conflict.reason == "closed"
    assert db.rollbacks == 2
    assert db.added == []


def test_closed_queue_does_not_create_a_second_decision_log():
    db = FakeSession(queue(ModerationQueueStatus.rejected))

    result = apply(service(db), "defer")

    assert result.reason == "closed"
    assert db.added == []


def test_transaction_rolls_back_on_database_error():
    db = FakeSession(queue())
    db.commit = MagicMock(side_effect=RuntimeError("database unavailable"))

    with pytest.raises(RuntimeError, match="database unavailable"):
        apply(service(db), "approve")

    assert db.rollbacks == 1


def test_moderation_card_is_escaped_bounded_and_has_exact_buttons():
    telegram = MagicMock()
    telegram.send_html.return_value = TelegramResult(success=True, message_id=44)
    publisher = TelegramModerationPublisher(telegram, chat_id="-10011")

    result = publisher.publish(queue())

    assert result.success is True
    args, kwargs = telegram.send_html.call_args
    assert "&lt;Unsafe &amp; title&gt;" in args[0]
    assert len(args[0]) <= 4096
    buttons = kwargs["reply_markup"]["inline_keyboard"]
    assert [button["text"] for button in buttons[0]] == ["✅ Одобрить", "❌ Отклонить"]
    assert [button["text"] for button in buttons[1]] == ["⏸ Отложить", "ℹ️ Подробнее"]
    assert all(button["callback_data"].startswith("moderation:") for row in buttons for button in row)


def test_polling_acks_and_removes_keyboard_after_committed_decision_even_if_edit_fails():
    publisher = MagicMock()
    publisher.get_updates.return_value = TelegramResult(success=True, data=[{
        "update_id": 4,
        "callback_query": {
            "id": "callback-id",
            "from": {"id": 7},
            "data": "moderation:approve:11",
            "message": {"chat": {"id": -10011}, "message_id": 22},
        },
    }])
    publisher.edit_message_reply_markup.return_value = TelegramResult(success=False, error="edit failed")
    decisions = MagicMock()
    decisions.apply_decision.return_value = SimpleNamespace(applied=True, action="approve", reason=None, duplicate=False)
    polling = TelegramModerationPollingService(publisher, decisions, poll_timeout_seconds=1, batch_limit=10)

    assert polling.poll_once() is True
    publisher.answer_callback_query.assert_called_once_with("callback-id", text="Одобрено")
    publisher.edit_message_reply_markup.assert_called_once_with(-10011, 22, None)


def test_polling_ignores_personal_feedback_callbacks():
    publisher = MagicMock()
    publisher.get_updates.return_value = TelegramResult(success=True, data=[{
        "update_id": 5,
        "callback_query": {"id": "callback-id", "from": {"id": 7}, "data": "feedback:like:11"},
    }])
    decisions = MagicMock()

    assert TelegramModerationPollingService(publisher, decisions, poll_timeout_seconds=1, batch_limit=10).poll_once() is True
    decisions.apply_decision.assert_not_called()
    publisher.answer_callback_query.assert_not_called()


def test_polling_sends_details_when_requested():
    publisher = MagicMock()
    publisher.get_updates.return_value = TelegramResult(success=True, data=[{
        "update_id": 6,
        "callback_query": {
            "id": "callback-id",
            "from": {"id": 7},
            "data": "moderation:details:11",
            "message": {"chat": {"id": -10011}, "message_id": 22},
        },
    }])
    decisions = MagicMock()
    decisions.apply_decision.return_value = SimpleNamespace(
        applied=False,
        action="details",
        reason="details",
        duplicate=False,
        details={"queue_id": 11, "title": "Title", "url": "https://example.test", "summary": "Summary", "score": 8.5},
    )

    publisher.send_html.return_value = TelegramResult(success=False, error="unavailable")

    assert TelegramModerationPollingService(publisher, decisions, poll_timeout_seconds=1, batch_limit=10).poll_once() is True
    publisher.send_html.assert_called_once()
    publisher.answer_callback_query.assert_called_once_with("callback-id", text="Не удалось отправить подробности")
