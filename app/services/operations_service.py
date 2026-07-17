"""Operations & Monitoring service — read-only system status."""
import structlog
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.database.models import (
    Item, ItemStatus, ItemAnalysis, AnalysisStatus,
    Publication, PublicationStatus,
    ModerationQueue, ModerationQueueStatus, ModerationDecision,
    CollectionRun, Source, PipelineRun
)

logger = structlog.get_logger()


class OperationsService:
    """Read-only service for system status and health monitoring."""

    def __init__(self, db: Session):
        self.db = db

    def get_full_status(self) -> Dict[str, Any]:
        """Collect status from all components."""
        logger.info("operations_started")
        start = time.time()

        try:
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pipeline": self._get_pipeline_status(),
                "scheduler": self._get_scheduler_status(),
                "collection": self._get_collection_status(),
                "moderation": self._get_moderation_status(),
                "publication": self._get_publication_status(),
                "items": self._get_items_status(),
                "analysis": self._get_analysis_status(),
                "health": None,
            }
            result["health"] = self._calculate_health(result)

            duration_ms = int((time.time() - start) * 1000)
            logger.info("operations_completed", duration_ms=duration_ms, health=result["health"]["status"])
            return result
        except Exception as e:
            logger.error("operations_failed", error=str(e))
            raise

    def _get_pipeline_status(self) -> Dict[str, Any]:
        """Get pipeline run statistics."""
        try:
            last_run = self.db.query(PipelineRun).order_by(PipelineRun.id.desc()).first()
            running = self.db.query(PipelineRun).filter(
                PipelineRun.status.in_(["running", "pending"])
            ).count()

            return {
                "last_run_id": last_run.run_id if last_run else None,
                "last_status": last_run.status.value if last_run and last_run.status else None,
                "last_started_at": last_run.started_at.isoformat() if last_run and last_run.started_at else None,
                "last_finished_at": last_run.finished_at.isoformat() if last_run and last_run.finished_at else None,
                "last_duration_ms": last_run.duration_ms if last_run else None,
                "last_items_processed": last_run.items_processed if last_run else None,
                "last_items_failed": last_run.items_failed if last_run else None,
                "running_now": running > 0,
                "total_runs": self.db.query(PipelineRun).count(),
            }
        except Exception:
            return {"error": "pipeline_runs table not available"}

    def _get_scheduler_status(self) -> Dict[str, Any]:
        """Get scheduler status from file lock or process check."""
        lock_file = "/tmp/ai_radar_scheduler.lock"
        pid = None
        active = False

        try:
            if os.path.exists(lock_file):
                with open(lock_file, "r") as f:
                    content = f.read().strip()
                    if content.isdigit():
                        pid = int(content)
                        # Check if process is alive
                        try:
                            os.kill(pid, 0)
                            active = True
                        except (OSError, ProcessLookupError):
                            active = False
        except Exception:
            pass

        return {
            "active": active,
            "pid": pid,
            "lock_file_exists": os.path.exists(lock_file),
        }

    def _get_collection_status(self) -> Dict[str, Any]:
        """Get collection run statistics."""
        try:
            total_sources = self.db.query(Source).filter(Source.enabled == True).count()
            total_runs = self.db.query(CollectionRun).count()
            successful_runs = self.db.query(CollectionRun).filter(CollectionRun.status == "success").count()
            failed_runs = self.db.query(CollectionRun).filter(CollectionRun.status == "failed").count()
            last_run = self.db.query(CollectionRun).order_by(CollectionRun.id.desc()).first()

            return {
                "total_sources": total_sources,
                "total_runs": total_runs,
                "successful_runs": successful_runs,
                "failed_runs": failed_runs,
                "last_run_at": last_run.started_at.isoformat() if last_run and last_run.started_at else None,
                "last_run_status": last_run.status if last_run else None,
            }
        except Exception:
            return {"error": "collection_runs table not available"}

    def _get_moderation_status(self) -> Dict[str, Any]:
        """Get moderation queue statistics."""
        try:
            pending = self.db.query(ModerationQueue).filter(
                ModerationQueue.queue_status == ModerationQueueStatus.pending
            ).count()
            in_review = self.db.query(ModerationQueue).filter(
                ModerationQueue.queue_status == ModerationQueueStatus.in_review
            ).count()
            approved = self.db.query(ModerationQueue).filter(
                ModerationQueue.queue_status.in_([
                    ModerationQueueStatus.approved,
                    ModerationQueueStatus.manual_review_approved
                ])
            ).count()
            blocked = self.db.query(ModerationQueue).filter(
                ModerationQueue.decision == ModerationDecision.blocked
            ).count()
            rejected = self.db.query(ModerationQueue).filter(
                ModerationQueue.queue_status == ModerationQueueStatus.rejected
            ).count()
            total = self.db.query(ModerationQueue).count()

            return {
                "total": total,
                "pending": pending,
                "in_review": in_review,
                "approved": approved,
                "blocked": blocked,
                "rejected": rejected,
            }
        except Exception:
            return {"error": "moderation_queue table not available"}

    def _get_publication_status(self) -> Dict[str, Any]:
        """Get publication statistics."""
        try:
            draft = self.db.query(Publication).filter(
                Publication.status == PublicationStatus.draft
            ).count()
            ready = self.db.query(Publication).filter(
                Publication.status == PublicationStatus.ready
            ).count()
            publishing = self.db.query(Publication).filter(
                Publication.status == PublicationStatus.publishing
            ).count()
            published = self.db.query(Publication).filter(
                Publication.status == PublicationStatus.published
            ).count()
            failed = self.db.query(Publication).filter(
                Publication.status == PublicationStatus.failed
            ).count()
            cancelled = self.db.query(Publication).filter(
                Publication.status == PublicationStatus.cancelled
            ).count()
            total = self.db.query(Publication).count()

            return {
                "total": total,
                "draft": draft,
                "ready": ready,
                "publishing": publishing,
                "published": published,
                "failed": failed,
                "cancelled": cancelled,
            }
        except Exception:
            return {"error": "publications table not available"}

    def _get_items_status(self) -> Dict[str, Any]:
        """Get items statistics by status."""
        try:
            rows = self.db.query(
                Item.status, func.count(Item.id)
            ).group_by(Item.status).all()

            by_status = {str(row[0].value if hasattr(row[0], 'value') else row[0]): row[1] for row in rows}
            total = sum(by_status.values())

            return {
                "total": total,
                "by_status": by_status,
            }
        except Exception:
            return {"error": "items query failed"}

    def _get_analysis_status(self) -> Dict[str, Any]:
        """Get analysis statistics by status."""
        try:
            rows = self.db.query(
                ItemAnalysis.status, func.count(ItemAnalysis.id)
            ).group_by(ItemAnalysis.status).all()

            by_status = {str(row[0].value if hasattr(row[0], 'value') else row[0]): row[1] for row in rows}
            total = sum(by_status.values())

            return {
                "total": total,
                "by_status": by_status,
            }
        except Exception:
            return {"error": "item_analysis query failed"}

    def _calculate_health(self, status: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate overall system health."""
        issues = []
        score = 100

        # Check pipeline
        pipeline = status.get("pipeline", {})
        if pipeline.get("last_status") == "failed":
            issues.append("Last pipeline run failed")
            score -= 20
        if pipeline.get("running_now"):
            issues.append("Pipeline currently running")
            # No penalty — running is normal

        # Check scheduler
        scheduler = status.get("scheduler", {})
        if not scheduler.get("active") and not scheduler.get("lock_file_exists"):
            issues.append("Scheduler not active (no lock file)")
            score -= 5

        # Check collection
        collection = status.get("collection", {})
        if collection.get("failed_runs", 0) > collection.get("successful_runs", 0):
            issues.append("More failed collection runs than successful")
            score -= 15

        # Check moderation
        moderation = status.get("moderation", {})
        if moderation.get("pending", 0) > 50:
            issues.append(f"High moderation backlog: {moderation['pending']} pending")
            score -= 10

        # Check publication
        publication = status.get("publication", {})
        if publication.get("failed", 0) > 0:
            issues.append(f"Failed publications: {publication['failed']}")
            score -= 10

        # Check items
        items = status.get("items", {})
        if items.get("total", 0) == 0:
            issues.append("No items in database")
            score -= 30

        # Determine status
        if score >= 90:
            health_status = "healthy"
        elif score >= 70:
            health_status = "warning"
        elif score >= 50:
            health_status = "degraded"
        else:
            health_status = "critical"

        logger.info("health_calculated", status=health_status, score=score, issues=len(issues))

        return {
            "status": health_status,
            "score": score,
            "issues": issues,
        }

    def get_component_status(self, component: str) -> Dict[str, Any]:
        """Get status for a specific component."""
        full = self.get_full_status()
        if component in full:
            return full[component]
        return {"error": f"Unknown component: {component}"}

    def get_summary(self) -> str:
        """Get human-readable summary."""
        status = self.get_full_status()
        health = status["health"]
        items = status["items"]
        moderation = status["moderation"]
        publication = status["publication"]

        lines = [
            f"Health: {health['status'].upper()} (score: {health['score']}/100)",
            f"Items: {items['total']} total ({items['by_status'].get('collected', 0)} collected, {items['by_status'].get('analyzed', 0)} analyzed)",
            f"Moderation: {moderation['total']} total ({moderation['pending']} pending, {moderation['approved']} approved, {moderation['blocked']} blocked)",
            f"Publications: {publication['total']} total ({publication['published']} published, {publication['draft']} draft)",
        ]

        if health["issues"]:
            lines.append(f"Issues: {', '.join(health['issues'])}")

        return "\n".join(lines)
