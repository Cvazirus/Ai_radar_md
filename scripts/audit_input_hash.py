"""Audit input_hash duplicates in item_analysis table."""
import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from app.database.session import SessionLocal
from app.database.models import ItemAnalysis, AnalysisStatus
from sqlalchemy import func


def audit_input_hash_duplicates():
    db = SessionLocal()
    try:
        # Find hashes with multiple success records
        dup_hashes = db.query(
            ItemAnalysis.input_hash,
            func.count(ItemAnalysis.id).label("cnt")
        ).filter(
            ItemAnalysis.status == AnalysisStatus.success
        ).group_by(
            ItemAnalysis.input_hash
        ).having(
            func.count(ItemAnalysis.id) > 1
        ).all()

        result = {
            "duplicate_groups": len(dup_hashes),
            "allowed_force_duplicates": 0,
            "invalid_duplicates": 0,
            "legacy_duplicates": 0,
            "details": []
        }

        for hash_val, count in dup_hashes:
            records = db.query(ItemAnalysis).filter(
                ItemAnalysis.input_hash == hash_val,
                ItemAnalysis.status == AnalysisStatus.success
            ).order_by(ItemAnalysis.created_at.asc()).all()

            force_count = sum(1 for r in records if r.force_run)
            legacy_count = sum(1 for r in records if r.prompt_version == "legacy")
            non_force_non_legacy = sum(1 for r in records if not r.force_run and r.prompt_version != "legacy")

            group = {
                "input_hash": hash_val[:16] + "...",
                "total_records": count,
                "force_records": force_count,
                "legacy_records": legacy_count,
                "non_force_non_legacy": non_force_non_legacy,
                "classification": "allowed_force" if non_force_non_legacy == 0 else "INVALID",
                "records": [
                    {
                        "id": r.id,
                        "item_id": r.item_id,
                        "force_run": r.force_run,
                        "force_reason": r.force_reason,
                        "prompt_version": r.prompt_version,
                    }
                    for r in records
                ]
            }

            if non_force_non_legacy == 0:
                result["allowed_force_duplicates"] += force_count
            else:
                result["invalid_duplicates"] += non_force_non_legacy

            if legacy_count > 0:
                result["legacy_duplicates"] += legacy_count

            result["details"].append(group)

        # Check for non-force non-legacy duplicates
        non_force_dups = db.query(
            ItemAnalysis.input_hash,
            func.count(ItemAnalysis.id).label("cnt")
        ).filter(
            ItemAnalysis.status == AnalysisStatus.success,
            ItemAnalysis.force_run == False,
            ItemAnalysis.input_hash != "legacy"
        ).group_by(
            ItemAnalysis.input_hash
        ).having(
            func.count(ItemAnalysis.id) > 1
        ).all()

        result["invalid_non_force_duplicates"] = len(non_force_dups)

        return result
    finally:
        db.close()


if __name__ == "__main__":
    import json
    result = audit_input_hash_duplicates()
    print(json.dumps(result, indent=2, default=str))
