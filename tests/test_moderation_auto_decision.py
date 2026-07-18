from unittest.mock import MagicMock, patch

import pytest

from app.database.models import ItemStatus, ModerationDecision, ModerationPriority, ModerationQueue, ModerationQueueStatus
from app.config import settings
from app.llm.schemas import ModerationDecisionResult
from app.services.moderation_service import ModerationService


def approved_result(decision=ModerationDecision.priority_review, blocking_reasons=None):
    return ModerationDecisionResult(
        item_id=1,
        analysis_id=1,
        decision=decision,
        priority=ModerationPriority.high,
        decision_score=8.7,
        blocking_reasons=blocking_reasons or [],
        decision_reasons={},
        warnings=[],
        rules_version="1.0",
        eligible_for_queue=(decision != ModerationDecision.blocked),
    )


def make_service_with_new_queue_item(monkeypatch, auto_enabled: bool, result: ModerationDecisionResult):
    monkeypatch.setattr(settings, "MODERATION_AUTO_DECISION_ENABLED", auto_enabled)

    db_mock = MagicMock()
    service = ModerationService(db_mock)

    item = MagicMock()
    item.id = 1
    item.status = ItemStatus.analyzed

    analysis = MagicMock()
    analysis.id = 1
    analysis.item_id = 1

    service.analysis_repo.get_by_id = MagicMock(return_value=analysis)
    service.item_repo.get = MagicMock(return_value=item)
    service.queue_repo.get_by_analysis_id = MagicMock(return_value=None)
    service.log_repo.create = MagicMock()
    service.queue_repo.create = MagicMock(side_effect=lambda q: q)

    db_mock.query.return_value.filter.return_value.all.return_value = []

    with patch("app.services.moderation_service.evaluate_item_moderation", return_value=result):
        service.moderate_analysis(analysis_id=1, force_recalculate=False)

    created_queue = service.queue_repo.create.call_args[0][0]
    return service, item, created_queue


def test_auto_decision_disabled_by_default_leaves_item_pending(monkeypatch):
    _, item, queue = make_service_with_new_queue_item(monkeypatch, auto_enabled=False, result=approved_result())

    assert queue.queue_status == ModerationQueueStatus.pending
    assert item.status == ItemStatus.analyzed


def test_auto_decision_approves_non_blocked_result_when_enabled(monkeypatch):
    service, item, queue = make_service_with_new_queue_item(
        monkeypatch, auto_enabled=True, result=approved_result(decision=ModerationDecision.digest_candidate)
    )

    assert queue.queue_status == ModerationQueueStatus.approved
    assert item.status == ItemStatus.approved
    assert queue.reviewed_by == "system-auto-policy"

    log_actions = [call.args[0].action for call in service.log_repo.create.call_args_list] + [
        call.args[0].action for call in service.db.add.call_args_list if hasattr(call.args[0], "action")
    ]
    assert "auto_approve" in log_actions


def test_auto_decision_rejects_blocked_result_when_enabled(monkeypatch):
    service, item, queue = make_service_with_new_queue_item(
        monkeypatch,
        auto_enabled=True,
        result=approved_result(decision=ModerationDecision.blocked, blocking_reasons=["low_confidence"]),
    )

    assert queue.queue_status == ModerationQueueStatus.rejected
    assert item.status == ItemStatus.rejected

    log_entries = [call.args[0] for call in service.db.add.call_args_list if hasattr(call.args[0], "action")]
    assert any(entry.action == "auto_reject" and "low_confidence" in entry.reason for entry in log_entries)


def test_auto_decision_skips_when_transition_not_allowed(monkeypatch):
    monkeypatch.setattr(settings, "MODERATION_AUTO_DECISION_ENABLED", True)

    db_mock = MagicMock()
    service = ModerationService(db_mock)
    item = MagicMock()
    item.id = 1
    item.status = ItemStatus.published

    queue = MagicMock(spec=ModerationQueue)
    queue.id = 42
    queue.queue_status = ModerationQueueStatus.cancelled

    service._apply_auto_decision(queue, item, approved_result())

    # cancelled -> approved is not an allowed transition; nothing should change.
    assert queue.queue_status == ModerationQueueStatus.cancelled
    assert item.status == ItemStatus.published


def test_force_recalculate_applies_auto_decision_too(monkeypatch):
    monkeypatch.setattr(settings, "MODERATION_AUTO_DECISION_ENABLED", True)

    db_mock = MagicMock()
    service = ModerationService(db_mock)

    item = MagicMock()
    item.id = 1
    item.status = ItemStatus.analyzed
    analysis = MagicMock()
    analysis.id = 1
    analysis.item_id = 1

    service.analysis_repo.get_by_id = MagicMock(return_value=analysis)
    service.item_repo.get = MagicMock(return_value=item)
    service.log_repo.create = MagicMock()

    existing_queue = MagicMock(spec=ModerationQueue)
    existing_queue.id = 123
    existing_queue.queue_status = ModerationQueueStatus.rejected
    service.queue_repo.get_by_analysis_id = MagicMock(return_value=existing_queue)

    db_mock.query.return_value.filter.return_value.all.return_value = []

    result = approved_result(decision=ModerationDecision.manual_review)
    with patch("app.services.moderation_service.evaluate_item_moderation", return_value=result):
        service.moderate_analysis(analysis_id=1, force_recalculate=True, force_reason="re-run")

    # force_recalculate resets to pending first, then auto-decision should approve it.
    assert existing_queue.queue_status == ModerationQueueStatus.approved
    assert item.status == ItemStatus.approved
