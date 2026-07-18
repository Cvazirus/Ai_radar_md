from pathlib import Path


def test_moderation_boundaries_are_kept():
    root = Path(__file__).resolve().parents[1]
    decision = (root / "app/services/moderation_decision_service.py").read_text()
    polling = (root / "app/services/telegram_moderation_polling_service.py").read_text()
    publisher = (root / "app/publishers/telegram_moderation.py").read_text()
    moderation_service = (root / "app/services/moderation_service.py").read_text()
    assert "TelegramPublisher" not in decision
    assert "app.publishers" not in decision
    assert "PersonalRankingService" not in polling
    assert "FeedbackService" not in polling
    assert "app.database" not in publisher
    assert "existing.telegram_chat_id = None" in moderation_service
    assert "existing.telegram_dispatch_started_at = None" in moderation_service
    assert "values(is_active=False)" in moderation_service
    for path in [
        "app/services/pipeline_orchestrator.py",
        "app/services/personal_ranking_service.py",
        "app/services/feedback_service.py",
    ]:
        assert "telegram_moderation" not in (root / path).read_text()


def test_moderation_migration_is_additive_and_reversible():
    root = Path(__file__).resolve().parents[1]
    migrations = list((root / "migrations/versions").glob("*_telegram_moderation_publisher.py"))
    assert len(migrations) == 1
    source = migrations[0].read_text()
    assert 'down_revision: Union[str, Sequence[str], None] = "d9e4f8a1b2c3"' in source
    assert "telegram_chat_id" in source
    assert "telegram_message_id" in source
    assert "telegram_moderation_update_receipts" in source
    assert "telegram_moderation_messages" in source
    assert "ondelete=\"SET NULL\"" in source
    assert "def upgrade" in source and "def downgrade" in source
