import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.pipeline.url_normalizer import canonicalize_url
from app.pipeline.entity_keys import extract_entity_keys
from app.pipeline.deduplicate import (
    calculate_content_hash,
    normalize_title_for_matching,
    calculate_title_similarity
)
from app.database.models import Source, Item, ItemStatus, DuplicateRelation, RelationType, ReviewStatus
from app.services.item_service import ItemService
from app.collectors.schemas import CollectedItem

# Класс-заглушка для цепочек query().filter().order_by().limit().all()
class FakeQuery:
    def __init__(self, all_val=None, first_val=None, first_seq=None):
        self.all_val = all_val if all_val is not None else []
        self.first_val = first_val
        self.first_seq = first_seq or []
        self.first_calls = 0

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def first(self):
        if self.first_seq:
            res = self.first_seq[self.first_calls]
            self.first_calls = min(self.first_calls + 1, len(self.first_seq) - 1)
            return res
        return self.first_val

    def all(self):
        if isinstance(self.all_val, list) and len(self.all_val) > 0 and isinstance(self.all_val[0], list):
            res = self.all_val[self.first_calls]
            self.first_calls = min(self.first_calls + 1, len(self.all_val) - 1)
            return res
        return self.all_val

# 1. Тест канонизации URL
def test_url_canonicalization():
    assert canonicalize_url("  https://EXAMPLE.com:443/article/  ") == "https://example.com/article"
    assert canonicalize_url("http://example.com:80/news") == "http://example.com/news"
    assert canonicalize_url("https://example.com/article#comments") == "https://example.com/article"
    assert canonicalize_url("https://example.com/a//b/c/") == "https://example.com/a/b/c"
    # IDN
    assert canonicalize_url("https://президент.рф") == "https://xn--d1abbgf6aiiy.xn--p1ai"

# 2. Тест удаления UTM и трекинг параметров
def test_utm_removal():
    assert canonicalize_url("https://example.com/article?id=55&utm_source=telegram&fbclid=abc") == "https://example.com/article?id=55"
    assert canonicalize_url("https://example.com/?ref=123&si=xyz&spm=1.2.3") == "https://example.com"
    assert canonicalize_url("https://example.com/?b=2&a=1") == "https://example.com?a=1&b=2"

# 3. Тест доменной нормализации (GitHub, YouTube, arXiv)
def test_domain_specific_canonicalization():
    assert canonicalize_url("https://github.com/Owner/Repo/blob/main/README.md?utm_source=test") == "https://github.com/Owner/Repo/blob/main/README.md"
    
    # YouTube
    assert canonicalize_url("https://youtu.be/dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert canonicalize_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&utm_medium=social") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    
    # arXiv
    assert canonicalize_url("https://arxiv.org/pdf/2401.12345") == "https://arxiv.org/abs/2401.12345"
    assert canonicalize_url("https://arxiv.org/pdf/2401.12345.pdf") == "https://arxiv.org/abs/2401.12345"

# 4. Тест извлечения сущностей
def test_entity_extraction():
    text = (
        "Check out github.com/openai/gpt-3. There is also a Hugging Face model "
        "huggingface.co/meta-llama/Llama-2-7b. Read the paper on arxiv:2401.12345. "
        "Watch video at https://youtu.be/dQw4w9WgXcQ. The version is v1.5.0."
    )
    entities = extract_entity_keys(text)
    
    assert "openai/gpt-3" in entities["github_repositories"]
    assert "meta-llama/Llama-2-7b" in entities["huggingface_models"]
    assert "2401.12345" in entities["arxiv_ids"]
    assert "dQw4w9WgXcQ" in entities["youtube_ids"]
    assert "1.5.0" in entities["version_tokens"]

# 5. Тест стабильности хэша
def test_hash_stability():
    h1 = calculate_content_hash(
        source_id=1,
        url="https://example.com/article",
        normalized_title="article title",
        published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc),
        external_id="ext-1"
    )
    h2 = calculate_content_hash(
        source_id=1,
        url="https://example.com/article",
        normalized_title="article title",
        published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc),
        external_id="ext-1"
    )
    assert h1 == h2

# 6. Тест попарной схожести
def test_similarity_matcher():
    assert calculate_title_similarity("OpenAI GPT-5 Release Announcement", "OpenAI GPT-5 Release Announcement") == 1.0
    assert calculate_title_similarity("OpenAI GPT-5 Release Announcement", "openai gpt-5 release announcement!") == 1.0
    # Высокое сходство
    assert calculate_title_similarity("OpenAI GPT-5 Release Announcement", "GPT-5 Release Announcement by OpenAI") > 0.70

# 7. Сценарий Level 2: совпадение по external_id
def test_item_service_deduplication_levels():
    mock_db = MagicMock()
    service = ItemService(mock_db)
    source = Source(id=1, name="OpenAI Blog")
    service.item_repo = MagicMock()
    service.rel_repo = MagicMock()
    
    existing_item = Item(
        id=10,
        source_id=1,
        external_id="ext-id-123",
        canonical_url="https://openai.com/blog/gpt-4",
        title="OpenAI GPT-4 Release",
        published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc),
        metadata_json={}
    )
    
    # Имитируем, что get_by_hash возвращает None (то есть Level 1 прошел успешно)
    service.item_repo.get_by_hash.return_value = None
    
    # Настраиваем FakeQuery
    mock_db.query.return_value = FakeQuery(all_val=[], first_seq=[existing_item, None])
    
    col_items = [
        CollectedItem(
            source_name="OpenAI Blog",
            source_type="rss",
            url="https://openai.com/blog/gpt-4-new?utm_source=twitter",
            title="Some New Title",
            external_id="ext-id-123",
            published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
        )
    ]
    
    # Запускаем обработку
    stats = service.process_collected_items(source, col_items)
    
    # Должен создаться элемент
    assert stats["created"] == 1
    
    # Проверяем, что создана связь exact_external_id
    service.rel_repo.create.assert_called_once()
    new_rel = service.rel_repo.create.call_args[0][0]
    assert new_rel.relation_type == RelationType.exact_external_id
    assert new_rel.confidence == 1.0
    assert new_rel.review_status == ReviewStatus.auto_confirmed

# 8. Сценарий Level 3: совпадение по canonical_url
def test_deduplication_level_3():
    mock_db = MagicMock()
    service = ItemService(mock_db)
    source = Source(id=1, name="OpenAI Blog")
    service.item_repo = MagicMock()
    service.rel_repo = MagicMock()
    service.item_repo.get_by_hash.return_value = None
    
    existing_item = Item(
        id=15,
        source_id=1,
        external_id=None,
        canonical_url="https://openai.com/blog/gpt-4",
        title="Another Title",
        published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc),
        metadata_json={}
    )
    mock_db.query.return_value = FakeQuery(all_val=[], first_val=existing_item)
    
    col_items = [
        CollectedItem(
            source_name="OpenAI Blog",
            source_type="rss",
            url="https://openai.com/blog/gpt-4?utm_medium=email",
            title="Some New Title",
            published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
        )
    ]
    
    stats = service.process_collected_items(source, col_items)
    assert stats["created"] == 1
    
    # Проверяем связь по URL
    service.rel_repo.create.assert_called_once()
    new_rel = service.rel_repo.create.call_args[0][0]
    assert new_rel.relation_type == RelationType.exact_canonical_url

# 9. Сценарий Level 4 & 5: совпадение по заголовку
def test_deduplication_level_4_5():
    mock_db = MagicMock()
    service = ItemService(mock_db)
    source = Source(id=1, name="OpenAI Blog")
    service.item_repo = MagicMock()
    service.rel_repo = MagicMock()
    service.item_repo.get_by_hash.return_value = None
    
    existing_item = Item(
        id=20,
        source_id=1,
        external_id=None,
        canonical_url="https://openai.com/blog/gpt-4-original",
        title="OpenAI releases GPT-4 for all users!",
        published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc),
        metadata_json={}
    )
    mock_db.query.return_value = FakeQuery(all_val=[existing_item], first_val=None)
    
    col_items = [
        CollectedItem(
            source_name="OpenAI Blog",
            source_type="rss",
            url="https://openai.com/blog/gpt-4-repost",
            title="OpenAI releases GPT-4 for all users!",
            published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
        )
    ]
    
    stats = service.process_collected_items(source, col_items)
    assert stats["created"] == 1
    
    # Создана связь same_source_title
    new_rel = service.rel_repo.create.call_args[0][0]
    assert new_rel.relation_type == RelationType.same_source_title

# 10. Сценарий Cross-Source Story
def test_cross_source_story():
    mock_db = MagicMock()
    service = ItemService(mock_db)
    source = Source(id=1, name="OpenAI Blog")
    service.item_repo = MagicMock()
    service.rel_repo = MagicMock()
    service.item_repo.get_by_hash.return_value = None
    
    existing_item = Item(
        id=30,
        source_id=2,
        external_id=None,
        canonical_url="https://habr.com/ru/post/123",
        title="OpenAI анонсировала GPT-4o",
        published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc),
        metadata_json={"entity_keys": {"github_repositories": ["openai/gpt-4o"]}}
    )
    mock_db.query.return_value = FakeQuery(all_val=[[], [existing_item]], first_val=None)
    
    col_items = [
        CollectedItem(
            source_name="OpenAI Blog",
            source_type="rss",
            url="https://openai.com/blog/gpt-4o-launch",
            title="GPT-4o launched by OpenAI",
            published_at=datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
        )
    ]
    
    with patch("app.services.item_service.extract_entity_keys") as mock_extract:
        mock_extract.return_value = {"github_repositories": ["openai/gpt-4o"]}
        
        stats = service.process_collected_items(source, col_items)
        assert stats["created"] == 1
        
        new_rel = service.rel_repo.create.call_args[0][0]
        assert new_rel.relation_type == RelationType.cross_source_story
