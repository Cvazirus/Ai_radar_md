from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import Session
import structlog
from app.database.models import Item, ItemStatus

logger = structlog.get_logger()


@dataclass
class NormalizeResult:
    item_id: int
    success: bool
    status: str
    error: str | None = None


class NormalizeService:
    def __init__(self, db: Session):
        self.db = db

    def normalize_batch(self, limit: int, item_id: Optional[int] = None) -> dict:
        """Normalize collected items to normalized status."""
        query = self.db.query(Item).filter(Item.status == ItemStatus.collected)
        if item_id:
            query = query.filter(Item.id == item_id)

        items = query.limit(limit).all()
        results = []

        for item in items:
            try:
                item.status = ItemStatus.normalized
                self.db.add(item)
                results.append(NormalizeResult(
                    item_id=item.id,
                    success=True,
                    status="normalized"
                ))
            except Exception as e:
                results.append(NormalizeResult(
                    item_id=item.id,
                    success=False,
                    status="error",
                    error=str(e)
                ))

        self.db.commit()

        return {
            "processed": sum(1 for r in results if r.success),
            "skipped": 0,
            "failed": sum(1 for r in results if not r.success),
            "errors": [r.error for r in results if r.error]
        }
