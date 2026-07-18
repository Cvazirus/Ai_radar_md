import uuid
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import structlog
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.database.models import (
    PipelineRun, PipelineRunStatus, Item, ItemStatus, ItemAnalysis,
    AnalysisStatus, ModerationQueue, ModerationQueueStatus, ModerationDecision,
    ModerationDecisionLog, Publication, PublicationStatus
)
from app.database.repositories import ModerationQueueRepository, ModerationDecisionLogRepository
from app.pipeline.moderation_state_machine import is_transition_allowed
from app.services.collection_service import CollectionService
from app.services.analysis_service import AnalysisService
from app.services.normalize_service import NormalizeService
from app.services.validation_service import ValidationService
from app.services.moderation_service import ModerationService
from app.services.publication_service import PublicationService
from app.config import settings

logger = structlog.get_logger()

AUTO_APPROVABLE_DECISIONS = (ModerationDecision.digest_candidate, ModerationDecision.priority_review)


class PipelineOrchestrator:
    STEPS = ["fetch", "normalize", "analysis", "validation", "moderation", "approval", "publication"]

    def __init__(self, db: Session):
        self.db = db

    def run_pipeline(
        self,
        limit: int = 10,
        from_step: Optional[str] = None,
        to_step: Optional[str] = None,
        resume: bool = False,
        item_id: Optional[int] = None,
        dry_run: bool = False,
        only_source_name: Optional[str] = None
    ) -> Dict[str, Any]:
        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        
        # 1. Handle resume
        pipeline_run = None
        if resume and not dry_run:
            pipeline_run = self.db.query(PipelineRun).filter(
                PipelineRun.status.in_([PipelineRunStatus.running, PipelineRunStatus.failed, PipelineRunStatus.cancelled])
            ).order_by(desc(PipelineRun.started_at)).first()
            
            if pipeline_run:
                run_id = pipeline_run.run_id
                logger.info("pipeline_resumed", run_id=run_id, step=pipeline_run.current_step)
                if not from_step:
                    from_step = pipeline_run.current_step
            else:
                logger.info("pipeline_resume_no_active_run_found", run_id=run_id)

        # 2. Determine start/end indices
        start_idx = 0
        if from_step:
            if from_step in self.STEPS:
                start_idx = self.STEPS.index(from_step)
            else:
                raise ValueError(f"Invalid from_step: {from_step}. Valid steps: {self.STEPS}")

        end_idx = len(self.STEPS) - 1
        if to_step:
            if to_step in self.STEPS:
                end_idx = self.STEPS.index(to_step)
            else:
                raise ValueError(f"Invalid to_step: {to_step}. Valid steps: {self.STEPS}")

        if start_idx > end_idx:
            raise ValueError(f"from_step '{from_step}' comes after to_step '{to_step}'")

        # 3. Dry run reporting
        if dry_run:
            return self._run_dry_run(limit, start_idx, end_idx, item_id, only_source_name)

        # 4. Initialize PipelineRun in DB
        if not pipeline_run:
            pipeline_run = PipelineRun(
                run_id=run_id,
                status=PipelineRunStatus.running,
                started_at=datetime.now(timezone.utc),
                current_step=self.STEPS[start_idx],
                summary_json={"steps": {}}
            )
            self.db.add(pipeline_run)
            self.db.commit()
        else:
            pipeline_run.status = PipelineRunStatus.running
            pipeline_run.current_step = self.STEPS[start_idx]
            self.db.commit()

        logger.info("pipeline_started", run_id=run_id, start_step=self.STEPS[start_idx], end_step=self.STEPS[end_idx])

        total_processed = 0
        total_failed = 0
        step_results = {}
        pipeline_failed = False
        pipeline_errors = []

        start_time = time.time()

        for idx in range(start_idx, end_idx + 1):
            step_name = self.STEPS[idx]
            pipeline_run.current_step = step_name
            self.db.commit()

            logger.info("pipeline_step_started", run_id=run_id, step=step_name)
            step_start = time.time()
            
            try:
                # Execute step - all business logic delegated to services
                res = self._execute_step(step_name, limit, item_id, only_source_name)

                duration_ms = int((time.time() - step_start) * 1000)
                step_result = {
                    "step_name": step_name,
                    "started_at": datetime.fromtimestamp(step_start, timezone.utc).isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": duration_ms,
                    "processed": res.get("processed", 0),
                    "skipped": res.get("skipped", 0),
                    "failed": res.get("failed", 0),
                    "errors": res.get("errors", []),
                    "next_step": self.STEPS[idx + 1] if idx + 1 < len(self.STEPS) else None
                }

                logger.info(
                    "pipeline_step_completed",
                    run_id=run_id,
                    step=step_name,
                    duration=duration_ms,
                    processed=step_result["processed"],
                    failed=step_result["failed"]
                )

                step_results[step_name] = step_result
                total_processed += step_result["processed"]
                total_failed += step_result["failed"]
                pipeline_errors.extend(step_result["errors"])

            except Exception as e:
                duration_ms = int((time.time() - step_start) * 1000)
                step_result = {
                    "step_name": step_name,
                    "started_at": datetime.fromtimestamp(step_start, timezone.utc).isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": duration_ms,
                    "processed": 0,
                    "skipped": 0,
                    "failed": 1,
                    "errors": [str(e)],
                    "next_step": None
                }
                logger.error(
                    "pipeline_step_failed",
                    run_id=run_id,
                    step=step_name,
                    duration=duration_ms,
                    processed=0,
                    failed=1,
                    error=str(e)
                )
                step_results[step_name] = step_result
                total_failed += 1
                pipeline_errors.append(f"Step {step_name} critical failure: {str(e)}")
                pipeline_failed = True
                break

        # 5. Finalize run status
        total_duration_ms = int((time.time() - start_time) * 1000)
        pipeline_run.finished_at = datetime.now(timezone.utc)
        pipeline_run.duration_ms = total_duration_ms
        pipeline_run.items_total = total_processed + total_failed
        pipeline_run.items_processed = total_processed
        pipeline_run.items_failed = total_failed
        
        if pipeline_failed:
            pipeline_run.status = PipelineRunStatus.failed
        else:
            pipeline_run.status = PipelineRunStatus.completed

        # Populate summary JSON
        summary = {
            "run_id": run_id,
            "status": str(pipeline_run.status),
            "started_at": pipeline_run.started_at.isoformat(),
            "finished_at": pipeline_run.finished_at.isoformat(),
            "duration_ms": total_duration_ms,
            "items_total": pipeline_run.items_total,
            "items_processed": total_processed,
            "items_failed": total_failed,
            "errors": pipeline_errors,
            "steps": step_results
        }
        pipeline_run.summary_json = summary
        self.db.commit()

        logger.info(
            "pipeline_finished",
            run_id=run_id,
            status=str(pipeline_run.status),
            duration=total_duration_ms,
            processed=total_processed,
            failed=total_failed
        )

        return summary

    def _execute_step(self, step_name: str, limit: int, item_id: Optional[int], only_source_name: Optional[str] = None) -> Dict[str, Any]:
        """Delegate step execution to appropriate service."""
        if step_name == "fetch":
            return self._step_fetch(limit, item_id, only_source_name)
        elif step_name == "normalize":
            return self._step_normalize(limit, item_id)
        elif step_name == "analysis":
            return self._step_analysis(limit, item_id)
        elif step_name == "validation":
            return self._step_validation(limit, item_id)
        elif step_name == "moderation":
            return self._step_moderation(limit, item_id)
        elif step_name == "approval":
            return self._step_approval(limit, item_id)
        elif step_name == "publication":
            return self._step_publication(limit, item_id)
        else:
            return {"processed": 0, "skipped": 0, "failed": 0, "errors": []}

    def _run_dry_run(self, limit: int, start_idx: int, end_idx: int, item_id: Optional[int], only_source_name: Optional[str] = None) -> Dict[str, Any]:
        step_results = {}
        for idx in range(start_idx, end_idx + 1):
            step_name = self.STEPS[idx]
            
            if step_name == "fetch":
                from app.database.models import Source
                query = self.db.query(Source).filter(Source.source_type == "rss", Source.enabled == True)
                if only_source_name:
                    query = query.filter(Source.name == only_source_name)
                count = query.count()
                processed = count
                skipped = 0
            elif step_name == "normalize":
                query = self.db.query(Item).filter(Item.status == ItemStatus.collected)
                if item_id:
                    query = query.filter(Item.id == item_id)
                count = query.count()
                processed = min(count, limit) if count > 0 else 0
                skipped = max(0, count - limit)
            elif step_name == "analysis":
                query = self.db.query(Item).filter(Item.status.in_([ItemStatus.collected, ItemStatus.normalized]))
                if item_id:
                    query = query.filter(Item.id == item_id)
                count = query.count()
                processed = min(count, limit) if count > 0 else 0
                skipped = max(0, count - limit)
            elif step_name == "validation":
                query = self.db.query(ItemAnalysis).filter(ItemAnalysis.status == AnalysisStatus.success)
                if item_id:
                    query = query.filter(ItemAnalysis.item_id == item_id)
                count = query.count()
                processed = min(count, limit) if count > 0 else 0
                skipped = max(0, count - limit)
            elif step_name == "moderation":
                moderated_ids = select(ModerationQueue.analysis_id)
                query = self.db.query(ItemAnalysis).filter(
                    ItemAnalysis.status == AnalysisStatus.success,
                    ~ItemAnalysis.id.in_(moderated_ids)
                )
                if item_id:
                    query = query.filter(ItemAnalysis.item_id == item_id)
                count = query.count()
                processed = min(count, limit) if count > 0 else 0
                skipped = max(0, count - limit)
            elif step_name == "approval":
                query = self.db.query(ModerationQueue).filter(ModerationQueue.queue_status == ModerationQueueStatus.pending)
                if item_id:
                    query = query.filter(ModerationQueue.item_id == item_id)
                count = query.count()
                processed = min(count, limit) if count > 0 else 0
                skipped = max(0, count - limit)
            elif step_name == "publication":
                approved_item_ids = select(ModerationQueue.item_id).where(
                    ModerationQueue.queue_status.in_([ModerationQueueStatus.approved, ModerationQueueStatus.manual_review_approved])
                )
                published_item_ids = select(Publication.item_id).where(Publication.status == PublicationStatus.published)
                query = self.db.query(Item).filter(
                    Item.id.in_(approved_item_ids),
                    ~Item.id.in_(published_item_ids)
                )
                if item_id:
                    query = query.filter(Item.id == item_id)
                count = query.count()
                processed = min(count, limit) if count > 0 else 0
                skipped = max(0, count - limit)
            else:
                processed = 0
                skipped = 0

            step_results[step_name] = {
                "step_name": step_name,
                "processed": processed,
                "skipped": skipped,
                "failed": 0,
                "errors": [],
                "next_step": self.STEPS[idx + 1] if idx + 1 < len(self.STEPS) else None
            }

        return {
            "run_id": "dry_run",
            "status": "completed",
            "dry_run": True,
            "steps": step_results
        }

    # Step runners - all delegate to services
    def _step_fetch(self, limit: int, item_id: Optional[int], only_source_name: Optional[str] = None) -> Dict[str, Any]:
        if item_id:
            return {"processed": 0, "skipped": 1, "failed": 0, "errors": []}
        service = CollectionService(self.db)
        stats = service.run_rss_collection(only_source_name=only_source_name)
        return {
            "processed": stats.get("items_created", 0),
            "skipped": stats.get("items_skipped", 0),
            "failed": stats.get("sources_failed", 0),
            "errors": []
        }

    def _step_normalize(self, limit: int, item_id: Optional[int]) -> Dict[str, Any]:
        service = NormalizeService(self.db)
        return service.normalize_batch(limit=limit, item_id=item_id)

    def _step_analysis(self, limit: int, item_id: Optional[int]) -> Dict[str, Any]:
        service = AnalysisService(self.db)
        if item_id:
            item = self.db.query(Item).filter(Item.id == item_id).first()
            if not item:
                return {"processed": 0, "skipped": 0, "failed": 1, "errors": [f"Item {item_id} not found"]}
            try:
                res = service.analyze_single_item(item)
                if res == "skipped_existing":
                    return {"processed": 0, "skipped": 1, "failed": 0, "errors": []}
                return {"processed": 1, "skipped": 0, "failed": 0, "errors": []}
            except Exception as e:
                return {"processed": 0, "skipped": 0, "failed": 1, "errors": [str(e)]}
        stats = service.analyze_batch(limit=limit)
        return {
            "processed": stats.get("success", 0),
            "skipped": stats.get("skipped", 0),
            "failed": stats.get("failed", 0) + stats.get("invalid", 0),
            "errors": []
        }

    def _step_validation(self, limit: int, item_id: Optional[int]) -> Dict[str, Any]:
        service = ValidationService(self.db)
        return service.validate_batch(limit=limit, item_id=item_id)

    def _step_moderation(self, limit: int, item_id: Optional[int]) -> Dict[str, Any]:
        service = ModerationService(self.db)
        if item_id:
            analysis = self.db.query(ItemAnalysis).filter(
                ItemAnalysis.item_id == item_id,
                ItemAnalysis.status == AnalysisStatus.success
            ).order_by(desc(ItemAnalysis.id)).first()
            if not analysis:
                return {"processed": 0, "skipped": 1, "failed": 0, "errors": []}
            try:
                res = service.moderate_analysis(analysis.id)
                if res:
                    return {"processed": 1, "skipped": 0, "failed": 0, "errors": []}
                return {"processed": 0, "skipped": 1, "failed": 0, "errors": []}
            except Exception as e:
                return {"processed": 0, "skipped": 0, "failed": 1, "errors": [str(e)]}
        results = service.moderate_batch(limit=limit)
        return {
            "processed": len(results),
            "skipped": 0,
            "failed": 0,
            "errors": []
        }

    def _step_approval(self, limit: int, item_id: Optional[int]) -> Dict[str, Any]:
        queue_repo = ModerationQueueRepository(self.db)
        log_repo = ModerationDecisionLogRepository(self.db)

        query = self.db.query(ModerationQueue).filter(ModerationQueue.queue_status == ModerationQueueStatus.pending)
        if item_id:
            query = query.filter(ModerationQueue.item_id == item_id)
        pending_items = query.limit(limit).all()

        processed = 0
        skipped = 0
        for queue_item in pending_items:
            if settings.AUTO_APPROVAL_ENABLED and queue_item.decision in AUTO_APPROVABLE_DECISIONS:
                prev_status = queue_item.queue_status
                target_status = ModerationQueueStatus.approved
                if not is_transition_allowed(prev_status, target_status):
                    skipped += 1
                    continue
                queue_repo.update_status(queue_item.id, target_status, reviewer="auto")
                log_repo.create(ModerationDecisionLog(
                    queue_id=queue_item.id,
                    previous_status=prev_status,
                    new_status=target_status,
                    action="auto_approve",
                    actor="auto",
                    reason=f"auto-approved: decision={queue_item.decision}"
                ))
                processed += 1
            else:
                skipped += 1

        return {"processed": processed, "skipped": skipped, "failed": 0, "errors": []}

    def _step_publication(self, limit: int, item_id: Optional[int]) -> Dict[str, Any]:
        service = PublicationService(self.db)
        stats = service.publish_batch(limit=limit, item_id=item_id)
        return {
            "processed": stats.get("processed", 0),
            "skipped": stats.get("skipped", 0),
            "failed": stats.get("failed", 0),
            "errors": []
        }
