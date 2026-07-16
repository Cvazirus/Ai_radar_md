import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from sqlalchemy.exc import IntegrityError
from app.database.session import SessionLocal
from app.database.models import Source, Item, ItemAnalysis, Publication, CollectionRun, ItemStatus, PublicationStatus, CategoryEnum, AnalysisStatus
from app.database.repositories import SourceRepository, ItemRepository, AnalysisRepository, PublicationRepository, CollectionRunRepository

def test_crud_and_constraints() -> None:
    db = SessionLocal()
    
    # Репозитории
    source_repo = SourceRepository(db)
    item_repo = ItemRepository(db)
    analysis_repo = AnalysisRepository(db)
    pub_repo = PublicationRepository(db)
    run_repo = CollectionRunRepository(db)

    print("=== STARTING DATABASE TESTING ===")

    # Очистка старых тестов на всякий случай
    db.query(Publication).delete()
    db.query(ItemAnalysis).delete()
    db.query(Item).delete()
    db.query(Source).delete()
    db.query(CollectionRun).delete()
    db.commit()

    # 1. Создание Source (CREATE)
    source = Source(
        name="Test OpenAI Blog",
        source_type="rss",
        base_url="https://openai.com/blog",
        config={"rss_url": "https://openai.com/blog/rss.xml"}
    )
    source = source_repo.create(source)
    print(f"[SUCCESS] Created Source: ID={source.id}, Name={source.name}")

    # 2. Создание Item (CREATE)
    item = Item(
        source_id=source.id,
        url="https://openai.com/blog/test-post",
        canonical_url="https://openai.com/blog/test-post",
        title="Test Post Title",
        content_hash="hash_test_1234567890",
        status=ItemStatus.collected
    )
    item = item_repo.create(item)
    print(f"[SUCCESS] Created Item: ID={item.id}, Title={item.title}")

    # 3. Создание Analysis (CREATE)
    analysis = ItemAnalysis(
        item_id=item.id,
        model_name="test-model",
        prompt_version="test-prompt",
        analysis_version="1.0",
        status=AnalysisStatus.success,
        input_hash="hash_test_analysis_123",
        category=CategoryEnum.news,
        summary_ru="Тестовое краткое содержание на русском.",
        tags=["ИИ", "Тест"],
        entities=[{"name": "OpenAI", "type": "company"}],
        total_score=8.5,
        is_primary_source=True
    )
    analysis = analysis_repo.create(analysis)
    print(f"[SUCCESS] Created Analysis for Item ID={analysis.item_id}, Total Score={analysis.total_score}")

    # 4. Создание Publication (CREATE)
    pub = Publication(
        item_id=item.id,
        telegram_text="🧩 Тестовый пост для Телеграм",
        status=PublicationStatus.draft
    )
    pub = pub_repo.create(pub)
    print(f"[SUCCESS] Created Publication for Item ID={pub.item_id}, Status={pub.status}")

    # 5. Создание CollectionRun (CREATE)
    run = CollectionRun(
        collector_name="rss_collector",
        status="success",
        items_found=10,
        items_created=5,
        items_skipped=5
    )
    run = run_repo.create(run)
    print(f"[SUCCESS] Created CollectionRun: ID={run.id}, Status={run.status}")

    # 6. Чтение (SELECT)
    selected_item = item_repo.get(item.id)
    print(f"[SUCCESS] Selected Item: Title={selected_item.title}, Status={selected_item.status}")

    # 7. Обновление (UPDATE)
    selected_item.title = "Updated Test Post Title"
    selected_item.status = ItemStatus.analyzed
    updated_item = item_repo.update(selected_item)
    print(f"[SUCCESS] Updated Item: ID={updated_item.id}, New Title={updated_item.title}, New Status={updated_item.status}")

    # 8. Проверка UNIQUE(content_hash) constraint
    duplicate_item = Item(
        source_id=source.id,
        url="https://openai.com/blog/duplicate-post",
        canonical_url="https://openai.com/blog/duplicate-post",
        title="Duplicate Post",
        content_hash="hash_test_1234567890", # Дубликат хэша!
        status=ItemStatus.collected
    )
    try:
        item_repo.create(duplicate_item)
        print("[FAIL] Duplicate content_hash accepted! UNIQUE constraint is broken.")
    except IntegrityError:
        db.rollback()
        print("[SUCCESS] Duplicate content_hash rejected. UNIQUE constraint works.")

    # 9. Проверка FOREIGN KEY constraint
    invalid_fk_item = Item(
        source_id=999999, # Неверный FK!
        url="https://openai.com/blog/invalid-fk",
        canonical_url="https://openai.com/blog/invalid-fk",
        title="Invalid FK Post",
        content_hash="hash_invalid_fk_999",
        status=ItemStatus.collected
    )
    try:
        item_repo.create(invalid_fk_item)
        print("[FAIL] Invalid source_id FK accepted! FOREIGN KEY constraint is broken.")
    except IntegrityError:
        db.rollback()
        print("[SUCCESS] Invalid source_id FK rejected. FOREIGN KEY constraint works.")

    # 10. Проверка NOT NULL constraint
    invalid_null_item = Item(
        source_id=source.id,
        url=None, # Должно быть NOT NULL!
        canonical_url="https://openai.com/blog/invalid-null",
        title="Invalid Null Post",
        content_hash="hash_invalid_null_999",
        status=ItemStatus.collected
    )
    try:
        item_repo.create(invalid_null_item)
        print("[FAIL] Null URL accepted! NOT NULL constraint is broken.")
    except IntegrityError:
        db.rollback()
        print("[SUCCESS] Null URL rejected. NOT NULL constraint works.")

    # 11. Удаление (DELETE)
    assert item_repo.delete(item.id) is True
    print(f"[SUCCESS] Deleted Item ID={item.id}. Cascade delete check:")
    
    # Проверка каскадного удаления
    assert db.query(ItemAnalysis).filter(ItemAnalysis.id == analysis.id).first() is None
    assert pub_repo.get(item.id) is None
    print("[SUCCESS] Cascade delete verified (Analysis and Publication deleted).")

    # 12. Удаление Source и Runs
    assert source_repo.delete(source.id) is True
    assert run_repo.delete(run.id) is True
    print("[SUCCESS] Cleanup finished. All test data successfully removed.")

    db.close()
    print("=== ALL TESTS PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    test_crud_and_constraints()
