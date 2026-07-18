from pathlib import Path


def test_feedback_boundaries_are_kept():
    root = Path(__file__).resolve().parents[1]
    assert "feedback_service" not in (root / "app/services/pipeline_orchestrator.py").read_text()
    assert "PersonalRankingService" not in (root / "app/services/telegram_feedback_polling_service.py").read_text()
    assert "UserPreference" not in (root / "app/services/publication_service.py").read_text()
    ranking_source = (root / "app/services/personal_ranking_service.py").read_text()
    assert "TelegramPublisher" not in ranking_source and "app.publishers" not in ranking_source
    assert "app.database" not in (root / "app/publishers/telegram.py").read_text()


def test_feedback_migration_is_reversible_and_uses_string_checks():
    root = Path(__file__).resolve().parents[1]
    migration = (root / "migrations/versions/d9e4f8a1b2c3_add_telegram_personal_feedback.py").read_text()
    assert "down_revision" in migration and "cbfeb13f1972" in migration
    assert "BigInteger" in migration
    assert "CheckConstraint" in migration
    assert "def upgrade" in migration and "def downgrade" in migration
    assert "telegram_chat_id" in migration
    assert "alter_column" not in migration
