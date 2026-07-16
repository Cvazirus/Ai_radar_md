import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from datetime import timedelta
from sqlalchemy import text
from app.database.session import SessionLocal
from app.database.models import Item
from app.pipeline.deduplicate import (
    normalize_title_for_matching,
    calculate_title_similarity,
    has_mismatched_parts
)

def analyze_item(item_id):
    db = SessionLocal()
    try:
        # 1. Загружаем исследуемый элемент
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            print(f"Item {item_id} not found.")
            return
            
        print(f"=== ANALYZING MATCHING FOR ITEM {item.id} ===")
        print(f"Title:         '{item.title}'")
        print(f"Source ID:     {item.source_id}")
        print(f"Published At:  {item.published_at}")
        
        # 2. Формируем запрос кандидатов
        start_date = item.published_at - timedelta(days=14)
        
        # Замеряем, сколько кандидатов вернул запрос
        candidates_query = db.query(Item).filter(
            Item.source_id == item.source_id,
            Item.id != item.id,
            Item.published_at >= start_date,
            Item.published_at <= item.published_at
        )
        candidates = candidates_query.order_by(Item.published_at.desc()).limit(100).all()
        candidates_count = len(candidates)
        print(f"\n1. Candidates returned by query: {candidates_count}")
        
        # 3. Получаем EXPLAIN для этого запроса, чтобы увидеть используемые индексы
        sql_str = str(candidates_query.order_by(Item.published_at.desc()).limit(100).statement.compile(compile_kwargs={"literal_binds": True}))
        explain_query = f"EXPLAIN {sql_str}"
        explain_results = db.execute(text(explain_query)).all()
        
        print("\n2. PostgreSQL EXPLAIN output (Indexes used):")
        for row in explain_results:
            print(f"   {row[0]}")
            
        # 4. Подсчитываем реальное число сравнений заголовков
        # В ItemService логика следующая:
        # - Сначала проверяем Level 4 (одинаковый заголовок) через next()
        # - Если title_dup найден, то для него SequenceMatcher не вызывается, а сразу идет добавление в relations.
        # - Для остальных кандидатов (которые не совпали с URL или title_dup) вызывается calculate_title_similarity (SequenceMatcher)
        
        comparisons_performed = 0
        current_title_match = normalize_title_for_matching(item.title)
        
        # Симулируем Level 4 next()
        title_dup = None
        for cand in candidates:
            comparisons_performed += 1 # Сравнение нормализованных строк
            if normalize_title_for_matching(cand.title) == current_title_match:
                title_dup = cand
                break
                
        # Симулируем Level 5 similarity
        similarity_comparisons = 0
        for cand in candidates:
            # Исключаем title_dup
            if title_dup and cand.id == title_dup.id:
                continue
            # Выполняется реальный SequenceMatcher
            similarity_comparisons += 1
            calculate_title_similarity(item.title, cand.title)
            
        total_comparisons = comparisons_performed + similarity_comparisons
        print(f"\n3. Comparisons performed:")
        print(f"   - Level 4 exact title string normalization checks: {comparisons_performed}")
        print(f"   - Level 5 fuzzy title similarity (SequenceMatcher ratio): {similarity_comparisons}")
        print(f"   - Total comparisons performed for this item:      {total_comparisons}")
        print("=============================================\n")
        
    finally:
        db.close()

if __name__ == "__main__":
    # Исследуем item 306 ("The state of enterprise AI")
    analyze_item(306)
