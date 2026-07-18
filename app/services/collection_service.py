from typing import Optional
from datetime import datetime, timezone
import structlog
from sqlalchemy.orm import Session
from app.database.models import Source, CollectionRun, Item
from app.database.repositories import CollectionRunRepository
from app.collectors.base import BaseCollector
from app.collectors.rss import RSSCollector
from app.collectors.github import GithubCollector
from app.collectors.arxiv import ArxivCollector
from app.collectors.huggingface import HuggingFaceCollector
from app.collectors.web import WebCollector
from app.services.item_service import ItemService

logger = structlog.get_logger()

SUPPORTED_SOURCE_TYPES = ("rss", "github", "arxiv", "huggingface", "web")


class CollectionService:
    def __init__(self, db: Session):
        self.db = db
        self.run_repo = CollectionRunRepository(db)
        self.item_service = ItemService(db)

    def _build_collector(self, source: Source) -> Optional[BaseCollector]:
        """Собрать инстанс коллектора под тип источника на основе source.config.
        Возвращает None и пишет warning, если конфиг источника неполный."""
        config = source.config or {}
        timeout = config.get("timeout_seconds", 20)

        if source.source_type == "rss":
            feed_url = config.get("feed_url")
            if not feed_url:
                logger.warn("source_skipped_no_feed_url", source_name=source.name, source_id=source.id)
                return None
            return RSSCollector(source_name=source.name, feed_url=feed_url, timeout_seconds=timeout)

        if source.source_type == "github":
            query = config.get("query")
            if not query:
                logger.warn("source_skipped_no_query", source_name=source.name, source_id=source.id)
                return None
            return GithubCollector(
                source_name=source.name,
                query=query,
                per_page=config.get("per_page", 20),
                sort=config.get("sort", "stars"),
                order=config.get("order", "desc"),
                token=config.get("token"),
                timeout_seconds=timeout,
            )

        if source.source_type == "arxiv":
            query = config.get("query")
            if not query:
                logger.warn("source_skipped_no_query", source_name=source.name, source_id=source.id)
                return None
            return ArxivCollector(
                source_name=source.name,
                query=query,
                max_results=config.get("max_results", 30),
                timeout_seconds=timeout,
            )

        if source.source_type == "huggingface":
            return HuggingFaceCollector(
                source_name=source.name,
                sort=config.get("sort", "createdAt"),
                direction=config.get("direction", -1),
                limit=config.get("limit", 20),
                search=config.get("search"),
                timeout_seconds=timeout,
            )

        if source.source_type == "web":
            listing_url = config.get("url")
            if not listing_url:
                logger.warn("source_skipped_no_url", source_name=source.name, source_id=source.id)
                return None
            return WebCollector(
                source_name=source.name,
                listing_url=listing_url,
                link_selector=config.get("link_selector", "a"),
                link_pattern=config.get("link_pattern"),
                max_items=config.get("max_items", 15),
                timeout_seconds=timeout,
            )

        logger.warn("source_skipped_unsupported_type", source_name=source.name, source_type=source.source_type)
        return None

    def run_collection(self, only_source_name: Optional[str] = None, source_type: Optional[str] = None) -> dict:
        """Прогнать сбор по всем активным источникам (либо только по одному
        типу/имени, если указаны фильтры)."""
        conditions = [Source.enabled == True]
        if source_type:
            conditions.append(Source.source_type == source_type)
        else:
            conditions.append(Source.source_type.in_(SUPPORTED_SOURCE_TYPES))
        if only_source_name:
            conditions.append(Source.name == only_source_name)

        sources = self.db.query(Source).filter(*conditions).all()

        total_stats = {
            "sources_total": len(sources),
            "sources_success": 0,
            "sources_failed": 0,
            "items_found": 0,
            "items_created": 0,
            "items_skipped": 0
        }

        logger.info("global_collection_started", sources_count=len(sources), source_type=source_type)

        for source in sources:
            config = source.config or {}

            run = CollectionRun(
                collector_name=f"{source.source_type}_{source.name}",
                started_at=datetime.now(timezone.utc),
                status="running",
                items_found=0,
                items_created=0,
                items_skipped=0
            )
            self.run_repo.create(run)

            collector = self._build_collector(source)
            if collector is None:
                run.finished_at = datetime.now(timezone.utc)
                run.status = "failed"
                run.error_message = "Source config is incomplete or source_type is unsupported"
                self.run_repo.update(run)
                total_stats["sources_failed"] += 1
                continue

            try:
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
                    "source_collection_failed",
                    source_name=source.name,
                    source_type=source.source_type,
                    error=str(e)
                )

                run.finished_at = datetime.now(timezone.utc)
                run.status = "failed"
                run.error_message = str(e)
                self.run_repo.update(run)

                total_stats["sources_failed"] += 1

        logger.info("global_collection_finished", stats=total_stats, source_type=source_type)
        return total_stats

    def run_rss_collection(self, only_source_name: Optional[str] = None) -> dict:
        """Оставлено для обратной совместимости — собирает только RSS-источники."""
        return self.run_collection(only_source_name=only_source_name, source_type="rss")
