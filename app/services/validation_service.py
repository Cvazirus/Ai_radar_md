from dataclasses import dataclass, field
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc
import structlog
from app.database.models import ItemAnalysis, AnalysisStatus
from app.pipeline.claim_validation import validate_source_claims

logger = structlog.get_logger()


@dataclass
class ValidationResult:
    item_id: int
    analysis_id: int
    valid: bool
    issues: List[str] = field(default_factory=list)
    next_status: str = "validated"


class ValidationService:
    def __init__(self, db: Session):
        self.db = db

    def validate_batch(self, limit: int, item_id: Optional[int] = None) -> dict:
        """Validate claims of the latest analyses."""
        query = self.db.query(ItemAnalysis).filter(ItemAnalysis.status == AnalysisStatus.success)
        if item_id:
            query = query.filter(ItemAnalysis.item_id == item_id)

        analyses = query.order_by(desc(ItemAnalysis.id)).limit(limit).all()
        results = []

        for analysis in analyses:
            try:
                item = analysis.item
                if not item:
                    continue
                claims = analysis.source_claims
                if isinstance(claims, dict) and "claims" in claims:
                    claims = claims["claims"]
                res = validate_source_claims(item.raw_text or item.title, claims)
                if res.invalid_claims:
                    results.append(ValidationResult(
                        item_id=item.id,
                        analysis_id=analysis.id,
                        valid=False,
                        issues=[f"{len(res.invalid_claims)} invalid claims"],
                        next_status="validation_failed"
                    ))
                else:
                    results.append(ValidationResult(
                        item_id=item.id,
                        analysis_id=analysis.id,
                        valid=True,
                        next_status="validated"
                    ))
            except Exception as e:
                results.append(ValidationResult(
                    item_id=item.id if item else 0,
                    analysis_id=analysis.id,
                    valid=False,
                    issues=[str(e)],
                    next_status="validation_error"
                ))

        return {
            "processed": sum(1 for r in results if r.valid),
            "skipped": 0,
            "failed": sum(1 for r in results if not r.valid),
            "errors": [issue for r in results for issue in r.issues if not r.valid]
        }
