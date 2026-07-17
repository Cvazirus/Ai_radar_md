import os
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, mock_open
import threading
import time

from app.database.models import Source, PipelineRun, PipelineRunStatus
from app.services.scheduler_service import SchedulerService, PipelineLockError


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    return db


@pytest.fixture
def scheduler(mock_db):
    if os.path.exists(SchedulerService.LOCK_FILE):
        try:
            os.remove(SchedulerService.LOCK_FILE)
        except OSError:
            pass
    return SchedulerService(mock_db)


def test_get_active_sources(scheduler, mock_db):
    source1 = Source(name="Source 1", enabled=True, source_type="rss")
    source2 = Source(name="Source 2", enabled=False, source_type="rss")
    
    mock_db.query.return_value.filter.return_value.all.return_value = [source1]
    
    active_sources = scheduler.get_active_sources()
    assert len(active_sources) == 1
    assert active_sources[0].name == "Source 1"


@patch("app.services.scheduler_service.PipelineOrchestrator.run_pipeline")
def test_run_once(mock_run_pipeline, scheduler):
    mock_run_pipeline.return_value = {"status": "completed"}
    
    summary = scheduler.run_once(limit=5)
    assert summary["status"] == "completed"
    assert mock_run_pipeline.call_count == 1
    assert not os.path.exists(SchedulerService.LOCK_FILE)


def test_dry_run(scheduler):
    with patch.object(scheduler.orchestrator, "run_pipeline") as mock_run:
        mock_run.return_value = {"status": "completed", "dry_run": True}
        summary = scheduler.run_once(dry_run=True)
        assert summary["status"] == "completed"
        assert not os.path.exists(SchedulerService.LOCK_FILE)


def test_lock_prevents_parallel_runs(scheduler, mock_db):
    # 1. Setup DB active lock
    active_run = PipelineRun(run_id="run_active_1", status=PipelineRunStatus.running, started_at=datetime.now(timezone.utc))
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = active_run
    
    with pytest.raises(PipelineLockError):
        scheduler.acquire_lock()
        
    # 2. Setup File lock check
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    with open(SchedulerService.LOCK_FILE, "w") as f:
        f.write(f"{os.getpid()},{time.time()}")
        
    with pytest.raises(PipelineLockError):
        scheduler.acquire_lock()
        
    if os.path.exists(SchedulerService.LOCK_FILE):
        os.remove(SchedulerService.LOCK_FILE)


@patch("app.services.scheduler_service.PipelineOrchestrator.run_pipeline")
def test_daemon_loop_and_graceful_shutdown(mock_run_pipeline, scheduler):
    mock_run_pipeline.return_value = {"status": "completed"}
    
    t = threading.Thread(
        target=scheduler.run_daemon,
        kwargs={"interval_minutes": 1, "limit": 2}
    )
    t.start()
    
    time.sleep(0.5)
    assert scheduler._is_running is True
    
    scheduler.stop()
    t.join(timeout=2)
    
    assert scheduler._is_running is False
    assert not t.is_alive()


@patch("app.services.scheduler_service.PipelineOrchestrator.run_pipeline")
def test_daemon_continues_after_error(mock_run_pipeline, scheduler):
    mock_run_pipeline.side_effect = Exception("Orchestrator error")
    
    with pytest.raises(Exception):
        scheduler.run_once()
        
    t = threading.Thread(
        target=scheduler.run_daemon,
        kwargs={"interval_minutes": 1, "limit": 2}
    )
    t.start()
    
    time.sleep(0.5)
    assert scheduler._is_running is True
    
    scheduler.stop()
    t.join(timeout=2)
    assert scheduler._is_running is False
