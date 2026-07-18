import logging
import time
from typing import List, Optional
from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from app.config import settings
from app.database.models import ModerationQueue, ModerationDecisionLog, ModerationQueueStatus, ItemAnalysis, AnalysisStatus, TelegramModerationMessage
from app.database.repositories import ModerationQueueRepository, ModerationDecisionLogRepository, ItemRepository, AnalysisRepository
from app.pipeline.moderation_rules import evaluate_item_moderation, MODERATION_RULES_VERSION
from app.llm.schemas import ModerationDecisionResult

logger = logging.getLogger(__name__)

class ModerationService:
    def __init__(self, db: Session):
        self.db = db
        self.queue_repo = ModerationQueueRepository(db)
        self.log_repo = ModerationDecisionLogRepository(db)
        self.item_repo = ItemRepository(db)
        self.analysis_repo = AnalysisRepository(db)

    def moderate_analysis(self, analysis_id: int, force_recalculate: bool = False, force_reason: Optional[str] = None) -> Optional[ModerationDecisionResult]:
        """
        Evaluate and moderate a single ItemAnalysis.
        """
        start_time = time.time()
        
        if not getattr(settings, "MODERATION_ENABLED", True):
            logger.info("Moderation is disabled in configuration.")
            return None

        analysis = self.analysis_repo.get_by_id(analysis_id)
        if not analysis:
            logger.error(f"ItemAnalysis not found: {analysis_id}")
            return None

        # Check existing queue item
        existing = self.queue_repo.get_by_analysis_id(analysis_id)
        if existing and not force_recalculate:
            logger.info("moderation_skipped_existing", extra={
                "item_id": analysis.item_id,
                "analysis_id": analysis_id,
                "queue_id": existing.id
            })
            # Return result mapped from existing
            return ModerationDecisionResult(
                item_id=existing.item_id,
                analysis_id=existing.analysis_id,
                decision=existing.decision,
                priority=existing.priority,
                decision_score=float(existing.decision_score) if existing.decision_score is not None else 0.0,
                blocking_reasons=existing.blocking_reasons or [],
                decision_reasons=existing.decision_reasons or {},
                warnings=existing.warnings or [],
                rules_version=MODERATION_RULES_VERSION,
                eligible_for_queue=(existing.decision != "blocked")
            )

        logger.info("moderation_selected", extra={
            "item_id": analysis.item_id,
            "analysis_id": analysis_id
        })

        item = self.item_repo.get(analysis.item_id)
        if not item:
            logger.error(f"Item not found: {analysis.item_id}")
            return None

        # Load duplicate relations
        from app.database.models import DuplicateRelation
        duplicate_relations = self.db.query(DuplicateRelation).filter(
            (DuplicateRelation.item_id == item.id) | (DuplicateRelation.duplicate_of_item_id == item.id)
        ).all()

        logger.info("moderation_rules_started", extra={
            "item_id": item.id,
            "analysis_id": analysis_id
        })

        # Evaluate rules
        result = evaluate_item_moderation(item, analysis, duplicate_relations)

        duration_ms = int((time.time() - start_time) * 1000)

        if result.decision == "blocked":
            logger.info("moderation_blocked", extra={
                "item_id": item.id,
                "analysis_id": analysis_id,
                "decision": str(result.decision),
                "reason_codes": result.blocking_reasons,
                "rules_version": result.rules_version,
                "duration_ms": duration_ms
            })
        else:
            logger.info("moderation_decision_created", extra={
                "item_id": item.id,
                "analysis_id": analysis_id,
                "decision": str(result.decision),
                "priority": str(result.priority),
                "decision_score": result.decision_score,
                "rules_version": result.rules_version,
                "duration_ms": duration_ms
            })

        # Save to DB
        if existing and force_recalculate:
            # Update existing queue item
            prev_status = existing.queue_status
            existing.queue_status = ModerationQueueStatus.pending
            existing.priority = result.priority
            existing.decision = result.decision
            existing.decision_score = result.decision_score
            existing.decision_reasons = result.decision_reasons
            existing.blocking_reasons = result.blocking_reasons
            existing.warnings = result.warnings
            existing.telegram_chat_id = None
            existing.telegram_message_id = None
            existing.telegram_dispatch_started_at = None
            self.db.execute(
                update(TelegramModerationMessage)
                .where(TelegramModerationMessage.moderation_queue_id == existing.id)
                .values(is_active=False)
            )
            existing.updated_at = func.now()
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            
            # Log transition/recalculation
            log_item = ModerationDecisionLog(
                queue_id=existing.id,
                previous_status=prev_status,
                new_status=ModerationQueueStatus.pending,
                action="recalculate",
                actor="system",
                reason=force_reason or "force recalculation of moderation rules",
                metadata_json=result.decision_reasons
            )
            self.log_repo.create(log_item)
            logger.info("moderation_queue_updated", extra={
                "item_id": item.id,
                "analysis_id": analysis_id,
                "queue_id": existing.id,
                "decision": str(result.decision),
                "priority": str(result.priority),
                "decision_score": result.decision_score
            })
        else:
            # Create new queue item
            queue_item = ModerationQueue(
                item_id=item.id,
                analysis_id=analysis_id,
                queue_status=ModerationQueueStatus.pending,
                priority=result.priority,
                decision=result.decision,
                decision_score=result.decision_score,
                decision_reasons=result.decision_reasons,
                blocking_reasons=result.blocking_reasons,
                warnings=result.warnings
            )
            self.queue_repo.create(queue_item)
            
            # Log initial decision
            log_item = ModerationDecisionLog(
                queue_id=queue_item.id,
                previous_status=None,
                new_status=ModerationQueueStatus.pending,
                action="create",
                actor="system",
                reason="initial auto moderation",
                metadata_json=result.decision_reasons
            )
            self.log_repo.create(log_item)
            
            logger.info("moderation_queue_created", extra={
                "item_id": item.id,
                "analysis_id": analysis_id,
                "queue_id": queue_item.id,
                "decision": str(result.decision),
                "priority": str(result.priority),
                "decision_score": result.decision_score
            })

        return result

    def moderate_batch(self, limit: Optional[int] = None) -> List[ModerationDecisionResult]:
        """
        Moderate a batch of successful analyses that have no queue item yet.
        """
        start_time = time.time()
        
        batch_limit = limit or getattr(settings, "MODERATION_BATCH_LIMIT", 50)
        
        # Query successful analyses that are not in moderation_queue
        # Subquery for already moderated analysis ids
        from sqlalchemy import select
        moderated_ids = select(ModerationQueue.analysis_id)
        
        analyses = self.db.query(ItemAnalysis).filter(
            ItemAnalysis.status == AnalysisStatus.success,
            ~ItemAnalysis.id.in_(moderated_ids)
        ).limit(batch_limit).all()

        results = []
        for analysis in analyses:
            try:
                res = self.moderate_analysis(analysis.id)
                if res:
                    results.append(res)
            except Exception as e:
                logger.error(f"Error moderating analysis {analysis.id}: {str(e)}", exc_info=True)
                # Keep going to process other items in the batch!

        logger.info("moderation_batch_completed", extra={
            "processed": len(analyses),
            "results_count": len(results),
            "duration_ms": int((time.time() - start_time) * 1000)
        })

        return results
