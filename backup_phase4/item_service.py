from typing import List, Dict
import structlog
from sqlalchemy.orm import Session
from app.database.models import Source, Item, ItemStatus
from app.database.repositories import ItemRepository
from app.collectors.schemas import CollectedItem
from app.pipeline.normalize import (
    normalize_title,
    normalize_text,
    normalize_author,
    normalize_published_at,
    normalize_language
)
from app.pipeline.deduplicate import calculate_content_hash

logger = structlog.get_logger()

class ItemService:
    def __init__(self, db: Session):
        self.db = db
        self.item_repo = ItemRepository(db)

    def process_collected_items(self, source: Source, collected_items: List[CollectedItem]) -> Dict[str, int]:
        stats = {"found": len(collected_items), "created": 0, "skipped": 0, "failed": 0}
        
        for col_item in collected_items:
            try:
                # 1. Нормализация полей
                norm_title = normalize_title(col_item.title)
                norm_text = normalize_text(col_item.text)
                norm_author = normalize_author(col_item.author)
                norm_published_at = normalize_published_at(col_item.published_at)
                norm_lang = normalize_language(norm_text or norm_title)
                
                # 2. Вычисление content_hash
                content_hash = calculate_content_hash(
                    source_id=source.id,
                    url=col_item.url,
                    normalized_title=norm_title,
                    published_at=norm_published_at,
                    external_id=col_item.external_id
                )
                
                # 3. Проверка дубликатов по хэшу
                existing = self.item_repo.get_by_hash(content_hash)
                if existing:
                    stats["skipped"] += 1
                    logger.info(
                        "rss_item_skipped",
                        source_name=source.name,
                        title=norm_title,
                        url=col_item.url,
                        reason="duplicate_content_hash"
                    )
                    continue

                # 4. Создание ORM Item
                new_item = Item(
                    source_id=source.id,
                    external_id=col_item.external_id,
                    url=col_item.url,
                    canonical_url=col_item.url,  # На этом этапе canonical_url = url
                    title=norm_title,
                    author=norm_author,
                    raw_text=norm_text,
                    published_at=norm_published_at,
                    content_hash=content_hash,
                    language=norm_lang,
                    status=ItemStatus.collected,
                    metadata_json=col_item.metadata
                )
                
                self.item_repo.create(new_item)
                stats["created"] += 1
                logger.info(
                    "rss_item_saved",
                    source_name=source.name,
                    title=norm_title,
                    url=col_item.url,
                    item_id=new_item.id
                )
                
            except Exception as e:
                stats["failed"] += 1
                logger.error(
                    "rss_item_processing_failed",
                    source_name=source.name,
                    url=col_item.url,
                    error=str(e)
                )
                
        return stats
