import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from app.database.session import SessionLocal
from app.database.models import Source
from app.database.repositories import SourceRepository

INITIAL_SOURCES = [
    {
        "name": "OpenAI News",
        "source_type": "rss",
        "base_url": "https://openai.com",
        "enabled": True,
        "trust_level": 3,
        "config": {
            "feed_url": "https://openai.com/news/rss.xml",
            "timeout_seconds": 20,
            "enabled": True
        }
    },
    {
        "name": "Hugging Face Blog",
        "source_type": "rss",
        "base_url": "https://huggingface.co",
        "enabled": True,
        "trust_level": 3,
        "config": {
            "feed_url": "https://huggingface.co/blog/feed.xml",
            "timeout_seconds": 20,
            "enabled": True
        }
    },
    {
        "name": "Habr AI Hub",
        "source_type": "rss",
        "base_url": "https://habr.com",
        "enabled": True,
        "trust_level": 2,
        "config": {
            "feed_url": "https://habr.com/ru/rss/hub/artificial_intelligence/all/",
            "timeout_seconds": 20,
            "enabled": True
        }
    },
    {
        "name": "Hacker News AI",
        "source_type": "rss",
        "base_url": "https://news.ycombinator.com",
        "enabled": True,
        "trust_level": 1,
        "config": {
            "feed_url": "https://hnrss.org/newest?q=AI",
            "timeout_seconds": 20,
            "enabled": True
        }
    },
    {
        "name": "GitHub Blog",
        "source_type": "rss",
        "base_url": "https://github.blog",
        "enabled": True,
        "trust_level": 2,
        "config": {
            "feed_url": "https://github.blog/feed/",
            "timeout_seconds": 20,
            "enabled": True
        }
    },
    {
        "name": "Google Research Blog",
        "source_type": "rss",
        "base_url": "https://research.google",
        "enabled": True,
        "trust_level": 3,
        "config": {
            "feed_url": "https://research.google/blog/rss/",
            "timeout_seconds": 20,
            "enabled": True
        }
    },
    # === Added 2026-07-19, verified live (HTTP 200, valid RSS, recent items) ===
    {
        "name": "TechCrunch",
        "source_type": "rss",
        "base_url": "https://techcrunch.com",
        "enabled": True,
        "trust_level": 2,
        "config": {
            "feed_url": "https://techcrunch.com/feed/",
            "timeout_seconds": 20,
            "enabled": True
        }
    },
    {
        "name": "WIRED",
        "source_type": "rss",
        "base_url": "https://www.wired.com",
        "enabled": True,
        "trust_level": 2,
        "config": {
            "feed_url": "https://www.wired.com/feed/rss",
            "timeout_seconds": 20,
            "enabled": True
        }
    },
    {
        "name": "Ars Technica",
        "source_type": "rss",
        "base_url": "https://arstechnica.com",
        "enabled": True,
        "trust_level": 2,
        "config": {
            "feed_url": "https://feeds.arstechnica.com/arstechnica/index",
            "timeout_seconds": 20,
            "enabled": True
        }
    },
    {
        "name": "MarkTechPost",
        "source_type": "rss",
        "base_url": "https://www.marktechpost.com",
        "enabled": True,
        "trust_level": 2,
        "config": {
            "feed_url": "https://www.marktechpost.com/feed/",
            "timeout_seconds": 20,
            "enabled": True
        }
    },
    {
        "name": "KDnuggets",
        "source_type": "rss",
        "base_url": "https://www.kdnuggets.com",
        "enabled": True,
        "trust_level": 2,
        "config": {
            "feed_url": "https://www.kdnuggets.com/feed",
            "timeout_seconds": 20,
            "enabled": True
        }
    }
]

def seed_sources() -> None:
    db = SessionLocal()
    repo = SourceRepository(db)
    
    print("=== SEEDING SOURCES ===")
    
    created_count = 0
    updated_count = 0
    skipped_count = 0
    
    for src_data in INITIAL_SOURCES:
        # Проверяем по имени и типу
        existing = db.query(Source).filter(
            Source.name == src_data["name"],
            Source.source_type == src_data["source_type"]
        ).first()
        
        # Или по config.feed_url
        if not existing:
            existing = db.query(Source).filter(
                Source.source_type == src_data["source_type"],
                Source.config["feed_url"].astext == src_data["config"]["feed_url"]
            ).first()
            
        if existing:
            # Проверяем, изменились ли конфиг или base_url
            base_url_changed = (existing.base_url != src_data["base_url"])
            
            # Сравниваем основные поля конфига
            current_config = existing.config or {}
            config_changed = False
            for k, v in src_data["config"].items():
                if current_config.get(k) != v:
                    config_changed = True
                    break
            
            if base_url_changed or config_changed:
                existing.base_url = src_data["base_url"]
                current_config.update(src_data["config"])
                existing.config = current_config
                repo.update(existing)
                print(f"[UPDATED] Source: name='{existing.name}', type='{existing.source_type}'")
                updated_count += 1
            else:
                print(f"[SKIPPED] Source: name='{existing.name}', type='{existing.source_type}'")
                skipped_count += 1
        else:
            # Создаем новый
            new_src = Source(
                name=src_data["name"],
                source_type=src_data["source_type"],
                base_url=src_data["base_url"],
                enabled=src_data["enabled"],
                trust_level=src_data["trust_level"],
                config=src_data["config"]
            )
            repo.create(new_src)
            print(f"[CREATED] Source: name='{new_src.name}', type='{new_src.source_type}'")
            created_count += 1
            
    db.close()
    print(f"=== SEEDING FINISHED: Created={created_count}, Updated={updated_count}, Skipped={skipped_count} ===")

if __name__ == "__main__":
    seed_sources()
