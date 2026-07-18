import sys
from os.path import abspath, dirname, join
sys.path.insert(0, dirname(dirname(abspath(__file__))))

import yaml

from app.database.session import SessionLocal
from app.database.models import Source
from app.database.repositories import SourceRepository

SOURCES_YAML_PATH = join(dirname(dirname(abspath(__file__))), "config", "news_sources.yaml")


def _trust_level_from_priority(priority) -> int:
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        return 1
    if priority <= 1:
        return 3
    if priority == 2:
        return 2
    return 1


def load_sources_from_yaml(path: str = SOURCES_YAML_PATH) -> list[dict]:
    """Load the source registry from config/news_sources.yaml and map each
    entry onto the fields expected by the Source model."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    result = []
    for entry in raw.get("sources", []):
        feed_url = entry.get("feed_url")
        if not feed_url:
            print(f"[SKIPPED] Source id='{entry.get('id')}': no feed_url in yaml")
            continue

        result.append({
            "name": entry.get("name") or entry["id"],
            "source_type": entry.get("source_type", "rss"),
            "base_url": entry.get("url") or feed_url,
            "enabled": bool(entry.get("enabled", True)),
            "trust_level": _trust_level_from_priority(entry.get("priority")),
            "config": {
                "slug": entry.get("id"),
                "feed_url": feed_url,
                "timeout_seconds": entry.get("timeout_seconds", 20),
                "language": entry.get("language"),
                "tags": entry.get("tags", []),
                "enabled": bool(entry.get("enabled", True)),
            },
        })
    return result


def _find_existing(db, src_data: dict) -> Source | None:
    # Primary match: same source_type + feed_url (stable even if name changes)
    existing = db.query(Source).filter(
        Source.source_type == src_data["source_type"],
        Source.config["feed_url"].astext == src_data["config"]["feed_url"],
    ).first()
    if existing:
        return existing

    # Fallback match: same name + type (covers rows created before this
    # migrated to the yaml-driven registry)
    return db.query(Source).filter(
        Source.name == src_data["name"],
        Source.source_type == src_data["source_type"],
    ).first()


def seed_sources() -> None:
    db = SessionLocal()
    repo = SourceRepository(db)

    print(f"=== SEEDING SOURCES FROM {SOURCES_YAML_PATH} ===")

    sources = load_sources_from_yaml()

    created_count = 0
    updated_count = 0
    skipped_count = 0

    for src_data in sources:
        existing = _find_existing(db, src_data)

        if existing:
            base_url_changed = (existing.base_url != src_data["base_url"])

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
            new_src = Source(
                name=src_data["name"],
                source_type=src_data["source_type"],
                base_url=src_data["base_url"],
                enabled=src_data["enabled"],
                trust_level=src_data["trust_level"],
                config=src_data["config"],
            )
            repo.create(new_src)
            print(f"[CREATED] Source: name='{new_src.name}', type='{new_src.source_type}'")
            created_count += 1

    db.close()
    print(f"=== SEEDING FINISHED: Created={created_count}, Updated={updated_count}, Skipped={skipped_count} ===")


if __name__ == "__main__":
    seed_sources()
