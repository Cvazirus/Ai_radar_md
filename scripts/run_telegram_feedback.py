"""Run allowlisted Telegram feedback long polling."""
from app.config import settings
from app.database.session import SessionLocal
from app.publishers.telegram import TelegramPublisher
from app.services.feedback_service import FeedbackService
from app.services.telegram_feedback_polling_service import TelegramFeedbackPollingService


def main() -> int:
    if not settings.TELEGRAM_FEEDBACK_ENABLED:
        return 0
    db = SessionLocal()
    publisher = TelegramPublisher()
    try:
        TelegramFeedbackPollingService(publisher, FeedbackService(db)).run_forever()
    finally:
        publisher.close()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
