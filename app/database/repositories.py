from typing import List, Optional, Dict
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database.models import Source, Item, ItemAnalysis, AnalysisStatus, Publication, CollectionRun, DuplicateRelation, RelationType

class SourceRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, source: Source) -> Source:
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    def get(self, source_id: int) -> Optional[Source]:
        return self.db.query(Source).filter(Source.id == source_id).first()

    def update(self, source: Source) -> Source:
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    def delete(self, source_id: int) -> bool:
        source = self.get(source_id)
        if source:
            self.db.delete(source)
            self.db.commit()
            return True
        return False

    def list(self, limit: int = 100, offset: int = 0) -> List[Source]:
        return self.db.query(Source).offset(offset).limit(limit).all()


class ItemRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, item: Item) -> Item:
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def get(self, item_id: int) -> Optional[Item]:
        return self.db.query(Item).filter(Item.id == item_id).first()

    def get_by_hash(self, content_hash: str) -> Optional[Item]:
        return self.db.query(Item).filter(Item.content_hash == content_hash).first()

    def get_by_canonical_url(self, canonical_url: str) -> Optional[Item]:
        return self.db.query(Item).filter(Item.canonical_url == canonical_url).first()

    def update(self, item: Item) -> Item:
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete(self, item_id: int) -> bool:
        item = self.get(item_id)
        if item:
            self.db.delete(item)
            self.db.commit()
            return True
        return False

    def list(self, limit: int = 100, offset: int = 0) -> List[Item]:
        return self.db.query(Item).offset(offset).limit(limit).all()


class AnalysisRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, analysis: ItemAnalysis) -> ItemAnalysis:
        self.db.add(analysis)
        self.db.commit()
        self.db.refresh(analysis)
        return analysis

    def update(self, analysis: ItemAnalysis) -> ItemAnalysis:
        self.db.add(analysis)
        self.db.commit()
        self.db.refresh(analysis)
        return analysis

    def get_by_id(self, analysis_id: int) -> Optional[ItemAnalysis]:
        return self.db.query(ItemAnalysis).filter(ItemAnalysis.id == analysis_id).first()

    def find_success_by_input_hash(self, input_hash: str) -> Optional[ItemAnalysis]:
        return self.db.query(ItemAnalysis).filter(
            ItemAnalysis.input_hash == input_hash,
            ItemAnalysis.status == AnalysisStatus.success
        ).first()

    def get_latest_success_for_item(self, item_id: int) -> Optional[ItemAnalysis]:
        return self.db.query(ItemAnalysis).filter(
            ItemAnalysis.item_id == item_id,
            ItemAnalysis.status == AnalysisStatus.success
        ).order_by(ItemAnalysis.id.desc()).first()

    def list_pending(self, limit: int = 100) -> List[ItemAnalysis]:
        return self.db.query(ItemAnalysis).filter(
            ItemAnalysis.status == AnalysisStatus.pending
        ).order_by(ItemAnalysis.id.asc()).limit(limit).all()

    def list_failed(self, limit: int = 100) -> List[ItemAnalysis]:
        return self.db.query(ItemAnalysis).filter(
            ItemAnalysis.status == AnalysisStatus.failed
        ).order_by(ItemAnalysis.id.desc()).limit(limit).all()

    def list_invalid(self, limit: int = 100) -> List[ItemAnalysis]:
        return self.db.query(ItemAnalysis).filter(
            ItemAnalysis.status == AnalysisStatus.invalid_response
        ).order_by(ItemAnalysis.id.desc()).limit(limit).all()

    def count_by_status(self) -> Dict[str, int]:
        rows = self.db.query(
            ItemAnalysis.status,
            func.count(ItemAnalysis.id)
        ).group_by(ItemAnalysis.status).all()
        return {str(row[0].value if hasattr(row[0], 'value') else row[0]): row[1] for row in rows}


class PublicationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, publication: Publication) -> Publication:
        self.db.add(publication)
        self.db.commit()
        self.db.refresh(publication)
        return publication

    def get(self, item_id: int) -> Optional[Publication]:
        return self.db.query(Publication).filter(Publication.item_id == item_id).first()

    def update(self, publication: Publication) -> Publication:
        self.db.add(publication)
        self.db.commit()
        self.db.refresh(publication)
        return publication

    def delete(self, item_id: int) -> bool:
        pub = self.get(item_id)
        if pub:
            self.db.delete(pub)
            self.db.commit()
            return True
        return False


class CollectionRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, run: CollectionRun) -> CollectionRun:
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def get(self, run_id: int) -> Optional[CollectionRun]:
        return self.db.query(CollectionRun).filter(CollectionRun.id == run_id).first()

    def update(self, run: CollectionRun) -> CollectionRun:
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def delete(self, run_id: int) -> bool:
        run = self.get(run_id)
        if run:
            self.db.delete(run)
            self.db.commit()
            return True
        return False

    def list(self, limit: int = 100, offset: int = 0) -> List[CollectionRun]:
        return self.db.query(CollectionRun).offset(offset).limit(limit).all()

class DuplicateRelationRepository:
    def __init__(self, db: Session):
        self.db = db
        
    def create(self, rel: DuplicateRelation) -> DuplicateRelation:
        self.db.add(rel)
        self.db.commit()
        self.db.refresh(rel)
        return rel
        
    def get(self, rel_id: int) -> Optional[DuplicateRelation]:
        return self.db.query(DuplicateRelation).filter(DuplicateRelation.id == rel_id).first()
        
    def get_by_items_and_type(self, item_id: int, duplicate_of_item_id: int, relation_type: RelationType) -> Optional[DuplicateRelation]:
        return self.db.query(DuplicateRelation).filter(
            DuplicateRelation.item_id == item_id,
            DuplicateRelation.duplicate_of_item_id == duplicate_of_item_id,
            DuplicateRelation.relation_type == relation_type
        ).first()
        
    def delete(self, rel_id: int) -> bool:
        rel = self.get(rel_id)
        if rel:
            self.db.delete(rel)
            self.db.commit()
            return True
        return False
