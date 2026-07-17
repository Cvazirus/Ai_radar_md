import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from unittest.mock import MagicMock, patch
from app.config import settings
from app.database.session import SessionLocal
from app.database.models import Source, Item, ItemStatus, CategoryEnum, ItemAnalysis, Publication, PublicationStatus
from app.services.analysis_service import AnalysisService
from app.llm.schemas import AnalysisResult, EntityResult, SourceClaim

def run_demo():
    db = SessionLocal()
    try:
        print("=== STARTING PHASE 5 PIPELINE DEMO ===")
        
        # 1. Зачистим все старые демонстрационные данные и сбросим collected
        db.query(Publication).filter(Publication.item_id >= 999900).delete(synchronize_session=False)
        db.query(ItemAnalysis).filter(ItemAnalysis.item_id >= 999900).delete(synchronize_session=False)
        db.query(Item).filter(Item.id >= 999900).delete(synchronize_session=False)
        # Сбросим любые leftover collected статусы, чтобы не мешали
        from sqlalchemy import update
        db.execute(update(Item).where(Item.status == ItemStatus.collected).values(status=ItemStatus.normalized))
        db.commit()

        # Создадим тестовый источник
        source = db.query(Source).filter(Source.id == 3).first()
        if not source:
            source = Source(id=3, name="Demo Source", source_type="rss", base_url="https://demo.com")
            db.add(source)
            db.commit()

        # Создадим тестовый Item
        item = Item(
            id=999999,
            source_id=3,
            title="Demo Article on Agents",
            url="https://demo.com/agents-are-cool",
            canonical_url="https://demo.com/agents-are-cool",
            raw_text="This is a breakthrough paper showing coding agents can solve 90% of issues.",
            content_hash="demo_content_hash_123",
            status=ItemStatus.collected
        )
        db.add(item)
        db.commit()
        print(f"Created demo item ID {item.id} with status: '{item.status}'")

        # 2. Мокаем LLMClient.analyze_item, чтобы симулировать успешный ответ модели
        result_mock = AnalysisResult(
            category=CategoryEnum.coding_agent,
            tags=["agents", "coding"],
            entities=[
                EntityResult(type="repository", name="gpt-5", canonical_name="openai/gpt-5", url="https://github.com/openai/gpt-5")
            ],
            summary_ru="Прорывное исследование возможностей кодинг-агентов.",
            what_is_new="Агенты решают 90% задач.",
            why_important="Ускоряет разработку ПО.",
            practical_use="Интеграция в IDE.",
            target_users=["developers", "architects"],
            is_primary_source=True,
            is_promotional=False,
            is_actionable=True,
            is_newsworthy=True,
            novelty_score=9,
            practicality_score=8,
            credibility_score=7,
            relevance_score=8,
            confidence=0.95,
            analysis_version="1.0",
            source_claims=[
                SourceClaim(
                    claim="Агенты решают 90% задач",
                    evidence_text="coding agents can solve 90% of issues",
                    evidence_type="explicit_statement",
                    confidence=0.9
                )
            ]
        )

        with patch("app.services.analysis_service.settings") as mock_settings, \
             patch("app.services.analysis_service.LLMClient") as mock_client_cls:
             
            mock_settings.LLM_ANALYSIS_ENABLED = True
            mock_settings.LLM_MODEL = "demo-gpt-4o"
            mock_settings.LLM_STORE_RAW_RESPONSE = True
            
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.analyze_item.return_value = result_mock
            mock_client.last_raw_response = '{"category": "coding_agent", "novelty_score": 9 ...}'
            
            service = AnalysisService(db)
            
            # Запускаем контур анализа
            print("\nRunning analysis_service.analyze_pending_items()...")
            stats = service.analyze_pending_items(limit=1)
            print(f"Stats returned: {stats}")

        # Проверим результаты в БД
        db.expire_all()
        updated_item = db.query(Item).filter(Item.id == 999999).first()
        print(f"\nItem status after successful analysis: '{updated_item.status}'")
        
        analysis = db.query(ItemAnalysis).filter(ItemAnalysis.item_id == 999999).first()
        if analysis:
            print("[SUCCESS] ItemAnalysis created in DB!")
            # total_score = (9*0.3) + (8*0.3) + (7*0.2) + (8*0.1) + (6*0.1) = 2.7 + 2.4 + 1.4 + 0.8 + 0.6 = 7.9
            # total_score = (9*0.3) + (8*0.3) + (7*0.2) + (8*0.1) = 2.7 + 2.4 + 1.4 + 0.8 = 7.3
            print(f"Calculated Total Score: {analysis.total_score} (Expected: 7.3)")
            print(f"Assigned Category:      {analysis.category.value}")
        else:
            print("[ERROR] ItemAnalysis NOT found in DB!")

        pub = db.query(Publication).filter(Publication.item_id == 999999).first()
        if pub:
            print("[SUCCESS] Publication draft created in DB!")
            print(f"Draft Telegram Text:    '{pub.telegram_text}' (empty on Phase 5)")
            print(f"Publication Status:     '{pub.status.value}'")
        else:
            print("[ERROR] Publication draft NOT found in DB!")

        # 3. Теперь протестируем сценарий ошибки анализа
        print("\n=== SIMULATING PIPELINE FAILURE ===")
        # Переводим статус обратно в collected
        updated_item.status = ItemStatus.collected
        db.commit()
        
        with patch("app.services.analysis_service.settings") as mock_settings, \
             patch("app.services.analysis_service.LLMClient") as mock_client_cls:
             
            mock_settings.LLM_ANALYSIS_ENABLED = True
            
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            # Симулируем падение провайдера
            mock_client.analyze_item.side_effect = Exception("LLM Provider Timeout Exception")
            
            service = AnalysisService(db)
            stats = service.analyze_pending_items(limit=1)
            print(f"Stats returned during failure: {stats}")

        db.expire_all()
        failed_item = db.query(Item).filter(Item.id == 999999).first()
        print(f"\nItem status after failed analysis: '{failed_item.status}'")
        print(f"Error saved in metadata:           '{failed_item.metadata_json.get('analysis_error')}'")
        
        failed_pub = db.query(Publication).filter(Publication.item_id == 999999).first()
        if not failed_pub:
            print("[SUCCESS] Publication draft was deleted/not created on failure!")
        else:
            print("[ERROR] Publication draft STILL exists in DB!")

        # Наводим порядок
        db.query(Publication).filter(Publication.item_id == 999999).delete()
        db.query(ItemAnalysis).filter(ItemAnalysis.item_id == 999999).delete()
        db.query(Item).filter(Item.id == 999999).delete()
        # Восстановим сброшенные collected
        db.execute(update(Item).where(Item.status == ItemStatus.normalized).values(status=ItemStatus.collected))
        db.commit()
        print("\nDemo cleaned up successfully.")
        
    finally:
        db.close()

if __name__ == "__main__":
    run_demo()
