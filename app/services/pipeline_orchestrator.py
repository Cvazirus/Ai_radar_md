import uuid
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import structlog
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.database.models import (
    PipelineRun, PipelineRunStatus, Item, ItemStatus, ItemAnalysis,
    AnalysisStatus, ModerationQueue, ModerationQueueStatus
)
from app.services.collection_service import CollectionService
from app.services.analysis_service import AnalysisService
from app.services.moderation_service import ModerationService
from app.pipeline.claim_validation import validate_source_claims

logger = structlog.get_logger()


class PipelineOrchestrator:
    STEPS = ["fetch", "normalize", "analysis", "validation", "moderation", "review"]

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
                # Execute step
                if step_name == "fetch":
                    res = self._step_fetch(limit, item_id, only_source_name)
                elif step_name == "normalize":
                    res = self._step_normalize(limit, item_id)
                elif step_name == "analysis":
                    res = self._step_analysis(limit, item_id)
                elif step_name == "validation":
                    res = self._step_validation(limit, item_id)
                elif step_name == "moderation":
                    res = self._step_moderation(limit, item_id)
                elif step_name == "review":
                    res = self._step_review()
                else:
                    res = {"processed": 0, "skipped": 0, "failed": 0, "errors": []}

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

    def _run_dry_run(self, limit: int, start_idx: int, end_idx: int, item_id: Optional[int], only_source_name: Optional[str] = None) -> Dict[str, Any]:
        step_results = {}
        for idx in range(start_idx, end_idx + 1):
            step_name = self.STEPS[idx]
            
            # Count prospective items
            if step_name == "fetch":
                # Count active RSS sources
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
                # Successful analyses with no moderation queue
                from sqlalchemy import select
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
            elif step_name == "review":
                query = self.db.query(ModerationQueue).filter(ModerationQueue.queue_status == ModerationQueueStatus.pending)
                if item_id:
                    query = query.filter(ModerationQueue.item_id == item_id)
                processed = query.count()
                skipped = 0
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

    # Step runners
    def _step_fetch(self, limit: int, item_id: Optional[int], only_source_name: Optional[str] = None) -> Dict[str, Any]:
        # Fetch calls CollectionService
        if item_id:
            # Skip global RSS fetch for target item
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
        query = self.db.query(Item).filter(Item.status == ItemStatus.collected)
        if item_id:
            query = query.filter(Item.id == item_id)
            
        items = query.limit(limit).all()
        processed = 0
        failed = 0
        errors = []
        
        for item in items:
            try:
                # Apply normalization status transition
                item.status = ItemStatus.normalized
                self.db.add(item)
                processed += 1
            except Exception as e:
                failed += 1
                errors.append(f"Normalize failed for item {item.id}: {str(e)}")
                
        self.db.commit()
        return {"processed": processed, "skipped": 0, "failed": failed, "errors": errors}

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
        # Validate claims of the latest analyses
        query = self.db.query(ItemAnalysis).filter(ItemAnalysis.status == AnalysisStatus.success)
        if item_id:
            query = query.filter(ItemAnalysis.item_id == item_id)
            
        analyses = query.order_by(desc(ItemAnalysis.id)).limit(limit).all()
        processed = 0
        failed = 0
        errors = []
        
        for analysis in analyses:
            try:
                item = analysis.item
                if not item:
                    continue
                claims = analysis.source_claims
                if isinstance(claims, dict) and "claims" in claims:
                    claims = claims["claims"]
                res = validate_source_claims(item.raw_text or item.title, claims)
                if res.invalid_claims:
                    failed += 1
                    errors.append(f"Validation failed for analysis {analysis.id}: {len(res.invalid_claims)} invalid claims")
                else:
                    processed += 1
            except Exception as e:
                failed += 1
                errors.append(f"Validation check failed for analysis {analysis.id}: {str(e)}")
                
        return {"processed": processed, "skipped": 0, "failed": failed, "errors": errors}

    def _step_moderation(self, limit: int, item_id: Optional[int]) -> Dict[str, Any]:
        service = ModerationService(self.db)
        if item_id:
            # Find latest analysis for the target item
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

    def _step_review(self) -> Dict[str, Any]:
        # Count pending items in queue
        count = self.db.query(ModerationQueue).filter(ModerationQueue.queue_status == ModerationQueueStatus.pending).count()
        return {"processed": count, "skipped": 0, "failed": 0, "errors": []}
