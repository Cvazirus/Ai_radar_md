import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, Mock

from app.database.models import Item, ItemStatus, ItemAnalysis, AnalysisStatus, Publication, PublicationStatus, ModerationQueue, ModerationQueueStatus, CategoryEnum
from app.services.publication_service import PublicationService
from app.publishers.telegram import TelegramResult


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def service(mock_db):
    return PublicationService(mock_db)


def test_get_approved_items(service, mock_db):
    item1 = Item(id=1, title="Item 1", status=ItemStatus.approved)
    item2 = Item(id=2, title="Item 2", status=ItemStatus.collected)

    mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = [item1]

    approved = service.get_approved_items()
    assert len(approved) == 1
    assert approved[0].id == 1


def test_format_telegram_text(service, mock_db):
    item = Item(id=1, title="New Model Release", url="https://example.com/model")
    analysis = ItemAnalysis(
        item_id=1,
        status=AnalysisStatus.success,
        total_score=8.5,
        summary_ru="Новый релиз модели ИИ.",
        category=CategoryEnum.model_release
    )

    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = analysis

    text = service.format_telegram_text(item)
    assert "📢 <b>New Model Release</b>" in text
    assert "Новый релиз модели ИИ." in text
    assert "model_release" in text
    assert "8.50/10" in text


def test_prepare_publication(service, mock_db):
    item = Item(id=1, title="Test Item", url="https://example.com")

    service.pub_repo.get = MagicMock(return_value=None)

    pub = service.prepare_publication(item)
    assert pub.item_id == 1
    assert pub.status == PublicationStatus.draft
    assert "Test Item" in pub.telegram_text


def test_dry_run(service, mock_db):
    item = Item(id=1, title="Test Item", url="https://example.com", status=ItemStatus.approved)

    service.get_approved_items = MagicMock(return_value=[item])
    service.pub_repo.get = MagicMock(return_value=None)

    stats = service.publish_batch(dry_run=True)
    assert stats["processed"] == 1
    assert mock_db.commit.call_count == 0


@patch("app.publishers.telegram.TelegramPublisher")
def test_publication_failure_and_retry(MockTelegramPublisher, service, mock_db):
    mock_publisher = Mock()
    MockTelegramPublisher.return_value = mock_publisher
    mock_publisher.send_html.return_value = TelegramResult(success=False, error="Failed", error_code=400)

    item = Item(id=1, title="Test Item", url="https://example.com", status=ItemStatus.approved)

    service.get_approved_items = MagicMock(return_value=[item])
    service.pub_repo.get = MagicMock(return_value=None)

    stats = service.publish_batch()
    assert stats["processed"] == 0
    assert stats["failed"] == 1

    mock_publisher.send_html.return_value = TelegramResult(success=True, message_id=42)

    failed_pub = Publication(item_id=1, telegram_text="clean text", status=PublicationStatus.failed)
    mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = [failed_pub]

    stats_retry = service.publish_batch(retry_failed=True)
    assert stats_retry["resumed"] == 1
    assert stats_retry["processed"] == 1


@patch("app.publishers.telegram.TelegramPublisher")
def test_resume_drafts(MockTelegramPublisher, service, mock_db):
    mock_publisher = Mock()
    MockTelegramPublisher.return_value = mock_publisher
    mock_publisher.send_html.return_value = TelegramResult(success=True, message_id=100)

    pub = Publication(item_id=1, telegram_text="Test", status=PublicationStatus.draft)
    mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = [pub]

    stats = service.publish_batch(resume=True)
    assert stats["resumed"] == 1
    assert stats["processed"] == 1
    assert pub.status == PublicationStatus.published
    assert pub.telegram_message_id == 100


@patch("app.publishers.telegram.TelegramPublisher")
def test_item_id_and_limit_filters(MockTelegramPublisher, service, mock_db):
    mock_publisher = Mock()
    MockTelegramPublisher.return_value = mock_publisher
    mock_publisher.send_html.return_value = TelegramResult(success=True, message_id=1)

    item1 = Item(id=1, title="Item 1", status=ItemStatus.approved)
    item2 = Item(id=2, title="Item 2", status=ItemStatus.approved)

    service.get_approved_items = MagicMock(return_value=[item1, item2])
    service.pub_repo.get = MagicMock(return_value=None)

    stats_limit = service.publish_batch(limit=1)
    assert stats_limit["processed"] == 1

    stats_id = service.publish_batch(item_id=2)
    assert stats_id["processed"] == 1


@patch("app.publishers.telegram.TelegramPublisher")
def test_publication_sends_feedback_keyboard_and_persists_canonical_chat(MockTelegramPublisher, service, mock_db):
    publisher = Mock()
    publisher.chat_id = "-1009876543210"
    publisher.send_html.return_value = TelegramResult(success=True, message_id=55)
    MockTelegramPublisher.return_value = publisher
    service.item_repo.get = MagicMock(return_value=None)
    publication = Publication(item_id=7, telegram_text="<b>text</b>", status=PublicationStatus.ready)

    assert service.publish_publication(publication) is True

    markup = publisher.send_html.call_args.kwargs["reply_markup"]
    buttons = [button for row in markup["inline_keyboard"] for button in row]
    assert [button["text"] for button in buttons] == ["👍 Нравится", "👎 Неинтересно", "⭐ Избранное", "🗑 Скрыть"]
    assert [button["callback_data"] for button in buttons] == [
        "feedback:like:7", "feedback:dislike:7", "feedback:favorite:7", "feedback:hide:7",
    ]
    assert publication.telegram_channel_id is None
    assert publication.telegram_chat_id == -1009876543210
    assert publication.telegram_message_id == 55


# === P1-1 AUDIT FIX: bounded, backoff-aware automatic retry of failed publications ===

@patch("app.publishers.telegram.TelegramPublisher")
def test_publish_publication_increments_retry_count_on_failure(MockTelegramPublisher, service, mock_db):
    mock_publisher = Mock()
    MockTelegramPublisher.return_value = mock_publisher
    mock_publisher.send_html.return_value = TelegramResult(success=False, error="Failed", error_code=400)

    pub = Publication(item_id=1, telegram_text="text", status=PublicationStatus.ready, retry_count=0)

    assert service.publish_publication(pub) is False
    assert pub.retry_count == 1

    assert service.publish_publication(pub) is False
    assert pub.retry_count == 2


def test_retry_failed_applies_max_retries_filter(service, mock_db):
    # Regression (P1-1 audit): retry_failed used to have no cap at all. Verify the
    # query actually gets a "retry_count < max_retries" predicate, not just that
    # some publications come back -- a mocked chain can't otherwise distinguish a
    # real filter from a no-op.
    pub = Publication(item_id=1, telegram_text="a", status=PublicationStatus.failed, retry_count=1)
    second_filter = mock_db.query.return_value.filter.return_value.filter
    second_filter.return_value.limit.return_value.all.return_value = [pub]

    stats = service.publish_batch(retry_failed=True, max_retries=3)

    assert stats["resumed"] == 1
    applied_str = " ".join(str(a) for a in second_filter.call_args.args)
    assert "retry_count" in applied_str


def test_retry_failed_applies_backoff_filter(service, mock_db):
    # Regression (P1-1 audit): retry_failed used to retry on every scheduler tick
    # with no backoff. Verify the query gets an "updated_at <= cutoff" predicate.
    pub = Publication(item_id=1, telegram_text="a", status=PublicationStatus.failed, retry_count=0)
    second_filter = mock_db.query.return_value.filter.return_value.filter
    second_filter.return_value.limit.return_value.all.return_value = [pub]

    stats = service.publish_batch(retry_failed=True, retry_backoff_minutes=15)

    assert stats["resumed"] == 1
    applied_str = " ".join(str(a) for a in second_filter.call_args.args)
    assert "updated_at" in applied_str
