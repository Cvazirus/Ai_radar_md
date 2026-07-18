"""Run allowlisted Telegram moderation long polling."""
from app.config import settings
from app.database.session import SessionLocal
from app.publishers.telegram import TelegramPublisher
from app.services.moderation_decision_service import ModerationDecisionService
from app.services.moderation_telegram_dispatch_service import ModerationTelegramDispatchService
from app.services.telegram_moderation_polling_service import TelegramModerationPollingService
from app.publishers.telegram_moderation import TelegramModerationPublisher


def main() -> int:
    if not settings.TELEGRAM_MODERATION_ENABLED:
        return 0
    valid_allowlist = any(value.strip().isdigit() and int(value.strip()) > 0 for value in settings.TELEGRAM_MODERATION_ALLOWED_USER_IDS.split(","))
    if settings.TELEGRAM_MODERATION_CALLBACK_PREFIX != "moderation" or not valid_allowlist:
        return 2
    try:
        int(settings.TELEGRAM_MODERATION_CHAT_ID)
    except (TypeError, ValueError):
        return 2
    db = SessionLocal()
    publisher = TelegramPublisher(
        bot_token=settings.TELEGRAM_MODERATION_BOT_TOKEN,
        chat_id=settings.TELEGRAM_MODERATION_CHAT_ID,
        max_retries=0,
    )
    try:
        moderation_publisher = TelegramModerationPublisher(publisher, chat_id=settings.TELEGRAM_MODERATION_CHAT_ID)
        dispatcher = ModerationTelegramDispatchService(db, moderation_publisher)
        TelegramModerationPollingService(publisher, ModerationDecisionService(db)).run_forever(
            before_poll=dispatcher.dispatch_pending,
        )
    finally:
        publisher.close()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
