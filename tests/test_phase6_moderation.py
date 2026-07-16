import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from app.config import settings
from app.database.models import (
    Item, ItemAnalysis, Source, AnalysisStatus, DuplicateRelation,
    RelationType, ModerationQueue, ModerationQueueStatus, ModerationPriority,
    ModerationDecision
)
from app.pipeline.moderation_rules import evaluate_item_moderation
from app.pipeline.moderation_state_machine import is_transition_allowed
from app.services.moderation_service import ModerationService
from app.database.repositories import ModerationQueueRepository, ModerationDecisionLogRepository

# Helper to create mock objects
def create_mock_item(item_id=1, title="Test title", url="https://example.com/article", status="collected"):
    item = MagicMock(spec=Item)
    item.id = item_id
    item.title = title
    item.url = url
    item.raw_text = "This is some test raw text for verification."
    item.published_at = datetime.now(timezone.utc) - timedelta(days=5)
    item.collected_at = datetime.now(timezone.utc) - timedelta(days=5)
    item.status = status
    item.metadata_json = {}
    item.source = MagicMock(spec=Source)
    item.source.trust_level = 1
    return item

def create_mock_analysis(analysis_id=1, item_id=1, status="success", score=7.5):
    analysis = MagicMock(spec=ItemAnalysis)
    analysis.id = analysis_id
    analysis.item_id = item_id
    analysis.status = status
    analysis.summary_ru = "Это краткое описание на русском языке."
    analysis.what_is_new = "Добавлена новая фича в систему."
    analysis.practical_use = "Можно использовать для автоматизации процессов."
    analysis.category = "agent"
    analysis.confidence = 0.8
    analysis.total_score = score
    analysis.relevance_score = 8
    analysis.is_primary_source = False
    analysis.is_promotional = False
    analysis.source_claims = []
    analysis.uncertainties = []
    analysis.prompt_version = "phase5-v1"
    analysis.input_hash = "abc123hash"
    return analysis

# --- 1. Blocking Rules Tests ---

def test_blocked_by_status():
    item = create_mock_item()
    analysis = create_mock_analysis(status="failed")
    res = evaluate_item_moderation(item, analysis)
    assert res.decision == ModerationDecision.blocked
    assert "analysis_not_success" in res.blocking_reasons

def test_blocked_by_summary():
    item = create_mock_item()
    analysis = create_mock_analysis()
    analysis.summary_ru = ""
    res = evaluate_item_moderation(item, analysis)
    assert res.decision == ModerationDecision.blocked
    assert "missing_summary" in res.blocking_reasons

def test_blocked_by_confidence():
    item = create_mock_item()
    analysis = create_mock_analysis()
    analysis.confidence = 0.3
    res = evaluate_item_moderation(item, analysis)
    assert res.decision == ModerationDecision.blocked
    assert "low_confidence" in res.blocking_reasons

def test_blocked_by_invalid_claims():
    item = create_mock_item()
    analysis = create_mock_analysis()
    # claim with invalid/missing evidence
    claim = {"claim": "Fact A", "evidence_text": "Not found in text", "evidence_type": "direct_quote", "confidence": 1.0}
    analysis.source_claims = [claim]
    res = evaluate_item_moderation(item, analysis)
    assert res.decision == ModerationDecision.blocked
    assert "invalid_claims" in res.blocking_reasons

def test_blocked_by_high_uncertainty():
    item = create_mock_item()
    analysis = create_mock_analysis()
    analysis.uncertainties = [{"field": "credibility", "reason": "Weak source", "severity": "high"}]
    res = evaluate_item_moderation(item, analysis)
    assert res.decision == ModerationDecision.blocked
    assert "high_uncertainty" in res.blocking_reasons

def test_blocked_by_exact_duplicate():
    item = create_mock_item(status="duplicate")
    analysis = create_mock_analysis()
    res = evaluate_item_moderation(item, analysis)
    assert res.decision == ModerationDecision.blocked
    assert "exact_duplicate" in res.blocking_reasons

# --- 2. Score Calculations & Bonuses/Penalties ---

def test_archive_decision():
    item = create_mock_item()
    analysis = create_mock_analysis(score=4.0)
    res = evaluate_item_moderation(item, analysis)
    assert res.decision == ModerationDecision.archive
    assert res.priority == ModerationPriority.low

def test_digest_candidate_decision():
    item = create_mock_item()
    analysis = create_mock_analysis(score=6.0)
    analysis.category = "news"
    res = evaluate_item_moderation(item, analysis)
    assert res.decision == ModerationDecision.digest_candidate
    assert res.priority == ModerationPriority.normal

def test_manual_review_decision():
    item = create_mock_item()
    analysis = create_mock_analysis(score=7.5)
    analysis.category = "news"
    res = evaluate_item_moderation(item, analysis)
    assert res.decision == ModerationDecision.manual_review
    assert res.priority == ModerationPriority.normal

def test_priority_review_decision():
    item = create_mock_item()
    analysis = create_mock_analysis(score=8.8)
    res = evaluate_item_moderation(item, analysis)
    assert res.decision == ModerationDecision.priority_review
    assert res.priority == ModerationPriority.high

def test_primary_source_bonus():
    item = create_mock_item(url="https://github.com/openai/gpt-3")
    analysis = create_mock_analysis(score=7.0)
    analysis.is_primary_source = True
    # evaluated decision_score should be total_score + primary_source_bonus (0.5) + category_bonus (0.5 for agent)
    res = evaluate_item_moderation(item, analysis)
    assert res.decision_score == 8.0 # 7.0 + 0.5 + 0.5

def test_category_bonus():
    item = create_mock_item()
    analysis = create_mock_analysis(score=7.0)
    analysis.is_primary_source = False # source bonus = 0.0
    
    # 1. Agent category (+0.5)
    analysis.category = "agent"
    res1 = evaluate_item_moderation(item, analysis)
    assert res1.decision_reasons["category_bonus"] == 0.5

    # 2. Model release category (+0.3)
    analysis.category = "model_release"
    res2 = evaluate_item_moderation(item, analysis)
    assert res2.decision_reasons["category_bonus"] == 0.3

def test_freshness_bonus():
    item = create_mock_item()
    analysis = create_mock_analysis(score=7.0)
    analysis.category = "other" # category bonus = 0.0
    analysis.is_primary_source = False # source bonus = 0.0
    
    # Fresh item (< 24 hours) -> +0.5
    item.published_at = datetime.now(timezone.utc) - timedelta(hours=10)
    res1 = evaluate_item_moderation(item, analysis)
    assert res1.decision_reasons["freshness_bonus"] == 0.5

    # Older item (< 72 hours) -> +0.3
    item.published_at = datetime.now(timezone.utc) - timedelta(hours=48)
    res2 = evaluate_item_moderation(item, analysis)
    assert res2.decision_reasons["freshness_bonus"] == 0.3

def test_duplicate_penalty():
    item = create_mock_item()
    analysis = create_mock_analysis(score=7.0)
    analysis.category = "other"
    analysis.is_primary_source = False
    
    rel = MagicMock(spec=DuplicateRelation)
    rel.item_id = item.id
    rel.duplicate_of_item_id = 999
    rel.relation_type = RelationType.cross_source_story

    res = evaluate_item_moderation(item, analysis, [rel])
    assert res.decision_reasons["duplicate_penalty"] == 1.0
    assert res.decision_score == 6.0 # 7.0 - 1.0

def test_uncertainty_penalty():
    item = create_mock_item()
    analysis = create_mock_analysis(score=7.0)
    analysis.category = "other"
    analysis.is_primary_source = False
    
    # Medium uncertainty -> -0.5
    analysis.uncertainties = [{"field": "credibility", "reason": "Weak source", "severity": "medium"}]
    res = evaluate_item_moderation(item, analysis)
    assert res.decision_reasons["uncertainty_penalty"] == 0.5
    assert res.decision_score == 6.5

def test_score_clamping():
    item = create_mock_item()
    analysis = create_mock_analysis(score=9.9)
    # 9.9 + 0.5 (primary) + 0.5 (agent) + 0.5 (fresh) = 11.4 -> clamped to 10.0
    res = evaluate_item_moderation(item, analysis)
    assert res.decision_score == 10.0

def test_legacy_analysis_handling():
    item = create_mock_item()
    analysis = create_mock_analysis()
    analysis.prompt_version = "legacy"
    
    # 1. Allow legacy = False -> blocked
    with patch("app.config.settings.MODERATION_ALLOW_LEGACY_ANALYSIS", False):
        res1 = evaluate_item_moderation(item, analysis)
        assert res1.decision == ModerationDecision.blocked
        assert "legacy_analysis" in res1.blocking_reasons

    # 2. Allow legacy = True -> not blocked
    with patch("app.config.settings.MODERATION_ALLOW_LEGACY_ANALYSIS", True):
        res2 = evaluate_item_moderation(item, analysis)
        assert res2.decision != ModerationDecision.blocked
        assert "legacy_analysis" not in res2.blocking_reasons

# --- 3. State Machine Tests ---

def test_state_transitions():
    # Allowed
    assert is_transition_allowed(None, ModerationQueueStatus.pending) is True
    assert is_transition_allowed(ModerationQueueStatus.pending, ModerationQueueStatus.approved) is True
    assert is_transition_allowed(ModerationQueueStatus.in_review, ModerationQueueStatus.rejected) is True
    assert is_transition_allowed(ModerationQueueStatus.approved, ModerationQueueStatus.cancelled) is True
    
    # Forbidden
    assert is_transition_allowed(ModerationQueueStatus.approved, ModerationQueueStatus.in_review) is False
    assert is_transition_allowed(ModerationQueueStatus.rejected, ModerationQueueStatus.approved) is False
    
    # Rejected -> Pending transition requires a reason
    assert is_transition_allowed(ModerationQueueStatus.rejected, ModerationQueueStatus.pending, reason="") is False
    assert is_transition_allowed(ModerationQueueStatus.rejected, ModerationQueueStatus.pending, reason="re-review requested") is True

# --- 4. Service and Repositories Mocking Tests ---

@patch("app.services.moderation_service.evaluate_item_moderation")
def test_queue_idempotency(mock_eval):
    db_mock = MagicMock()
    service = ModerationService(db_mock)
    
    # Mock repositories
    service.analysis_repo.get_by_id = MagicMock(return_value=create_mock_analysis())
    # Mock existing queue item
    existing_queue = MagicMock(spec=ModerationQueue)
    existing_queue.id = 123
    existing_queue.analysis_id = 1
    existing_queue.decision = "manual_review"
    existing_queue.priority = "normal"
    existing_queue.decision_score = 7.5
    existing_queue.blocking_reasons = []
    existing_queue.decision_reasons = {}
    existing_queue.warnings = []
    
    service.queue_repo.get_by_analysis_id = MagicMock(return_value=existing_queue)
    
    # Call service
    res = service.moderate_analysis(analysis_id=1, force_recalculate=False)
    
    # Verification: should skip evaluation and return mapped existing
    mock_eval.assert_not_called()
    assert res.analysis_id == 1
    assert res.decision == "manual_review"

@patch("app.services.moderation_service.evaluate_item_moderation")
def test_force_recalculate_preserves_history(mock_eval):
    db_mock = MagicMock()
    service = ModerationService(db_mock)
    
    analysis = create_mock_analysis()
    item = create_mock_item()
    service.analysis_repo.get_by_id = MagicMock(return_value=analysis)
    service.item_repo.get = MagicMock(return_value=item)
    
    existing_queue = MagicMock(spec=ModerationQueue)
    existing_queue.id = 123
    existing_queue.queue_status = ModerationQueueStatus.approved
    service.queue_repo.get_by_analysis_id = MagicMock(return_value=existing_queue)
    
    # Mock evaluation result
    eval_result = evaluate_item_moderation(item, analysis)
    mock_eval.return_value = eval_result
    
    # Mock decision log creation
    service.log_repo.create = MagicMock()
    
    # Call service with force_recalculate=True
    res = service.moderate_analysis(analysis_id=1, force_recalculate=True, force_reason="Recalculating rules")
    
    # Verification: should call evaluate and log recalculation action
    mock_eval.assert_called()
    service.log_repo.create.assert_called()
    log_arg = service.log_repo.create.call_args[0][0]
    assert log_arg.action == "recalculate"
    assert log_arg.previous_status == ModerationQueueStatus.approved
    assert log_arg.new_status == ModerationQueueStatus.pending

def test_approve_does_not_create_publication():
    db_mock = MagicMock()
    service = ModerationService(db_mock)
    
    existing_queue = MagicMock(spec=ModerationQueue)
    existing_queue.id = 123
    existing_queue.queue_status = ModerationQueueStatus.pending
    db_mock.query.return_value.filter.return_value.first.return_value = existing_queue
    service.log_repo.create = MagicMock()
    
    # Transition to approved
    from scripts.review_moderation import handle_transition
    args = MagicMock()
    args.queue_id = 123
    args.reviewer = "cvazi"
    args.reason = "Approved"
    
    handle_transition(args, db_mock, ModerationQueueStatus.approved, "approve")
    
    # Verify: status is updated, but no publication is created
    assert any(call[0][0] == existing_queue for call in db_mock.add.call_args_list)
    assert existing_queue.queue_status == ModerationQueueStatus.approved
    
    # Check that db.add was NOT called on a Publication instance
    for call in db_mock.add.call_args_list:
        added_obj = call[0][0]
        assert not added_obj.__class__.__name__ == "Publication"

def test_reject_does_not_delete_item():
    db_mock = MagicMock()
    service = ModerationService(db_mock)
    
    existing_queue = MagicMock(spec=ModerationQueue)
    existing_queue.id = 123
    existing_queue.queue_status = ModerationQueueStatus.pending
    db_mock.query.return_value.filter.return_value.first.return_value = existing_queue
    service.log_repo.create = MagicMock()
    
    # Transition to rejected
    from scripts.review_moderation import handle_transition
    args = MagicMock()
    args.queue_id = 123
    args.reviewer = "cvazi"
    args.reason = "Duplicate secondary source"
    
    handle_transition(args, db_mock, ModerationQueueStatus.rejected, "reject")
    
    # Verify: status updated, db.delete not called on items
    assert existing_queue.queue_status == ModerationQueueStatus.rejected
    db_mock.delete.assert_not_called()

def test_batch_moderation_error_handling():
    db_mock = MagicMock()
    service = ModerationService(db_mock)
    
    # Two analyses
    a1 = create_mock_analysis(analysis_id=10)
    a2 = create_mock_analysis(analysis_id=20)
    service.db.query().filter().limit().all = MagicMock(return_value=[a1, a2])
    
    # moderate_analysis throws error on first, succeeds on second
    service.moderate_analysis = MagicMock(side_effect=[Exception("DB error"), MagicMock()])
    
    # Run batch
    results = service.moderate_batch()
    
    # Verification: should catch first error, but process second
    assert len(results) == 1
    assert service.moderate_analysis.call_count == 2
