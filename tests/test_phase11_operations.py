"""Tests for Phase 11 — Operations & Monitoring."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone
from app.database.models import (
    ItemStatus, ItemAnalysis, AnalysisStatus, CategoryEnum,
    Publication, PublicationStatus,
    ModerationQueue, ModerationQueueStatus, ModerationDecision, ModerationPriority,
    CollectionRun, PipelineRun, Source
)
from app.services.operations_service import OperationsService


# === HEALTH CALCULATION ===

def test_health_healthy():
    """Healthy when all components are OK."""
    mock_db = MagicMock()
    service = OperationsService(mock_db)

    # Mock all queries to return reasonable values
    mock_db.query.return_value.filter.return_value.count.return_value = 0
    mock_db.query.return_value.count.return_value = 100
    mock_db.query.return_value.group_by.return_value.all.return_value = [
        (ItemStatus.collected, 90),
        (ItemStatus.analyzed, 10),
    ]

    status = service.get_full_status()
    assert status["health"]["status"] in ("healthy", "warning")
    assert status["health"]["score"] >= 70


def test_health_degraded():
    """Degraded when pipeline failed."""
    mock_db = MagicMock()
    service = OperationsService(mock_db)

    # Make pipeline appear failed
    mock_pipeline = MagicMock()
    mock_pipeline.status.value = "failed"
    mock_pipeline.started_at = None
    mock_pipeline.finished_at = None
    mock_pipeline.duration_ms = None
    mock_pipeline.items_processed = None
    mock_pipeline.items_failed = None
    mock_pipeline.run_id = "test-run"
    mock_db.query.return_value.order_by.return_value.first.return_value = mock_pipeline
    mock_db.query.return_value.filter.return_value.count.return_value = 0
    mock_db.query.return_value.count.return_value = 100
    mock_db.query.return_value.group_by.return_value.all.return_value = [
        (ItemStatus.collected, 100),
    ]

    status = service.get_full_status()
    assert status["health"]["score"] < 90


# === COMPONENT STATISTICS ===

def test_items_status():
    """Items status returns correct counts."""
    mock_db = MagicMock()
    service = OperationsService(mock_db)

    mock_db.query.return_value.group_by.return_value.all.return_value = [
        (ItemStatus.collected, 50),
        (ItemStatus.analyzed, 30),
        (ItemStatus.duplicate, 5),
    ]

    result = service._get_items_status()
    assert result["total"] == 85
    assert result["by_status"]["collected"] == 50
    assert result["by_status"]["analyzed"] == 30


def test_moderation_status():
    """Moderation status returns correct counts."""
    mock_db = MagicMock()
    service = OperationsService(mock_db)

    # Mock chain for moderation queries
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.count.return_value = 5

    result = service._get_moderation_status()
    assert "total" in result
    assert "pending" in result
    assert "approved" in result
    assert "blocked" in result


def test_publication_status():
    """Publication status returns correct counts."""
    mock_db = MagicMock()
    service = OperationsService(mock_db)

    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.count.return_value = 3

    result = service._get_publication_status()
    assert "total" in result
    assert "draft" in result
    assert "published" in result


# === SUMMARY ===

def test_summary_format():
    """Summary returns formatted string."""
    mock_db = MagicMock()
    service = OperationsService(mock_db)

    mock_db.query.return_value.filter.return_value.count.return_value = 0
    mock_db.query.return_value.count.return_value = 100
    mock_db.query.return_value.group_by.return_value.all.return_value = [
        (ItemStatus.collected, 100),
    ]

    summary = service.get_summary()
    assert "Health:" in summary
    assert "Items:" in summary
    assert "Moderation:" in summary
    assert "Publications:" in summary


# === JSON OUTPUT ===

def test_json_output():
    """Full status can be serialized to JSON."""
    import json
    mock_db = MagicMock()
    service = OperationsService(mock_db)

    mock_db.query.return_value.filter.return_value.count.return_value = 0
    mock_db.query.return_value.count.return_value = 100
    mock_db.query.return_value.group_by.return_value.all.return_value = [
        (ItemStatus.collected, 100),
    ]

    status = service.get_full_status()
    # Should not raise
    json_str = json.dumps(status, default=str)
    assert len(json_str) > 0


# === EMPTY DATABASE ===

def test_empty_database():
    """Operations work with empty database."""
    mock_db = MagicMock()
    service = OperationsService(mock_db)

    mock_db.query.return_value.filter.return_value.count.return_value = 0
    mock_db.query.return_value.count.return_value = 0
    mock_db.query.return_value.group_by.return_value.all.return_value = []

    status = service.get_full_status()
    assert status["items"]["total"] == 0
    assert status["health"]["status"] in ("degraded", "critical")
    assert status["health"]["score"] < 70


# === FAILED SERVICES ===

def test_pipeline_error():
    """Pipeline error is handled gracefully."""
    mock_db = MagicMock()
    service = OperationsService(mock_db)

    # Make pipeline query raise an exception
    mock_db.query.return_value.order_by.return_value.first.side_effect = Exception("DB error")
    mock_db.query.return_value.filter.return_value.count.return_value = 0
    mock_db.query.return_value.count.return_value = 100
    mock_db.query.return_value.group_by.return_value.all.return_value = [
        (ItemStatus.collected, 100),
    ]

    status = service.get_full_status()
    assert "error" in status["pipeline"]


# === DEGRADED STATE ===

def test_degraded_state():
    """System is degraded when health score is low."""
    mock_db = MagicMock()
    service = OperationsService(mock_db)

    # Create a status dict that would result in low health
    test_status = {
        "pipeline": {"last_status": "failed", "running_now": False},
        "scheduler": {"active": False, "lock_file_exists": False},
        "collection": {"failed_runs": 10, "successful_runs": 1},
        "moderation": {"pending": 100, "approved": 0, "blocked": 0},
        "publication": {"failed": 5, "published": 0},
        "items": {"total": 100, "by_status": {"collected": 100}},
    }

    health = service._calculate_health(test_status)
    assert health["score"] < 90
    assert len(health["issues"]) > 0


# === COMPONENT FILTERING ===

def test_component_filtering():
    """Can get status for individual components."""
    mock_db = MagicMock()
    service = OperationsService(mock_db)

    mock_db.query.return_value.filter.return_value.count.return_value = 0
    mock_db.query.return_value.count.return_value = 100
    mock_db.query.return_value.group_by.return_value.all.return_value = [
        (ItemStatus.collected, 100),
    ]

    pipeline = service.get_component_status("pipeline")
    assert "last_run_id" in pipeline or "error" in pipeline

    moderation = service.get_component_status("moderation")
    assert "total" in moderation or "error" in moderation

    unknown = service.get_component_status("unknown")
    assert "error" in unknown


# === OPERATIONS READ-ONLY ===

def test_operations_read_only():
    """OperationsService never writes to database."""
    import inspect
    from app.services import operations_service
    source = inspect.getsource(operations_service)
    # Should not contain write operations
    assert "INSERT" not in source
    assert "UPDATE " not in source
    assert "DELETE" not in source
    assert ".add(" not in source
    assert ".commit(" not in source
