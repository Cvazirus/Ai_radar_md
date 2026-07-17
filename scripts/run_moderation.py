import sys
import argparse
import json
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from app.config import settings
from app.database.session import SessionLocal
from app.database.models import Item, ItemAnalysis, AnalysisStatus, DuplicateRelation, ModerationQueue
from app.database.repositories import ItemRepository, AnalysisRepository, ModerationQueueRepository
from app.services.moderation_service import ModerationService
from app.pipeline.moderation_rules import evaluate_item_moderation

def main():
    parser = argparse.ArgumentParser(description="AI Radar Moderation Processor")
    parser.add_argument("--analysis-id", type=int, help="Process a specific analysis by ID")
    parser.add_argument("--item-id", type=int, help="Process all successful analyses for a specific item by ID")
    parser.add_argument("--limit", type=int, default=50, help="Max items to process in batch")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate moderation rules but do not save to DB")
    parser.add_argument("--force-recalculate", action="store_true", help="Force recalculation even if already in queue")
    parser.add_argument("--reason", type=str, help="Reason for recalculation")
    parser.add_argument("--only-decision", action="store_true", help="Evaluate and print decision, do not write to DB")
    parser.add_argument("--only-source-id", type=int, help="Only process items from this source ID")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        item_repo = ItemRepository(db)
        analysis_repo = AnalysisRepository(db)
        queue_repo = ModerationQueueRepository(db)
        service = ModerationService(db)

        # Build list of analyses to process
        if args.analysis_id:
            analysis = analysis_repo.get_by_id(args.analysis_id)
            if not analysis:
                print(f"Analysis {args.analysis_id} not found")
                return
            analyses = [analysis]
        elif args.item_id:
            analyses = db.query(ItemAnalysis).filter(
                ItemAnalysis.item_id == args.item_id,
                ItemAnalysis.status == AnalysisStatus.success
            ).all()
            if not analyses:
                print(f"No successful analyses found for item {args.item_id}")
                return
        else:
            # Batch mode
            query = db.query(ItemAnalysis).filter(
                ItemAnalysis.status == AnalysisStatus.success
            )
            if args.only_source_id:
                query = query.join(Item).filter(Item.source_id == args.only_source_id)
            
            # If not forcing recalculation, skip already moderated analyses
            if not args.force_recalculate:
                from sqlalchemy import select
                moderated_ids = select(ModerationQueue.analysis_id)
                query = query.filter(~ItemAnalysis.id.in_(moderated_ids))
            
            analyses = query.order_by(ItemAnalysis.id.asc()).limit(args.limit).all()

        is_dry = args.dry_run or args.only_decision
        print(f"=== Processing {len(analyses)} analyses (dry_run={is_dry}, force={args.force_recalculate}) ===")

        for idx, analysis in enumerate(analyses):
            item = item_repo.get(analysis.item_id)
            if not item:
                print(f"[{idx+1}/{len(analyses)}] Error: Item {analysis.item_id} not found")
                continue

            if is_dry:
                # Dry run evaluation
                duplicate_relations = db.query(DuplicateRelation).filter(
                    (DuplicateRelation.item_id == item.id) | (DuplicateRelation.duplicate_of_item_id == item.id)
                ).all()
                result = evaluate_item_moderation(item, analysis, duplicate_relations)
                
                print(f"[{idx+1}/{len(analyses)}] Item {item.id} | Analysis {analysis.id}")
                print(f"  Category: {analysis.category}")
                print(f"  Total Score: {analysis.total_score}")
                print(f"  Decision Score: {result.decision_score}")
                print(f"  Decision: {result.decision}")
                print(f"  Priority: {result.priority}")
                if result.blocking_reasons:
                    print(f"  Blocking Reasons: {result.blocking_reasons}")
                print(f"  Reasons Breakdown: {json.dumps(result.decision_reasons)}")
                print("-" * 40)
            else:
                # Write to DB
                res = service.moderate_analysis(
                    analysis.id, 
                    force_recalculate=args.force_recalculate, 
                    force_reason=args.reason
                )
                if res:
                    print(f"[{idx+1}/{len(analyses)}] Moderated Item {item.id} | Analysis {analysis.id} -> Decision: {res.decision}, Priority: {res.priority}, Score: {res.decision_score}")
                else:
                    print(f"[{idx+1}/{len(analyses)}] Skipped Item {item.id} | Analysis {analysis.id}")

    finally:
        db.close()

if __name__ == "__main__":
    main()
