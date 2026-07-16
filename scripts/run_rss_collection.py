import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

import structlog
from app.database.session import SessionLocal
from app.services.collection_service import CollectionService

logger = structlog.get_logger()

def run_collection() -> None:
    db = SessionLocal()
    try:
        service = CollectionService(db)
        stats = service.run_rss_collection()
        print("\n=== COLLECTION RUN COMPLETE ===")
        print(f"Total RSS Sources:  {stats['sources_total']}")
        print(f"Success Sources:    {stats['sources_success']}")
        print(f"Failed Sources:     {stats['sources_failed']}")
        print(f"Items Found:        {stats['items_found']}")
        print(f"Items Created:      {stats['items_created']}")
        print(f"Items Skipped:      {stats['items_skipped']}")
        print("===============================\n")
    except Exception as e:
        logger.error("rss_orchestration_failed", error=str(e))
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    run_collection()
