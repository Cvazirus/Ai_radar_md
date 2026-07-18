from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.database.models import Publication
from app.services.feedback_service import FeedbackService
from app.services.personal_ranking_service import PersonalRankingService
from app.services.telegram_feedback_polling_service import TelegramFeedbackPollingService
from app.publishers.telegram import TelegramResult


class FeedbackRepositoryStub:
    def __init__(self):
        self.rows = {}

    def get(self, user_id, publication_id):
        return self.rows.get((user_id, publication_id))

    def save(self, feedback):
        self.rows[(feedback.telegram_user_id, feedback.publication_id)] = feedback
        return feedback

    def list_for_user(self, user_id):
        return [row for (stored_user_id, _), row in self.rows.items() if stored_user_id == user_id]

    def list_favorites(self, user_id, limit=100):
        return [row for row in self.list_for_user(user_id) if row.is_favorite][:limit]


class ReceiptRepositoryStub:
    def __init__(self):
        self.rows = {}

    def get(self, update_id):
        return self.rows.get(update_id)

    def create(self, update_id, telegram_user_id=None, publication_id=None):
        receipt = SimpleNamespace(update_id=update_id, telegram_user_id=telegram_user_id, publication_id=publication_id)
        self.rows[update_id] = receipt
        return receipt


def make_feedback_service():
    db = MagicMock()
    feedback_repo = FeedbackRepositoryStub()
    receipt_repo = ReceiptRepositoryStub()
    service = FeedbackService(
        db,
        enabled=True,
        allowed_user_ids="7",
        feedback_repository=feedback_repo,
        receipt_repository=receipt_repo,
    )
    publication = Publication(item_id=11, telegram_text="text", telegram_chat_id=-10011, telegram_message_id=22)
    service._get_publication = MagicMock(return_value=publication)
    service._recalculate_preferences = MagicMock()
    return service, db, feedback_repo, receipt_repo


def apply(service, action, update_id, **kwargs):
    return service.apply_feedback(
        update_id=update_id,
        telegram_user_id=7,
        callback_data=f"feedback:{action}:11",
        chat_id=-10011,
        message_id=22,
        **kwargs,
    )


def test_like_dislike_replaces_reaction_and_duplicate_has_no_second_effect():
    service, _, feedback_repo, receipt_repo = make_feedback_service()

    assert apply(service, "like", 1).applied is True
    assert feedback_repo.get(7, 11).reaction == "like"
    assert apply(service, "dislike", 2).applied is True
    assert feedback_repo.get(7, 11).reaction == "dislike"
    duplicate = apply(service, "like", 2)

    assert duplicate.duplicate is True
    assert feedback_repo.get(7, 11).reaction == "dislike"
    assert len(receipt_repo.rows) == 2


def test_favorite_toggles_and_hide_is_one_way():
    service, _, feedback_repo, _ = make_feedback_service()

    apply(service, "favorite", 1)
    assert feedback_repo.get(7, 11).is_favorite is True
    apply(service, "favorite", 2)
    assert feedback_repo.get(7, 11).is_favorite is False
    apply(service, "hide", 3)
    apply(service, "hide", 4)
    assert feedback_repo.get(7, 11).is_hidden is True


@pytest.mark.parametrize("callback", ["feedback:unknown:11", "feedback:like:0", "feedback:like:11:x", "other:like:11"])
def test_invalid_callback_does_not_write(callback):
    service, db, _, receipt_repo = make_feedback_service()

    result = service.apply_feedback(1, 7, callback, -10011, 22)

    assert result.applied is False
    assert result.reason == "invalid_callback"
    assert not receipt_repo.rows
    db.commit.assert_not_called()


def test_unknown_publication_and_unauthorized_user_do_not_write():
    service, db, _, receipt_repo = make_feedback_service()
    service._get_publication.return_value = None

    assert apply(service, "like", 1).reason == "publication_not_found"
    unauthorized = service.apply_feedback(2, 99, "feedback:like:11", -10011, 22)

    assert unauthorized.reason == "unauthorized"
    assert not receipt_repo.rows
    db.commit.assert_not_called()


def test_transaction_rolls_back_when_persistence_fails():
    service, db, _, _ = make_feedback_service()
    db.commit.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        apply(service, "like", 1)

    db.rollback.assert_called_once()


def test_preference_recalculation_tracks_counts_and_clamps_weight():
    service, _, feedback_repo, _ = make_feedback_service()
    preferences = MagicMock()
    service.preference_repository = preferences
    service._preference_keys = MagicMock(return_value={"topic": ["agent"]})
    for publication_id in range(1, 6):
        feedback_repo.rows[(7, publication_id)] = SimpleNamespace(
            telegram_user_id=7,
            publication_id=publication_id,
            reaction="like",
            is_favorite=True,
            is_hidden=False,
        )
    feedback_repo.rows[(7, 99)] = SimpleNamespace(
        telegram_user_id=7,
        publication_id=99,
        reaction="dislike",
        is_favorite=False,
        is_hidden=True,
    )

    FeedbackService._recalculate_preferences(service, 7)

    saved = preferences.replace_for_user.call_args.args[1]
    topic = next(preference for preference in saved if preference.preference_key == "agent")
    assert topic.weight == 10
    assert topic.positive_count == 10
    assert topic.negative_count == 2


def test_preference_aggregation_and_ranking_clamps_contributions():
    preferences = [
        SimpleNamespace(preference_type="topic", preference_key="agent", weight=10, positive_count=3, negative_count=0),
        SimpleNamespace(preference_type="source", preference_key="example", weight=-10, positive_count=0, negative_count=3),
        SimpleNamespace(preference_type="entity", preference_key="openai", weight=10, positive_count=3, negative_count=0),
    ]
    repository = MagicMock()
    repository.list_for_user.return_value = preferences
    ranking = PersonalRankingService(repository)

    result = ranking.rank(
        telegram_user_id=7,
        base_score=8.0,
        topic="agent",
        source="example",
        entities={"companies": ["OpenAI"]},
        content_type="rss",
    )

    assert result.personal_score == 3.0
    assert result.final_score == 11.0
    assert {entry.preference_key for entry in result.breakdown} == {"agent", "example", "openai"}
    assert all(-3 <= entry.contribution <= 3 for entry in result.breakdown)


def test_polling_acknowledges_personal_hide_without_deleting_channel_post():
    publisher = MagicMock()
    publisher.get_updates.return_value = TelegramResult(success=True, data=[{
        "update_id": 4,
        "callback_query": {
            "id": "callback-id",
            "from": {"id": 7},
            "data": "feedback:hide:11",
            "message": {"chat": {"id": -10011}, "message_id": 22},
        },
    }])
    feedback = MagicMock()
    feedback.apply_feedback.return_value = SimpleNamespace(applied=True, action="hide", reason=None)
    polling = TelegramFeedbackPollingService(publisher, feedback, poll_timeout_seconds=1, batch_limit=10)

    assert polling.poll_once() is True
    feedback.apply_feedback.assert_called_once()
    publisher.answer_callback_query.assert_called_once_with("callback-id", text="Сохранено")
    publisher.delete_message.assert_not_called()


def test_polling_does_not_delete_for_rejected_callback_or_api_error():
    publisher = MagicMock()
    publisher.get_updates.return_value = TelegramResult(success=False, error="temporary error")
    feedback = MagicMock()
    polling = TelegramFeedbackPollingService(publisher, feedback, poll_timeout_seconds=1, batch_limit=10)

    assert polling.poll_once() is False
    feedback.apply_feedback.assert_not_called()
    publisher.delete_message.assert_not_called()
