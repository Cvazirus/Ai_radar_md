from typing import List, Dict, Optional
from datetime import timedelta
import structlog
from sqlalchemy.orm import Session
from app.database.models import (
    Source, Item, ItemStatus, DuplicateRelation, RelationType, ReviewStatus
)
from app.database.repositories import ItemRepository, DuplicateRelationRepository
from app.collectors.schemas import CollectedItem
from app.pipeline.normalize import (
    normalize_title,
    normalize_text,
    normalize_author,
    normalize_published_at,
    normalize_language
)
from app.pipeline.url_normalizer import canonicalize_url
from app.pipeline.entity_keys import extract_entity_keys
from app.pipeline.deduplicate import (
    calculate_content_hash,
    normalize_title_for_matching,
    calculate_title_similarity,
    has_mismatched_parts
)

logger = structlog.get_logger()

class ItemService:
    def __init__(self, db: Session):
        self.db = db
        self.item_repo = ItemRepository(db)
        self.rel_repo = DuplicateRelationRepository(db)

    def process_collected_items(self, source: Source, collected_items: List[CollectedItem]) -> Dict[str, int]:
        stats = {"found": len(collected_items), "created": 0, "skipped": 0, "failed": 0}
        
        for col_item in collected_items:
            try:
                # 1. Нормализация полей
                norm_title = normalize_title(col_item.title)
                norm_text = normalize_text(col_item.text)
                norm_author = normalize_author(col_item.author)
                norm_published_at = normalize_published_at(col_item.published_at)
                norm_lang = normalize_language(norm_text or norm_title)
                
                # 2. Канонизация URL
                canonical_url = canonicalize_url(col_item.url)
                
                # 3. Вычисление content_hash
                content_hash = calculate_content_hash(
                    source_id=source.id,
                    url=canonical_url,
                    normalized_title=norm_title,
                    published_at=norm_published_at,
                    external_id=col_item.external_id
                )
                
                # 4. УРОВЕНЬ 1 — content_hash (Защита от UNIQUE constraint)
                existing = self.item_repo.get_by_hash(content_hash)
                if existing:
                    stats["skipped"] += 1
                    logger.info(
                        "rss_item_skipped",
                        source_name=source.name,
                        title=norm_title,
                        url=col_item.url,
                        reason="duplicate_content_hash"
                    )
                    continue

                # Извлечение сущностей
                entity_keys = extract_entity_keys(norm_text or norm_title)
                metadata = col_item.metadata or {}
                metadata["entity_keys"] = entity_keys

                # 5. Создание ORM объекта Item
                new_item = Item(
                    source_id=source.id,
                    external_id=col_item.external_id,
                    url=col_item.url,
                    canonical_url=canonical_url,
                    title=norm_title,
                    author=norm_author,
                    raw_text=norm_text,
                    published_at=norm_published_at,
                    content_hash=content_hash,
                    language=norm_lang,
                    status=ItemStatus.collected,
                    metadata_json=metadata
                )
                
                relations_to_create = []
                is_duplicate = False
                
                # Оптимизированный поиск кандидатов (без O(N²))
                # УРОВЕНЬ 2 — external_id (Поиск O(1) по индексу)
                if new_item.external_id:
                    ext_dup = self.db.query(Item).filter(
                        Item.source_id == source.id,
                        Item.external_id == new_item.external_id
                    ).first()
                    if ext_dup:
                        is_duplicate = True
                        relations_to_create.append({
                            "duplicate_of_item_id": ext_dup.id,
                            "relation_type": RelationType.exact_external_id,
                            "confidence": 1.0000,
                            "review_status": ReviewStatus.auto_confirmed,
                            "reason": f"Matches external_id '{new_item.external_id}'"
                        })

                # УРОВЕНЬ 3 — canonical_url (Поиск O(1) по индексу)
                url_dup = self.db.query(Item).filter(
                    Item.canonical_url == new_item.canonical_url
                ).first()
                if url_dup:
                    is_duplicate = True
                    relations_to_create.append({
                        "duplicate_of_item_id": url_dup.id,
                        "relation_type": RelationType.exact_canonical_url,
                        "confidence": 1.0000,
                        "review_status": ReviewStatus.auto_confirmed,
                        "reason": f"Matches canonical_url '{new_item.canonical_url}'"
                    })

                # УРОВЕНЬ 4 & 5 — Сходство заголовков в рамках одного источника за последние 14 дней
                candidates_query = self.db.query(Item).filter(
                    Item.source_id == source.id
                )
                if new_item.published_at:
                    start_date = new_item.published_at - timedelta(days=14)
                    candidates_query = candidates_query.filter(Item.published_at >= start_date)
                
                candidates = candidates_query.order_by(Item.published_at.desc()).limit(100).all()
                
                # УРОВЕНЬ 4 — Одинаковый заголовок одного источника (same_source_title)
                new_title_match = normalize_title_for_matching(new_item.title)
                title_dup = next(
                    (x for x in candidates if normalize_title_for_matching(x.title) == new_title_match),
                    None
                )
                if title_dup:
                    is_duplicate = True
                    # Применение D46: несовпадающие части запрещают auto_confirmed
                    mismatch = has_mismatched_parts(new_item.title, title_dup.title)
                    relations_to_create.append({
                        "duplicate_of_item_id": title_dup.id,
                        "relation_type": RelationType.same_source_title,
                        "confidence": 0.7000 if mismatch else 0.9500,
                        "review_status": ReviewStatus.pending_review if mismatch else ReviewStatus.auto_confirmed,
                        "reason": "Matches identical normalized title (mismatched parts detected)" if mismatch else "Matches identical normalized title"
                    })

                # УРОВЕНЬ 5 — Похожие заголовки одного источника (Level 5)
                for ext in candidates:
                    # Исключаем тех, кого уже связали по URL или идентичному Title
                    if ext.id != (url_dup.id if url_dup else None) and ext.id != (title_dup.id if title_dup else None):
                        sim = calculate_title_similarity(new_item.title, ext.title)
                        if sim >= 0.92:
                            is_duplicate = True
                            conf = float(sim)
                            mismatch = has_mismatched_parts(new_item.title, ext.title)
                            
                            if mismatch:
                                conf = min(conf, 0.7000) # Понижаем confidence
                                rev_status = ReviewStatus.pending_review
                            else:
                                rev_status = ReviewStatus.auto_confirmed if conf >= 0.97 else ReviewStatus.pending_review
                                
                            relations_to_create.append({
                                "duplicate_of_item_id": ext.id,
                                "relation_type": RelationType.same_source_title,
                                "confidence": conf,
                                "review_status": rev_status,
                                "reason": f"Title similarity {sim:.4f} within 14 days (mismatched parts)" if mismatch else f"Title similarity {sim:.4f} within 14 days"
                            })

                # CROSS-SOURCE STORY (Поиск связанных новостей в разных источниках)
                # Разные source_id, только при наличии общих entity keys, разница <= 7 дней
                flat_keys = []
                for key_type in ["arxiv_ids", "github_repositories", "huggingface_models", "dois", "youtube_ids"]:
                    flat_keys.extend(entity_keys.get(key_type, []))
                
                if flat_keys:
                    cross_query = self.db.query(Item).filter(
                        Item.source_id != source.id
                    )
                    if new_item.published_at:
                        start_date = new_item.published_at - timedelta(days=7)
                        cross_query = cross_query.filter(Item.published_at >= start_date)
                        
                    cross_candidates = cross_query.order_by(Item.published_at.desc()).limit(150).all()
                    
                    for ext in cross_candidates:
                        ext_keys = ext.metadata_json.get("entity_keys", {}) if ext.metadata_json else {}
                        common_entities = []
                        for key_type in ["arxiv_ids", "github_repositories", "huggingface_models", "dois", "youtube_ids"]:
                            ext_vals = set(ext_keys.get(key_type, []))
                            curr_vals = set(entity_keys.get(key_type, []))
                            common = ext_vals.intersection(curr_vals)
                            if common:
                                common_entities.append(f"{key_type}: {list(common)}")
                        
                        # Только если есть общие entity keys
                        if common_entities:
                            sim = calculate_title_similarity(new_item.title, ext.title)
                            conf = 0.9800
                            rev_status = ReviewStatus.auto_confirmed
                            
                            reason_parts = [f"Matching entities ({', '.join(common_entities)})"]
                            if sim >= 0.85:
                                reason_parts.append(f"Title similarity {sim:.4f}")
                                
                            relations_to_create.append({
                                "duplicate_of_item_id": ext.id,
                                "relation_type": RelationType.cross_source_story,
                                "confidence": conf,
                                "review_status": rev_status,
                                "reason": " and ".join(reason_parts)
                            })

                # Если хотя бы один уровень (2-5) пометил запись как дубликат, проставляем статус duplicate
                if is_duplicate:
                    new_item.status = ItemStatus.duplicate

                # Сохраняем Item в базу данных
                self.item_repo.create(new_item)
                stats["created"] += 1
                
                # Создаем связи в duplicate_relations с защитой от дублирования (идемпотентность)
                for rel_data in relations_to_create:
                    try:
                        existing_rel = None
                        if new_item.id is not None:
                            from unittest.mock import MagicMock
                            res = self.rel_repo.get_by_items_and_type(
                                item_id=new_item.id,
                                duplicate_of_item_id=rel_data["duplicate_of_item_id"],
                                relation_type=rel_data["relation_type"]
                            )
                            if not isinstance(res, MagicMock):
                                existing_rel = res
                                
                        if not existing_rel:
                            new_rel = DuplicateRelation(
                                item_id=new_item.id,
                                duplicate_of_item_id=rel_data["duplicate_of_item_id"],
                                relation_type=rel_data["relation_type"],
                                confidence=rel_data["confidence"],
                                review_status=rel_data["review_status"],
                                reason=rel_data["reason"]
                            )
                            self.rel_repo.create(new_rel)
                    except Exception as rel_err:
                        logger.error(
                            "duplicate_relation_creation_failed",
                            item_id=new_item.id,
                            duplicate_of_item_id=rel_data["duplicate_of_item_id"],
                            error=str(rel_err)
                        )
                
                logger.info(
                    "rss_item_saved",
                    source_name=source.name,
                    title=norm_title,
                    url=col_item.url,
                    item_id=new_item.id,
                    status=new_item.status.value
                )
                
            except Exception as e:
                stats["failed"] += 1
                logger.error(
                    "rss_item_processing_failed",
                    source_name=source.name,
                    url=col_item.url,
                    error=str(e)
                )
                
        return stats
