"""Read-only feedback review commands."""
import argparse

from sqlalchemy import func

from app.database.models import UserFeedback, UserPreference
from app.database.session import SessionLocal
from app.database.repositories import UserFeedbackRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="Review persisted Telegram feedback")
    parser.add_argument("--favorites", type=int, metavar="USER_ID")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    if not args.favorites and not args.stats:
        parser.error("choose --favorites USER_ID or --stats")

    db = SessionLocal()
    try:
        if args.favorites:
            for feedback in UserFeedbackRepository(db).list_favorites(args.favorites):
                print(f"publication_id={feedback.publication_id} reaction={feedback.reaction} hidden={feedback.is_hidden}")
        if args.stats:
            reactions = db.query(UserFeedback.reaction, func.count(UserFeedback.id)).group_by(UserFeedback.reaction).all()
            print("feedback", {str(reaction): count for reaction, count in reactions})
            print("preferences", db.query(func.count(UserPreference.id)).scalar())
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
