import sys
import time
import argparse
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from datetime import timedelta, timezone
from sqlalchemy import text
from app.database.session import SessionLocal
from app.database.models import (
    Item, Source, DuplicateRelation, RelationType, ReviewStatus, ItemStatus
)
from app.pipeline.url_normalizer import canonicalize_url
from app.pipeline.entity_keys import extract_entity_keys
from app.pipeline.deduplicate import (
    calculate_content_hash,
    normalize_title_for_matching,
    calculate_title_similarity,
    has_mismatched_parts
)

def run_backfill(dry_run=False, no_truncate=False):
    db = SessionLocal()
    try:
        print(f"=== STARTING PHASE 4 BACKFILL (Dry Run: {dry_run}, No Truncate: {no_truncate}) ===")
        start_time = time.time()
        
        # 1. Очищаем duplicate_relations только при реальном запуске и без флага no_truncate
        if not dry_run and not no_truncate:
            print("Truncating duplicate_relations table...")
            db.execute(text("TRUNCATE TABLE duplicate_relations RESTART IDENTITY CASCADE;"))
            db.commit()
            
        # 2. Загружаем все новости, упорядоченные хронологически по дате публикации
        items = db.query(Item).order_by(Item.published_at.asc(), Item.id.asc()).all()
        total_items = len(items)
        print(f"Loaded {total_items} items from database.")
        
        # Шаг А: Обновление URL, хэшей и сущностей
        print("Step A: Normalizing URLs, computing new content hashes, and extracting entities...")
        for i, item in enumerate(items):
            canonical = canonicalize_url(item.url)
            item.canonical_url = canonical
            
            # Извлечение сущностей
            entity_keys = extract_entity_keys(item.raw_text or item.title)
            meta = item.metadata_json or {}
            meta["entity_keys"] = entity_keys
            item.metadata_json = meta
            
            # Пересчет content_hash на базе канонического URL
            new_hash = calculate_content_hash(
                source_id=item.source_id,
                url=canonical,
                normalized_title=item.title,
                published_at=item.published_at,
                external_id=item.external_id
            )
            item.content_hash = new_hash
            
            db.add(item)
            if i % 500 == 0:
                db.commit()
                print(f"Processed A: {i}/{total_items} items...")
        db.commit()
        print("Step A complete.")
        
        # Шаг Б: Хронологический расчет дубликатов с оптимизацией по времени и сущностям (O(N) с окном)
        print("Step B: Building duplicate relations using candidate window index queries...")
        relations_created = 0
        duplicates_marked = 0
        
        for i, current_item in enumerate(items):
            relations_to_create = []
            is_duplicate = False
            
            # Level 2: external_id inside the same source (O(1) index query)
            if current_item.external_id:
                ext_query = db.query(Item).filter(
                    Item.source_id == current_item.source_id,
                    Item.external_id == current_item.external_id,
                    Item.id != current_item.id
                )
                if current_item.published_at:
                    ext_query = ext_query.filter(Item.published_at <= current_item.published_at)
                else:
                    ext_query = ext_query.filter(Item.id < current_item.id)
                ext_dup = ext_query.first()
                
                if ext_dup:
                    is_duplicate = True
                    relations_to_create.append({
                        "duplicate_of_item_id": ext_dup.id,
                        "relation_type": RelationType.exact_external_id,
                        "confidence": 1.0000,
                        "review_status": ReviewStatus.auto_confirmed,
                        "reason": f"Matches external_id '{current_item.external_id}'"
                    })
            
            # Level 3: canonical_url global (O(1) index query)
            url_query = db.query(Item).filter(
                Item.canonical_url == current_item.canonical_url,
                Item.id != current_item.id
            )
            if current_item.published_at:
                url_query = url_query.filter(Item.published_at <= current_item.published_at)
            else:
                url_query = url_query.filter(Item.id < current_item.id)
            url_dup = url_query.first()
            
            if url_dup:
                is_duplicate = True
                relations_to_create.append({
                    "duplicate_of_item_id": url_dup.id,
                    "relation_type": RelationType.exact_canonical_url,
                    "confidence": 1.0000,
                    "review_status": ReviewStatus.auto_confirmed,
                    "reason": f"Matches canonical_url '{current_item.canonical_url}'"
                })
                
            # Level 4 & 5: title similarity within same source and 14 days time window
            candidates_query = db.query(Item).filter(
                Item.source_id == current_item.source_id,
                Item.id != current_item.id
            )
            if current_item.published_at:
                start_date = current_item.published_at - timedelta(days=14)
                candidates_query = candidates_query.filter(
                    Item.published_at >= start_date,
                    Item.published_at <= current_item.published_at
                )
            else:
                candidates_query = candidates_query.filter(Item.id < current_item.id)
                
            candidates = candidates_query.order_by(Item.published_at.desc()).limit(100).all()
            
            # Level 4: same title in same source
            current_title_match = normalize_title_for_matching(current_item.title)
            title_dup = next(
                (x for x in candidates if normalize_title_for_matching(x.title) == current_title_match),
                None
            )
            
            if title_dup:
                is_duplicate = True
                # Применение D46: несовпадающие части запрещают auto_confirmed
                mismatch = has_mismatched_parts(current_item.title, title_dup.title)
                relations_to_create.append({
                    "duplicate_of_item_id": title_dup.id,
                    "relation_type": RelationType.same_source_title,
                    "confidence": 0.7000 if mismatch else 0.9500,
                    "review_status": ReviewStatus.pending_review if mismatch else ReviewStatus.auto_confirmed,
                    "reason": "Matches identical normalized title (mismatched parts detected)" if mismatch else "Matches identical normalized title"
                })
                
            # Level 5: similar title in same source
            for ext in candidates:
                if ext.id != (url_dup.id if url_dup else None) and ext.id != (title_dup.id if title_dup else None):
                    sim = calculate_title_similarity(current_item.title, ext.title)
                    if sim >= 0.92:
                        is_duplicate = True
                        conf = float(sim)
                        mismatch = has_mismatched_parts(current_item.title, ext.title)
                        
                        if mismatch:
                            conf = min(conf, 0.7000)
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
                        
            # Cross-Source Story: search other sources in <= 7 days, only when entity keys intersect
            entity_keys = current_item.metadata_json.get("entity_keys", {}) if current_item.metadata_json else {}
            flat_keys = []
            for key_type in ["arxiv_ids", "github_repositories", "huggingface_models", "dois", "youtube_ids"]:
                flat_keys.extend(entity_keys.get(key_type, []))
                
            if flat_keys:
                cross_query = db.query(Item).filter(
                    Item.source_id != current_item.source_id,
                    Item.id != current_item.id
                )
                if current_item.published_at:
                    start_date = current_item.published_at - timedelta(days=7)
                    cross_query = cross_query.filter(
                        Item.published_at >= start_date,
                        Item.published_at <= current_item.published_at
                    )
                else:
                    cross_query = cross_query.filter(Item.id < current_item.id)
                    
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
                            
                    if common_entities:
                        sim = calculate_title_similarity(current_item.title, ext.title)
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
            
            # Обновляем статус
            if is_duplicate:
                current_item.status = ItemStatus.duplicate
                db.add(current_item)
                duplicates_marked += 1
            else:
                current_item.status = ItemStatus.collected
                db.add(current_item)
                
            # Записываем связи
            for rel in relations_to_create:
                # Идемпотентность: проверяем, нет ли уже такой связи
                existing_rel = db.query(DuplicateRelation).filter(
                    DuplicateRelation.item_id == current_item.id,
                    DuplicateRelation.duplicate_of_item_id == rel["duplicate_of_item_id"],
                    DuplicateRelation.relation_type == rel["relation_type"]
                ).first()
                
                if not existing_rel:
                    db_rel = DuplicateRelation(
                        item_id=current_item.id,
                        duplicate_of_item_id=rel["duplicate_of_item_id"],
                        relation_type=rel["relation_type"],
                        confidence=rel["confidence"],
                        review_status=rel["review_status"],
                        reason=rel["reason"]
                    )
                    db.add(db_rel)
                    relations_created += 1
            
            if i % 100 == 0:
                db.commit()
                print(f"Processed B: {i}/{total_items} items...")
                
        if dry_run:
            db.rollback()
            print("Dry Run rollbacked successfully.")
        else:
            db.commit()
            
        duration = time.time() - start_time
        print(f"\n=== PHASE 4 BACKFILL COMPLETE (Dry Run: {dry_run}, No Truncate: {no_truncate}) ===")
        print(f"Total processed:      {total_items}")
        print(f"Duplicates marked:    {duplicates_marked}")
        print(f"Relations created:    {relations_created}")
        print(f"Total duration:       {duration:.2f} seconds")
        print(f"Average speed:        {total_items / duration:.2f} items/sec")
        print("====================================================\n")
        
    except Exception as e:
        db.rollback()
        print(f"Backfill failed: {e}")
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Phase 4 Backfill")
    parser.add_argument("--dry-run", action="store_true", help="Run without committing changes")
    parser.add_argument("--no-truncate", action="store_true", help="Do not truncate duplicate_relations table")
    args = parser.parse_args()
    run_backfill(dry_run=args.dry_run, no_truncate=args.no_truncate)
