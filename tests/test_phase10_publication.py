import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.database.models import Item, ItemStatus, ItemAnalysis, AnalysisStatus, Publication, PublicationStatus, ModerationQueue, ModerationQueueStatus, CategoryEnum
from app.services.publication_service import PublicationService


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
    assert "📢 *New Model Release*" in text
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


def test_publication_failure_and_retry(service, mock_db):
    item = Item(id=1, title="Test Item (simulate_failure)", url="https://example.com", status=ItemStatus.approved)
    
    service.get_approved_items = MagicMock(return_value=[item])
    service.pub_repo.get = MagicMock(return_value=None)
    
    stats = service.publish_batch()
    assert stats["processed"] == 0
    assert stats["failed"] == 1
    
    failed_pub = Publication(item_id=1, telegram_text="simulate_failure", status=PublicationStatus.failed)
    mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = [failed_pub]
    
    failed_pub.telegram_text = "clean text"
    
    stats_retry = service.publish_batch(retry_failed=True)
    assert stats_retry["resumed"] == 1
    assert stats_retry["processed"] == 1


def test_resume_drafts(service, mock_db):
    pub = Publication(item_id=1, telegram_text="Test", status=PublicationStatus.draft)
    mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = [pub]
    
    stats = service.publish_batch(resume=True)
    assert stats["resumed"] == 1
    assert stats["processed"] == 1
    assert pub.status == PublicationStatus.published


def test_item_id_and_limit_filters(service, mock_db):
    item1 = Item(id=1, title="Item 1", status=ItemStatus.approved)
    item2 = Item(id=2, title="Item 2", status=ItemStatus.approved)
    
    service.get_approved_items = MagicMock(return_value=[item1, item2])
    service.pub_repo.get = MagicMock(return_value=None)
    
    stats_limit = service.publish_batch(limit=1)
    assert stats_limit["processed"] == 1
    
    stats_id = service.publish_batch(item_id=2)
    assert stats_id["processed"] == 1
