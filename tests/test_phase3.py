import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import httpx
from pydantic import ValidationError

from app.collectors.schemas import CollectedItem
from app.collectors.rss import RSSCollector
from app.pipeline.normalize import (
    normalize_title,
    normalize_text,
    normalize_author,
    normalize_published_at,
    normalize_language
)
from app.pipeline.deduplicate import calculate_content_hash
from app.services.item_service import ItemService
from app.services.collection_service import CollectionService
from app.database.models import Source, Item, CollectionRun

# 1. Валидация CollectedItem
def test_collected_item_validation():
    # Валидный объект
    item = CollectedItem(
        source_name="Test Source",
        source_type="rss",
        external_id="123",
        url="https://example.com/post",
        title="Test Post",
        author="John Doe",
        text="Hello world",
        published_at=datetime(2026, 7, 16, 12, 0, 0),
        metadata={"tags": ["AI"]}
    )
    assert item.source_name == "Test Source"
    assert item.published_at.tzinfo == timezone.utc # Валидатор сделал timezone-aware

    # Невалидные данные (пустой url)
    with pytest.raises(ValidationError):
        CollectedItem(source_name="Test", source_type="rss", url="", title="Test Title")

    # Невалидные данные (пустой title)
    with pytest.raises(ValidationError):
        CollectedItem(source_name="Test", source_type="rss", url="http://test.com", title="  ")

# 2. Разбор RSS
@patch("httpx.Client")
def test_rss_parse(mock_client):
    rss_xml = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
        <channel>
            <title>Test RSS Feed</title>
            <link>https://example.com</link>
            <item>
                <title>Test RSS Item</title>
                <link>https://example.com/item1</link>
                <guid>item1-guid</guid>
                <pubDate>Thu, 16 Jul 2026 12:00:00 GMT</pubDate>
                <description>RSS Summary</description>
            </item>
        </channel>
    </rss>"""
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = rss_xml.encode("utf-8")
    mock_resp.text = rss_xml
    
    mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
    
    collector = RSSCollector("Test RSS", "https://example.com/feed.xml")
    items = collector.collect()
    
    assert len(items) == 1
    assert items[0].title == "Test RSS Item"
    assert items[0].url == "https://example.com/item1"
    assert items[0].external_id == "item1-guid"
    assert items[0].text == "RSS Summary"
    assert items[0].published_at is not None

# 3. Разбор Atom
@patch("httpx.Client")
def test_atom_parse(mock_client):
    atom_xml = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
        <title>Test Atom Feed</title>
        <link href="https://example.com"/>
        <entry>
            <title>Test Atom Item</title>
            <link href="https://example.com/entry1"/>
            <id>atom1-id</id>
            <updated>2026-07-16T12:00:00Z</updated>
            <content type="html">Atom Content</content>
        </entry>
    </feed>"""
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = atom_xml.encode("utf-8")
    mock_resp.text = atom_xml
    
    mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
    
    collector = RSSCollector("Test Atom", "https://example.com/atom.xml")
    items = collector.collect()
    
    assert len(items) == 1
    assert items[0].title == "Test Atom Item"
    assert items[0].url == "https://example.com/entry1"
    assert items[0].external_id == "atom1-id"
    assert items[0].text == "Atom Content"

# 4. Пустая лента
@patch("httpx.Client")
def test_empty_feed(mock_client):
    empty_xml = """<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel></channel></rss>"""
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = empty_xml.encode("utf-8")
    mock_resp.text = empty_xml
    
    mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
    
    collector = RSSCollector("Test Empty", "https://example.com/empty.xml")
    items = collector.collect()
    assert len(items) == 0

# 5. Невалидная XML-лента
@patch("httpx.Client")
def test_invalid_xml_feed(mock_client):
    invalid_xml = """This is not XML! <malformed>"""
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = invalid_xml.encode("utf-8")
    mock_resp.text = invalid_xml
    
    mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
    
    collector = RSSCollector("Test Malformed", "https://example.com/bad.xml")
    # feedparser должен сгладить невалидный XML или вернуть 0 записей без краша
    items = collector.collect()
    assert isinstance(items, list)

# 6. Timeout (ошибка соединения)
@patch("httpx.Client")
def test_feed_timeout(mock_client):
    mock_client.return_value.__enter__.return_value.get.side_effect = httpx.ConnectTimeout("Timeout connecting")
    
    collector = RSSCollector("Test Timeout", "https://example.com/timeout.xml")
    
    with pytest.raises(httpx.ConnectTimeout):
        collector.collect()

# 7. HTTP 500
@patch("httpx.Client")
def test_feed_http_500(mock_client):
    # Симулируем 3 попытки, возвращающие 500
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    
    mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
    
    collector = RSSCollector("Test 500", "https://example.com/500.xml", timeout_seconds=1)
    
    # Чтобы тесты не висели из-за sleep, временно подменим time.sleep
    with patch("time.sleep") as mock_sleep:
        with pytest.raises(httpx.HTTPStatusError):
            collector.collect()
        assert mock_sleep.call_count == 2

# 8. Нормализация заголовка
def test_normalize_title():
    assert normalize_title("  Test &amp; Title  ") == "Test & Title"
    assert normalize_title("Title with <b>HTML</b>") == "Title with HTML"
    assert normalize_title(None) == ""

# 9. Нормализация HTML-текста
def test_normalize_text():
    html_input = "Hello <script>alert(1)</script>World! <p>This is <i>text</i>.</p>"
    assert normalize_text(html_input) == "Hello World! This is text ."
    assert normalize_text("   ") is None
    assert normalize_text(None) is None

# 10. Разбор даты
def test_normalize_published_at():
    naive_dt = datetime(2026, 7, 16, 12, 0, 0)
    aware_dt = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    
    assert normalize_published_at(naive_dt) == aware_dt
    assert normalize_published_at(aware_dt) == aware_dt
    assert normalize_published_at(None) is None

# 11. Стабильность content_hash
def test_content_hash_stability():
    h1 = calculate_content_hash(
        source_id=1,
        url="http://test.com",
        normalized_title="Title Test",
        published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc),
        external_id="ext-1"
    )
    
    h2 = calculate_content_hash(
        source_id=1,
        url="http://test.com",
        normalized_title="Title Test",
        published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc),
        external_id="ext-1"
    )
    
    assert h1 == h2
    assert len(h1) == 64

# 12. Повторное сохранение одной записи (дедупликация)
def test_duplicate_item_saving():
    mock_db = MagicMock()
    mock_repo = MagicMock()
    
    item_service = ItemService(mock_db)
    item_service.item_repo = mock_repo
    
    # Имитируем, что запись уже есть в базе
    mock_repo.get_by_hash.return_value = MagicMock(spec=Item)
    
    source = MagicMock(spec=Source)
    source.id = 1
    source.name = "Test Source"
    
    col_items = [
        CollectedItem(
            source_name="Test Source",
            source_type="rss",
            url="https://test.com/post1",
            title="Post 1",
            content_hash="hash1"
        )
    ]
    
    stats = item_service.process_collected_items(source, col_items)
    
    assert stats["skipped"] == 1
    assert stats["created"] == 0
    assert mock_repo.create.call_count == 0

# 13-17. Ошибки источников, collection_runs status
def test_collection_service_orchestration():
    mock_db = MagicMock()
    
    # 2 источника: 1-й работает, 2-й падает с ошибкой
    source1 = Source(id=1, name="Source 1", source_type="rss", enabled=True, config={"feed_url": "http://s1.xml"})
    source2 = Source(id=2, name="Source 2", source_type="rss", enabled=True, config={"feed_url": "http://s2.xml"})
    
    mock_db.query.return_value.filter.return_value.all.return_value = [source1, source2]
    
    service = CollectionService(mock_db)
    
    # Мокаем репозиторий CollectionRun и ItemService
    service.run_repo = MagicMock()
    service.item_service = MagicMock()
    
    # Патчим метод collect коллектора
    with patch.object(RSSCollector, "collect") as mock_collect:
        # 1-й коллектор отдает 1 запись, 2-й бросает ошибку
        mock_collect.side_effect = [
            [CollectedItem(source_name="Source 1", source_type="rss", url="http://url", title="Title")],
            Exception("Connection reset by peer")
        ]
        
        service.item_service.process_collected_items.return_value = {
            "found": 1, "created": 1, "skipped": 0, "failed": 0
        }
        
        stats = service.run_rss_collection()
        
        # Проверяем, что сбор продолжился при падении 2-го источника
        assert stats["sources_total"] == 2
        assert stats["sources_success"] == 1
        assert stats["sources_failed"] == 1
        assert stats["items_created"] == 1
        
        # Проверяем, что были сделаны записи в CollectionRun с правильными статусами
        created_runs = service.run_repo.create.call_args_list
        assert len(created_runs) == 2
        
        # Проверяем обновления статусов
        updated_runs = service.run_repo.update.call_args_list
        assert len(updated_runs) == 2
        
        run_1_final = updated_runs[0][0][0]
        assert run_1_final.status == "success"
        
        run_2_final = updated_runs[1][0][0]
        assert run_2_final.status == "failed"
        assert "Connection reset by peer" in run_2_final.error_message
