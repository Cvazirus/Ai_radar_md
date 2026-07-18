import os
import time
import signal
import sys
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import structlog
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Source, PipelineRun, PipelineRunStatus
from app.services.pipeline_orchestrator import PipelineOrchestrator
from app.services.publication_service import PublicationService

logger = structlog.get_logger()


class PipelineLockError(Exception):
    pass


class SchedulerService:
    LOCK_FILE = "/tmp/ai_radar_pipeline.lock"

    def __init__(self, db: Session):
        self.db = db
        self.orchestrator = PipelineOrchestrator(db)
        self._stop_event = threading.Event()
        self._is_running = False

    def get_active_sources(self) -> List[Source]:
        """Получить список активных RSS источников из БД."""
        return self.db.query(Source).filter(
            Source.source_type == "rss",
            Source.enabled == True
        ).all()

    def acquire_lock(self) -> None:
        """Попытка захвата блокировки пайплайна (File Lock + DB Lock)."""
        now = datetime.now(timezone.utc)
        
        # 1. DB Lock Check
        active_run = self.db.query(PipelineRun).filter(
            PipelineRun.status == PipelineRunStatus.running
        ).order_by(PipelineRun.started_at.desc()).first()
        
        if active_run:
            started_at = active_run.started_at or now
            lock_age = (now - started_at).total_seconds()
            if lock_age < settings.SCHEDULER_LOCK_TIMEOUT:
                logger.warn("scheduler_db_lock_active", run_id=active_run.run_id, started_at=active_run.started_at, age_seconds=lock_age)
                raise PipelineLockError(f"Pipeline is already running (DB lock run_id={active_run.run_id})")
            else:
                logger.warn("scheduler_db_lock_expired", run_id=active_run.run_id, age_seconds=lock_age)
                active_run.status = PipelineRunStatus.failed
                active_run.summary_json = {
                    **(active_run.summary_json or {}),
                    "error": "Lock expired and broken by scheduler"
                }
                self.db.commit()

        # 2. File Lock Check
        if os.path.exists(self.LOCK_FILE):
            try:
                with open(self.LOCK_FILE, "r") as f:
                    content = f.read().strip().split(",")
                    if len(content) == 2:
                        pid = int(content[0])
                        started_ts = float(content[1])
                        
                        process_alive = True
                        try:
                            os.kill(pid, 0)
                        except OSError:
                            process_alive = False
                            
                        age = time.time() - started_ts
                        if process_alive and age < settings.SCHEDULER_LOCK_TIMEOUT:
                            logger.warn("scheduler_file_lock_active", pid=pid, age_seconds=age)
                            raise PipelineLockError(f"Pipeline is already running (File lock pid={pid})")
                        else:
                            logger.warn("scheduler_file_lock_stale_or_expired", pid=pid, alive=process_alive, age_seconds=age)
            except Exception as e:
                if isinstance(e, PipelineLockError):
                    raise
                logger.error("scheduler_lock_read_failed", error=str(e))

        # Записываем новый lock-файл
        try:
            with open(self.LOCK_FILE, "w") as f:
                f.write(f"{os.getpid()},{time.time()}")
        except Exception as e:
            logger.error("scheduler_lock_write_failed", error=str(e))

    def release_lock(self) -> None:
        """Освобождение блокировки пайплайна."""
        try:
            if os.path.exists(self.LOCK_FILE):
                os.remove(self.LOCK_FILE)
        except Exception as e:
            logger.error("scheduler_lock_release_failed", error=str(e))

    def _auto_publish(self) -> None:
        """Publish already-approved items after a pipeline run. Failures are logged, not raised,
        so a Telegram/publication issue never takes down the scheduler loop."""
        if not getattr(settings, "SCHEDULER_AUTO_PUBLISH_ENABLED", False):
            return
        try:
            publish_limit = getattr(settings, "SCHEDULER_PUBLISH_LIMIT", 10)
            stats = PublicationService(self.db).publish_batch(limit=publish_limit)
            logger.info("scheduler_auto_publish_completed", stats=stats)
        except Exception as e:
            logger.error("scheduler_auto_publish_failed", error=str(e))

    def run_once(self, limit: int = 10, source_name: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
        """Запуск одного прохода пайплайна с контролем блокировок."""
        if not settings.SCHEDULER_ENABLED and not dry_run:
            logger.info("scheduler_disabled_in_config")
            return {"status": "disabled"}

        logger.info("scheduler_run_started", limit=limit, source_name=source_name, dry_run=dry_run)

        if not dry_run:
            self.acquire_lock()

        try:
            summary = self.orchestrator.run_pipeline(
                limit=limit,
                only_source_name=source_name,
                dry_run=dry_run
            )
            logger.info("scheduler_run_completed", status=summary.get("status"))
            if not dry_run:
                self._auto_publish()
            return summary
        except Exception as e:
            logger.error("scheduler_run_failed", error=str(e))
            raise
        finally:
            if not dry_run:
                self.release_lock()

    def run_daemon(self, interval_minutes: int = 60, limit: int = 10, source_name: Optional[str] = None, dry_run: bool = False) -> None:
        """Запуск периодического шедулера (бесконечный цикл с graceful shutdown)."""
        logger.info("scheduler_daemon_started", interval_minutes=interval_minutes, limit=limit, source_name=source_name, dry_run=dry_run)
        self._is_running = True
        
        self._setup_signals()

        interval_seconds = interval_minutes * 60
        
        while not self._stop_event.is_set():
            try:
                sources = self.get_active_sources()
                logger.info("scheduler_daemon_tick", active_sources=[s.name for s in sources])
                
                self.run_once(limit=limit, source_name=source_name, dry_run=dry_run)
            except Exception as e:
                logger.error("scheduler_daemon_tick_error", error=str(e))
                
            logger.info("scheduler_daemon_sleeping", seconds=interval_seconds)
            if self._stop_event.wait(interval_seconds):
                break
                
        logger.info("scheduler_daemon_stopped")
        self._is_running = False

    def stop(self) -> None:
        """Graceful остановка шедулера."""
        logger.info("scheduler_graceful_shutdown_requested")
        self._stop_event.set()

    def _setup_signals(self) -> None:
        """Настройка обработки системных сигналов SIGINT/SIGTERM для graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info("scheduler_signal_received", signal=signum)
            self.stop()
            
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
