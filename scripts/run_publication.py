#!/usr/bin/env python
import argparse
import json
import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from app.database.session import SessionLocal
from app.services.publication_service import PublicationService


def main():
    parser = argparse.ArgumentParser(description="AI Radar Publication Engine CLI")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry run without database modification")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of items to process")
    parser.add_argument("--item-id", type=int, default=None, help="Process a single item by its ID")
    parser.add_argument("--resume", action="store_true", help="Resume unfinished publications (draft/ready/publishing)")
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed publications")

    args = parser.parse_args()

    db = SessionLocal()
    try:
        service = PublicationService(db)
        print("Starting Publication Engine...")
        stats = service.publish_batch(
            limit=args.limit,
            item_id=args.item_id,
            resume=args.resume,
            retry_failed=args.retry_failed,
            dry_run=args.dry_run
        )
        print(f"Publication run finished: {json.dumps(stats, indent=2)}")
    except Exception as e:
        print(f"Critical publication error: {str(e)}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
