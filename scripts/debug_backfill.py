import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from datetime import timedelta
from app.database.session import SessionLocal
from app.database.models import Item
from app.pipeline.deduplicate import normalize_title_for_matching, has_mismatched_parts

db = SessionLocal()
try:
    current_item = db.query(Item).filter(Item.id == 306).first()
    print(f"current_item {current_item.id}: title='{current_item.title}', pub='{current_item.published_at}'")
    
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
    print(f"Candidates found: {len(candidates)}")
    
    current_title_match = normalize_title_for_matching(current_item.title)
    print(f"Normalized current title: '{current_title_match}'")
    
    title_dup = next(
        (x for x in candidates if normalize_title_for_matching(x.title) == current_title_match),
        None
    )
    
    if title_dup:
        print(f"MATCH FOUND! title_dup {title_dup.id}: '{title_dup.title}', pub='{title_dup.published_at}'")
        mismatch = has_mismatched_parts(current_item.title, title_dup.title)
        print(f"Mismatch: {mismatch}")
    else:
        print("NO MATCH FOUND.")
        
finally:
    db.close()
