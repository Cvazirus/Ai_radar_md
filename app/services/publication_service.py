from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional, List, Dict, Any
import structlog
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database.models import Item, ItemStatus, ItemAnalysis, AnalysisStatus, Publication, PublicationStatus, ModerationQueue, ModerationQueueStatus
from app.database.repositories import PublicationRepository, ItemRepository
from app.config import settings

logger = structlog.get_logger()


class PublicationService:
    def __init__(self, db: Session):
        self.db = db
        self.pub_repo = PublicationRepository(db)
        self.item_repo = ItemRepository(db)

    def get_approved_items(self) -> List[Item]:
        """Получить список утвержденных материалов из ModerationQueue или Item."""
        return self.db.query(Item).join(
            ModerationQueue, ModerationQueue.item_id == Item.id, isouter=True
        ).filter(
            or_(
                Item.status.in_([ItemStatus.approved, ItemStatus.manual_review_approved]),
                ModerationQueue.queue_status.in_([ModerationQueueStatus.approved, ModerationQueueStatus.manual_review_approved])
            )
        ).all()

    def format_telegram_text(self, item: Item) -> str:
        """Сформировать текст публикации на основе анализа материала."""
        analysis = self.db.query(ItemAnalysis).filter(
            ItemAnalysis.item_id == item.id,
            ItemAnalysis.status == AnalysisStatus.success
        ).order_by(ItemAnalysis.id.desc()).first()

        if analysis:
            summary_ru = getattr(analysis, "summary_ru", item.title) or item.title
            category_enum = getattr(analysis, "category", None)
            category = category_enum.value if hasattr(category_enum, "value") else str(category_enum or "news")
            total_score = getattr(analysis, "total_score", 0.0)
            try:
                score_str = f"{float(total_score):.2f}"
            except (TypeError, ValueError):
                score_str = "0.00"

            return (
                f"📢 <b>{escape(item.title)}</b>\n\n"
                f"📝 {escape(summary_ru)}\n\n"
                f"🏷 Категория: #{category}\n"
                f"⭐️ Оценка: {score_str}/10\n"
                f"🔗 Источник: {escape(item.url or '')}"
            )
        else:
            return (
                f"📢 <b>{escape(item.title)}</b>\n\n"
                f"🔗 Источник: {escape(item.url or '')}"
            )

    def _feedback_keyboard(self, item_id: int) -> Dict[str, Any]:
        prefix = settings.TELEGRAM_FEEDBACK_CALLBACK_PREFIX.rstrip(":")
        return {"inline_keyboard": [
            [
                {"text": "👍 Нравится", "callback_data": f"{prefix}:like:{item_id}"},
                {"text": "👎 Неинтересно", "callback_data": f"{prefix}:dislike:{item_id}"},
            ],
            [
                {"text": "⭐ Избранное", "callback_data": f"{prefix}:favorite:{item_id}"},
                {"text": "🗑 Скрыть", "callback_data": f"{prefix}:hide:{item_id}"},
            ],
        ]}

    def prepare_publication(self, item: Item, dry_run: bool = False) -> Publication:
        """Создать публикацию в статусе draft."""
        telegram_text = self.format_telegram_text(item)

        existing = self.pub_repo.get(item.id)
        if existing:
            return existing

        pub = Publication(
            item_id=item.id,
            telegram_text=telegram_text,
            status=PublicationStatus.draft
        )

        if not dry_run:
            self.db.add(pub)
            self.db.commit()
            self.db.refresh(pub)

        return pub

    def publish_publication(self, pub: Publication, dry_run: bool = False) -> bool:
        """Опубликовать материал через Telegram."""
        from app.publishers.telegram import TelegramPublisher

        # Transition: ready -> publishing
        pub.status = PublicationStatus.publishing
        if not dry_run:
            self.db.commit()

        logger.info("publication_started", item_id=pub.item_id, status=str(pub.status), dry_run=dry_run)

        if dry_run:
            logger.info("publication_dry_run", item_id=pub.item_id)
            return True

        # Real Telegram publishing
        publisher = TelegramPublisher()
        try:
            result = publisher.send_html(pub.telegram_text, reply_markup=self._feedback_keyboard(pub.item_id))

            if result.success:
                logger.info(
                    "publication_completed",
                    item_id=pub.item_id,
                    message_id=result.message_id,
                    status="published",
                )
                pub.status = PublicationStatus.published
                pub.published_at = datetime.now(timezone.utc)
                pub.telegram_message_id = result.message_id
                try:
                    pub.telegram_chat_id = int(publisher.chat_id)
                except (TypeError, ValueError):
                    logger.warning("publication_chat_id_not_numeric", item_id=pub.item_id)

                item = self.item_repo.get(pub.item_id)
                if item:
                    item.status = ItemStatus.published
                self.db.commit()
                return True
            else:
                logger.error(
                    "publication_failed",
                    item_id=pub.item_id,
                    error=result.error,
                    error_code=result.error_code,
                )
                pub.status = PublicationStatus.failed
                pub.retry_count = (pub.retry_count or 0) + 1
                self.db.commit()
                return False
        finally:
            publisher.close()

    def publish_batch(
        self,
        limit: int = 10,
        item_id: Optional[int] = None,
        resume: bool = False,
        retry_failed: bool = False,
        dry_run: bool = False,
        max_retries: Optional[int] = None,
        retry_backoff_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Пакетная публикация утвержденных материалов.

        max_retries/retry_backoff_minutes only apply when retry_failed=True. They are
        None (unbounded, immediate) by default to preserve the manual --retry-failed
        CLI behavior; the scheduler passes explicit caps for its automatic retries.
        """
        stats = {"processed": 0, "failed": 0, "skipped": 0, "resumed": 0}

        logger.info(
            "publication_batch_started",
            limit=limit,
            item_id=item_id,
            resume=resume,
            retry_failed=retry_failed,
            dry_run=dry_run,
            max_retries=max_retries,
            retry_backoff_minutes=retry_backoff_minutes,
        )

        publications_to_process = []

        if retry_failed:
            query = self.db.query(Publication).filter(Publication.status == PublicationStatus.failed)
            if item_id:
                query = query.filter(Publication.item_id == item_id)
            if max_retries is not None:
                query = query.filter(Publication.retry_count < max_retries)
            if retry_backoff_minutes is not None:
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=retry_backoff_minutes)
                query = query.filter(Publication.updated_at <= cutoff)
            publications_to_process = query.limit(limit).all()
            for p in publications_to_process:
                logger.info("publication_resumed", item_id=p.item_id, previous_status="failed")
                stats["resumed"] += 1

        elif resume:
            query = self.db.query(Publication).filter(
                Publication.status.in_([PublicationStatus.draft, PublicationStatus.ready, PublicationStatus.publishing])
            )
            if item_id:
                query = query.filter(Publication.item_id == item_id)
            publications_to_process = query.limit(limit).all()
            for p in publications_to_process:
                logger.info("publication_resumed", item_id=p.item_id, previous_status=str(p.status))
                stats["resumed"] += 1

        else:
            approved_items = self.get_approved_items()
            if item_id:
                approved_items = [i for i in approved_items if i.id == item_id]

            for item in approved_items:
                if len(publications_to_process) >= limit:
                    break

                existing_pub = self.pub_repo.get(item.id)
                if existing_pub:
                    if existing_pub.status == PublicationStatus.published:
                        logger.info("publication_skipped", item_id=item.id, reason="already_published")
                        stats["skipped"] += 1
                        continue
                    else:
                        logger.info("publication_skipped", item_id=item.id, reason="existing_unfinished_publication")
                        stats["skipped"] += 1
                        continue

                pub = self.prepare_publication(item, dry_run=dry_run)
                publications_to_process.append(pub)

        for pub in publications_to_process:
            try:
                success = self.publish_publication(pub, dry_run=dry_run)
                if success:
                    stats["processed"] += 1
                else:
                    stats["failed"] += 1
            except Exception as e:
                logger.error("publication_unhandled_error", item_id=pub.item_id, error=str(e))
                stats["failed"] += 1
                if not dry_run:
                    pub.status = PublicationStatus.failed
                    self.db.commit()

        logger.info("publication_batch_completed", stats=stats)
        return stats
