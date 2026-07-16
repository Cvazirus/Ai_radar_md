#!/usr/bin/env python
import argparse
import json
import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from app.database.session import SessionLocal
from app.services.pipeline_orchestrator import PipelineOrchestrator


def main():
    parser = argparse.ArgumentParser(description="AI Radar Pipeline Orchestrator CLI")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without DB modifications")
    parser.add_argument("--limit", type=int, default=10, help="Max items to process per step")
    parser.add_argument("--from-step", type=str, default=None, help="Start step of the pipeline")
    parser.add_argument("--to-step", type=str, default=None, help="End step of the pipeline")
    parser.add_argument("--resume", action="store_true", help="Resume from last failed step")
    parser.add_argument("--item-id", type=int, default=None, help="Target a specific item ID")

    args = parser.parse_args()

    db = SessionLocal()
    try:
        orchestrator = PipelineOrchestrator(db)
        summary = orchestrator.run_pipeline(
            limit=args.limit,
            from_step=args.from_step,
            to_step=args.to_step,
            resume=args.resume,
            item_id=args.item_id,
            dry_run=args.dry_run
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "failed", "errors": [str(e)]}, indent=2, ensure_ascii=False))
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
