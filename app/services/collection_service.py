from typing import Optional
from datetime import datetime, timezone
import structlog
from sqlalchemy.orm import Session
from app.database.models import Source, CollectionRun, Item
from app.database.repositories import CollectionRunRepository
from app.collectors.rss import RSSCollector
from app.services.item_service import ItemService

logger = structlog.get_logger()

class CollectionService:
    def __init__(self, db: Session):
        self.db = db
        self.run_repo = CollectionRunRepository(db)
        self.item_service = ItemService(db)

    def run_rss_collection(self, only_source_name: Optional[str] = None) -> dict:
        # 1. Получаем активные RSS источники
        query = self.db.query(Source).filter(
            Source.source_type == "rss",
            Source.enabled == True
        )
        if only_source_name:
            query = query.filter(Source.name == only_source_name)
        sources = query.all()
        
        total_stats = {
            "sources_total": len(sources),
            "sources_success": 0,
            "sources_failed": 0,
            "items_found": 0,
            "items_created": 0,
            "items_skipped": 0
        }
        
        logger.info("rss_global_collection_started", sources_count=len(sources))
        
        for source in sources:
            config = source.config or {}
            feed_url = config.get("feed_url")
            timeout = config.get("timeout_seconds", 20)
            
            if not feed_url:
                logger.warn(
                    "rss_source_skipped_no_feed_url",
                    source_name=source.name,
                    source_id=source.id
                )
                total_stats["sources_failed"] += 1
                continue

            # Создаем лог запуска (CollectionRun) в БД
            run = CollectionRun(
                collector_name=f"rss_{source.name}",
                started_at=datetime.now(timezone.utc),
                status="running",
                items_found=0,
                items_created=0,
                items_skipped=0
            )
            self.run_repo.create(run)
            
            try:
                # Инициализируем коллектор
                collector = RSSCollector(
                    source_name=source.name,
                    feed_url=feed_url,
                    timeout_seconds=timeout
                )
                
                # Сбор элементов
                collected_items = collector.collect()
                
                # Ограничиваем количество записей
                items_count = self.db.query(Item).filter(Item.source_id == source.id).count()
                if items_count == 0:
                    limit = config.get("initial_import_limit") or config.get("max_items_per_run") or 100
                else:
                    limit = config.get("max_items_per_run") or 50
                    
                collected_items = collected_items[:limit]
                
                # Сохранение в БД с дедупликацией
                item_stats = self.item_service.process_collected_items(source, collected_items)
                
                # Обновляем CollectionRun
                run.finished_at = datetime.now(timezone.utc)
                run.status = "success"
                run.items_found = item_stats["found"]
                run.items_created = item_stats["created"]
                run.items_skipped = item_stats["skipped"]
                self.run_repo.update(run)
                
                # Обновляем общую статистику
                total_stats["sources_success"] += 1
                total_stats["items_found"] += item_stats["found"]
                total_stats["items_created"] += item_stats["created"]
                total_stats["items_skipped"] += item_stats["skipped"]
                
                # Обновляем дату последней проверки
                source.last_checked_at = datetime.now(timezone.utc)
                self.db.add(source)
                self.db.commit()
                
            except Exception as e:
                # Фиксируем ошибку, но продолжаем сбор по остальным источникам!
                logger.error(
                    "rss_source_collection_failed",
                    source_name=source.name,
                    feed_url=feed_url,
                    error=str(e)
                )
                
                run.finished_at = datetime.now(timezone.utc)
                run.status = "failed"
                run.error_message = str(e)
                self.run_repo.update(run)
                
                total_stats["sources_failed"] += 1
                
        logger.info("rss_global_collection_finished", stats=total_stats)
        return total_stats
