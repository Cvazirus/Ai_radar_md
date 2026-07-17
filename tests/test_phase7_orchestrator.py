import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from sqlalchemy.orm import Session
from app.services.pipeline_orchestrator import PipelineOrchestrator
from app.database.models import (
    PipelineRun, PipelineRunStatus, Item, ItemStatus, ItemAnalysis,
    AnalysisStatus, ModerationQueue, ModerationQueueStatus
)


@pytest.fixture
def mock_db():
    db = MagicMock(spec=Session)
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    db.query.return_value.filter.return_value.count.return_value = 0
    return db


@pytest.fixture
def orchestrator(mock_db):
    return PipelineOrchestrator(mock_db)


def test_dry_run(orchestrator: PipelineOrchestrator):
    summary = orchestrator.run_pipeline(dry_run=True, limit=5)
    assert summary["run_id"] == "dry_run"
    assert summary["status"] == "completed"
    assert summary["dry_run"] is True
    assert "fetch" in summary["steps"]
    assert "normalize" in summary["steps"]
    assert "analysis" in summary["steps"]
    assert "validation" in summary["steps"]
    assert "moderation" in summary["steps"]
    assert "review" in summary["steps"]


def test_from_step_to_step(orchestrator: PipelineOrchestrator):
    summary = orchestrator.run_pipeline(dry_run=True, from_step="normalize", to_step="validation")
    assert "fetch" not in summary["steps"]
    assert "normalize" in summary["steps"]
    assert "analysis" in summary["steps"]
    assert "validation" in summary["steps"]
    assert "moderation" not in summary["steps"]
    assert "review" not in summary["steps"]


def test_invalid_steps(orchestrator: PipelineOrchestrator):
    with pytest.raises(ValueError):
        orchestrator.run_pipeline(from_step="invalid_step")
    with pytest.raises(ValueError):
        orchestrator.run_pipeline(to_step="invalid_step")
    with pytest.raises(ValueError):
        orchestrator.run_pipeline(from_step="moderation", to_step="normalize")


@patch("app.services.pipeline_orchestrator.CollectionService")
@patch("app.services.pipeline_orchestrator.AnalysisService")
@patch("app.services.pipeline_orchestrator.ModerationService")
@patch("app.services.pipeline_orchestrator.NormalizeService")
@patch("app.services.pipeline_orchestrator.ValidationService")
def test_full_pipeline_run(
    mock_val_service, mock_norm_service, mock_mod_service, mock_anal_service, mock_col_service,
    orchestrator: PipelineOrchestrator, mock_db
):
    # Setup mocks
    mock_col = MagicMock()
    mock_col.run_rss_collection.return_value = {"items_created": 5, "items_skipped": 0, "sources_failed": 0}
    mock_col_service.return_value = mock_col

    mock_norm = MagicMock()
    mock_norm.normalize_batch.return_value = {"processed": 5, "skipped": 0, "failed": 0, "errors": []}
    mock_norm_service.return_value = mock_norm

    mock_anal = MagicMock()
    mock_anal.analyze_batch.return_value = {"success": 3, "skipped": 2, "failed": 0, "invalid": 0}
    mock_anal_service.return_value = mock_anal

    mock_val = MagicMock()
    mock_val.validate_batch.return_value = {"processed": 3, "skipped": 0, "failed": 0, "errors": []}
    mock_val_service.return_value = mock_val

    mock_mod = MagicMock()
    mock_mod.moderate_batch.return_value = [MagicMock()]
    mock_mod_service.return_value = mock_mod

    # Mock queue count
    mock_db.query.return_value.filter.return_value.count.return_value = 2

    # Execute
    summary = orchestrator.run_pipeline(limit=5)
    
    assert summary["status"] == str(PipelineRunStatus.completed)
    assert isinstance(summary["items_processed"], int)
    assert summary["items_failed"] == 0
    assert "fetch" in summary["steps"]
    assert "review" in summary["steps"]


@patch("app.services.pipeline_orchestrator.CollectionService")
def test_pipeline_step_error_continuation(
    mock_col_service, orchestrator: PipelineOrchestrator, mock_db
):
    # If fetch step fails completely, the pipeline run status should be failed
    mock_col = MagicMock()
    mock_col.run_rss_collection.side_effect = Exception("Fetch error")
    mock_col_service.return_value = mock_col

    summary = orchestrator.run_pipeline(to_step="fetch")
    assert summary["status"] == str(PipelineRunStatus.failed)
    assert "fetch" in summary["steps"]
    assert summary["steps"]["fetch"]["failed"] == 1
    assert "Fetch error" in summary["steps"]["fetch"]["errors"][0]


def test_resume_pipeline(orchestrator: PipelineOrchestrator, mock_db):
    # Mock resume lookup returning a failed run
    failed_run = MagicMock(spec=PipelineRun)
    failed_run.run_id = "run_failed_123"
    failed_run.current_step = "validation"
    
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = failed_run

    summary = orchestrator.run_pipeline(resume=True, dry_run=True)
    assert summary["run_id"] == "dry_run"
