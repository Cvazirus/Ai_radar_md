import sys
import argparse
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

import structlog
from app.config import settings
from app.database.session import SessionLocal
from app.database.models import Item, ItemStatus, AnalysisStatus
from app.database.repositories import ItemRepository, AnalysisRepository
from app.pipeline.input_hash import calculate_analysis_input_hash
from app.services.analysis_service import AnalysisService

logger = structlog.get_logger()


def main():
    parser = argparse.ArgumentParser(description="AI Radar Analysis Runner")
    parser.add_argument("--item-id", type=int, help="Analyze a specific item by ID")
    parser.add_argument("--limit", type=int, default=10, help="Max items to analyze")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be analyzed without LLM calls")
    parser.add_argument("--model", type=str, help="Override LLM model")
    parser.add_argument("--force", action="store_true", help="Force re-analysis even if input_hash matches")
    parser.add_argument("--force-reason", type=str, help="Reason for forcing re-analysis")
    parser.add_argument("--only-source-id", type=int, help="Only analyze items from this source")
    args = parser.parse_args()

    if args.model:
        settings.LLM_MODEL = args.model

    db = SessionLocal()
    try:
        item_repo = ItemRepository(db)
        analysis_repo = AnalysisRepository(db)

        if args.item_id:
            items = [item_repo.get(args.item_id)]
            if not items[0]:
                print(f"Item {args.item_id} not found")
                return
        else:
            query = db.query(Item).filter(
                Item.status.in_([ItemStatus.collected, ItemStatus.normalized])
            )
            if args.only_source_id:
                query = query.filter(Item.source_id == args.only_source_id)
            items = query.order_by(Item.id.asc()).limit(args.limit).all()

        if args.dry_run:
            print(f"=== DRY RUN: {len(items)} items ===")
            for item in items:
                raw_text = item.raw_text or item.title
                input_hash = calculate_analysis_input_hash(
                    item_id=item.id,
                    title=item.title,
                    raw_text=raw_text,
                    source_url=item.url,
                    model_name=settings.LLM_MODEL,
                    prompt_version=settings.LLM_PROMPT_VERSION,
                    analysis_version=settings.LLM_ANALYSIS_VERSION,
                )
                existing = analysis_repo.find_success_by_input_hash(input_hash)
                truncated = len(raw_text) > settings.LLM_MAX_INPUT_CHARS
                print(f"  item_id={item.id} | title={item.title[:60]} | source={item.source.name if item.source else '?'} | input_chars={len(raw_text)} | truncated={truncated} | input_hash={input_hash[:16]}... | existing={'YES' if existing else 'NO'}")
            return

        print(f"=== Analyzing {len(items)} items (force={args.force}) ===")
        service = AnalysisService(db)
        stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0, "invalid": 0}

        for item in items:
            stats["total"] += 1
            try:
                result = service.analyze_single_item(item, force=args.force, force_reason=args.force_reason)
                if result == "skipped_existing":
                    stats["skipped"] += 1
                    print(f"  SKIP item_id={item.id} (input_hash match)")
                else:
                    stats["success"] += 1
                    latest = analysis_repo.get_latest_success_for_item(item.id)
                    ts = latest.total_score if latest else "?"
                    print(f"  OK   item_id={item.id} | total_score={ts}")
            except Exception as e:
                stats["failed"] += 1
                print(f"  FAIL item_id={item.id} | error={e}")

        print(f"\n=== DONE: total={stats['total']} success={stats['success']} failed={stats['failed']} skipped={stats['skipped']} invalid={stats.get('invalid', 0)} ===")

    finally:
        db.close()


if __name__ == "__main__":
    main()
