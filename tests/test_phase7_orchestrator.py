import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from sqlalchemy.orm import Session
from app.services.pipeline_orchestrator import PipelineOrchestrator
from app.database.models import (
    PipelineRun, PipelineRunStatus, Item, ItemStatus, ItemAnalysis,
    AnalysisStatus, ModerationQueue, ModerationQueueStatus, ModerationDecision,
    ModerationDecisionLog
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
    assert "approval" in summary["steps"]
    assert "publication" in summary["steps"]


def test_from_step_to_step(orchestrator: PipelineOrchestrator):
    summary = orchestrator.run_pipeline(dry_run=True, from_step="normalize", to_step="validation")
    assert "fetch" not in summary["steps"]
    assert "normalize" in summary["steps"]
    assert "analysis" in summary["steps"]
    assert "validation" in summary["steps"]
    assert "moderation" not in summary["steps"]
    assert "approval" not in summary["steps"]
    assert "publication" not in summary["steps"]


def test_invalid_steps(orchestrator: PipelineOrchestrator):
    with pytest.raises(ValueError):
        orchestrator.run_pipeline(from_step="invalid_step")
    with pytest.raises(ValueError):
        orchestrator.run_pipeline(to_step="invalid_step")
    with pytest.raises(ValueError):
        orchestrator.run_pipeline(from_step="moderation", to_step="normalize")


@patch("app.services.pipeline_orchestrator.PublicationService")
@patch("app.services.pipeline_orchestrator.CollectionService")
@patch("app.services.pipeline_orchestrator.AnalysisService")
@patch("app.services.pipeline_orchestrator.ModerationService")
@patch("app.services.pipeline_orchestrator.NormalizeService")
@patch("app.services.pipeline_orchestrator.ValidationService")
def test_full_pipeline_run(
    mock_val_service, mock_norm_service, mock_mod_service, mock_anal_service, mock_col_service,
    mock_pub_service,
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

    mock_pub = MagicMock()
    mock_pub.publish_batch.return_value = {"processed": 1, "skipped": 0, "failed": 0, "resumed": 0}
    mock_pub_service.return_value = mock_pub

    # Mock queue query (used by both approval's pending lookup and dry-run counts)
    mock_db.query.return_value.filter.return_value.count.return_value = 2
    mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = []

    # Execute
    summary = orchestrator.run_pipeline(limit=5)

    assert summary["status"] == str(PipelineRunStatus.completed)
    assert isinstance(summary["items_processed"], int)
    assert summary["items_failed"] == 0
    assert "fetch" in summary["steps"]
    assert "approval" in summary["steps"]
    assert "publication" in summary["steps"]
    mock_pub.publish_batch.assert_called_once_with(limit=5, item_id=None)


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


@patch("app.services.pipeline_orchestrator.ModerationDecisionLogRepository")
@patch("app.services.pipeline_orchestrator.ModerationQueueRepository")
def test_step_approval_auto_approves_digest_candidate_when_enabled(
    mock_queue_repo_cls, mock_log_repo_cls, orchestrator: PipelineOrchestrator, mock_db, monkeypatch
):
    from app.config import settings
    monkeypatch.setattr(settings, "AUTO_APPROVAL_ENABLED", True)

    queue_item = MagicMock(spec=ModerationQueue)
    queue_item.id = 42
    queue_item.queue_status = ModerationQueueStatus.pending
    queue_item.decision = ModerationDecision.digest_candidate
    mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = [queue_item]

    mock_queue_repo = MagicMock()
    mock_queue_repo_cls.return_value = mock_queue_repo
    mock_log_repo = MagicMock()
    mock_log_repo_cls.return_value = mock_log_repo

    result = orchestrator._step_approval(limit=10, item_id=None)

    assert result == {"processed": 1, "skipped": 0, "failed": 0, "errors": []}
    mock_queue_repo.update_status.assert_called_once_with(42, ModerationQueueStatus.approved, reviewer="auto")
    mock_log_repo.create.assert_called_once()


def test_step_approval_leaves_pending_when_auto_approval_disabled(
    orchestrator: PipelineOrchestrator, mock_db, monkeypatch
):
    from app.config import settings
    monkeypatch.setattr(settings, "AUTO_APPROVAL_ENABLED", False)

    queue_item = MagicMock(spec=ModerationQueue)
    queue_item.id = 42
    queue_item.queue_status = ModerationQueueStatus.pending
    queue_item.decision = ModerationDecision.digest_candidate
    mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = [queue_item]

    result = orchestrator._step_approval(limit=10, item_id=None)

    assert result == {"processed": 0, "skipped": 1, "failed": 0, "errors": []}


@patch("app.services.pipeline_orchestrator.PublicationService")
def test_step_publication_delegates_to_publication_service(
    mock_pub_service_cls, orchestrator: PipelineOrchestrator
):
    mock_pub_service = MagicMock()
    mock_pub_service.publish_batch.return_value = {"processed": 2, "skipped": 1, "failed": 0, "resumed": 0}
    mock_pub_service_cls.return_value = mock_pub_service

    result = orchestrator._step_publication(limit=3, item_id=None)

    mock_pub_service.publish_batch.assert_called_once_with(limit=3, item_id=None)
    assert result == {"processed": 2, "skipped": 1, "failed": 0, "errors": []}
