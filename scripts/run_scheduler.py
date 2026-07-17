#!/usr/bin/env python
import argparse
import json
import sys
import time
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from app.database.session import SessionLocal
from app.services.scheduler_service import SchedulerService


def main():
    parser = argparse.ArgumentParser(description="AI Radar Pipeline Scheduler CLI")
    parser.add_argument("--once", action="store_true", help="Run pipeline once and exit")
    parser.add_argument("--daemon", action="store_true", help="Run scheduler in background/daemon loop")
    parser.add_argument("--interval", type=int, default=None, help="Interval in minutes (overrides config)")
    parser.add_argument("--source", type=str, default=None, help="Process only specific source by name")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode (read-only, no lock)")
    parser.add_argument("--limit", type=int, default=10, help="Max items to process per step")

    args = parser.parse_args()

    if not args.once and not args.daemon:
        parser.print_help()
        print("\nError: Either --once or --daemon must be specified.")
        sys.exit(1)

    db = SessionLocal()
    try:
        scheduler = SchedulerService(db)
        
        if args.once:
            print("Starting single pipeline run...")
            summary = scheduler.run_once(
                limit=args.limit,
                source_name=args.source,
                dry_run=args.dry_run
            )
            print(json.dumps(summary, indent=2, ensure_ascii=False))
        elif args.daemon:
            from app.config import settings
            interval = args.interval or settings.SCHEDULER_INTERVAL_MINUTES
            print(f"Starting scheduler daemon loop (interval: {interval}m)...")
            scheduler.run_daemon(
                interval_minutes=interval,
                limit=args.limit,
                source_name=args.source,
                dry_run=args.dry_run
            )
    except Exception as e:
        print(f"Critical scheduler error: {str(e)}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
