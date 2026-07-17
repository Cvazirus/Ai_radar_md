"""Digest builder — generates Markdown news digests from analyzed items."""
import os
import json
import structlog
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database.models import (
    Item, ItemStatus, ItemAnalysis, AnalysisStatus, CategoryEnum, Source
)

logger = structlog.get_logger()

# Categories for digest sections
SECTION_MAP = {
    "model_release": "Новые модели",
    "local_model": "Новые модели",
    "agent": "Агентные системы",
    "coding_agent": "Агентные системы",
    "agent_harness": "Агентные системы",
    "mcp_server": "Агентные системы",
    "skill": "Skills и Harnesses",
    "prompt": "Skills и Harnesses",
    "research": "Исследования",
    "dataset": "Исследования",
    "benchmark": "Исследования",
    "framework": "Open Source",
    "api": "Open Source",
    "tutorial": "Практические материалы",
    "news": "Главное",
    "opinion": "Главное",
    "company_update": "Главное",
    "product_update": "Главное",
    "security": "Безопасность",
    "funding": "Главное",
    "other": "Главное",
}

# AI-related keywords for filtering
AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "large language model", "gpt", "claude", "gemini", "llama",
    "transformer", "neural", "model", "agent", "coding", "open source",
    "github", "huggingface", "arxiv", "research", "benchmark", "safety",
    "машинное обучение", "нейросеть", "искусственный интеллект",
    "языковая модель", "агент", "исследование",
]


class DigestService:
    """Builds Markdown digests from analyzed items."""

    def __init__(self, db: Session):
        self.db = db

    def build_digest(
        self,
        limit: int = 20,
        min_score: float = 0.0,
        include_sections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build a digest from analyzed items."""
        logger.info("digest_build_started", limit=limit, min_score=min_score)

        # Get successful analyses
        analyses = self.db.query(ItemAnalysis).filter(
            ItemAnalysis.status == AnalysisStatus.success,
            ItemAnalysis.total_score >= min_score,
        ).order_by(ItemAnalysis.total_score.desc()).limit(limit * 3).all()

        if not analyses:
            logger.info("digest_build_completed", items=0, sections=0)
            return {"items": [], "sections": {}, "stats": {"total": 0}}

        # Group by section
        sections = {}
        items_used = 0

        for analysis in analyses:
            if items_used >= limit:
                break

            item = self.db.query(Item).filter(Item.id == analysis.item_id).first()
            if not item:
                continue

            # Get section
            category = str(analysis.category.value if hasattr(analysis.category, 'value') else analysis.category)
            section = SECTION_MAP.get(category, "Главное")

            # Skip if section not wanted
            if include_sections and section not in include_sections:
                continue

            # Get source name
            source_name = "Unknown"
            if item.source_id:
                source = self.db.query(Source).filter(Source.id == item.source_id).first()
                if source:
                    source_name = source.name

            # Build item data
            tags_data = analysis.tags if isinstance(analysis.tags, dict) else {}
            tags_list = tags_data.get("tags", []) if isinstance(tags_data, dict) else []

            item_data = {
                "item_id": item.id,
                "title": item.title,
                "url": item.url,
                "source": source_name,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "category": category,
                "summary_ru": analysis.summary_ru or "",
                "what_is_new": analysis.what_is_new or "",
                "why_important": analysis.why_important or "",
                "practical_use": analysis.practical_use or "",
                "total_score": float(analysis.total_score) if analysis.total_score else 0.0,
                "tags": tags_list[:5],
                "language": item.language or "en",
            }

            if section not in sections:
                sections[section] = []
            sections[section].append(item_data)
            items_used += 1

        # Build stats
        total_in_db = self.db.query(ItemAnalysis).filter(
            ItemAnalysis.status == AnalysisStatus.success
        ).count()

        stats = {
            "total_analyzed": total_in_db,
            "total_in_digest": items_used,
            "sections_count": len(sections),
            "built_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info("digest_build_completed", items=items_used, sections=len(sections))
        return {"items": [item for section_items in sections.values() for item in section_items], "sections": sections, "stats": stats}

    def render_markdown(self, digest: Dict[str, Any]) -> str:
        """Render digest as Markdown."""
        lines = []
        now = datetime.now(timezone.utc)

        lines.append("# AI Radar")
        lines.append("")
        lines.append(f"**Дата:** {now.strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append("")

        stats = digest.get("stats", {})
        lines.append(f"Проанализировано: {stats.get('total_analyzed', 0)} | В выпуск: {stats.get('total_in_digest', 0)}")
        lines.append("")

        sections = digest.get("sections", {})

        # Section order
        section_order = [
            "Главное",
            "Новые модели",
            "Агентные системы",
            "Исследования",
            "Open Source",
            "Skills и Harnesses",
            "Практические материалы",
            "Безопасность",
        ]

        for section_name in section_order:
            items = sections.get(section_name, [])
            if not items:
                continue

            lines.append(f"## {section_name}")
            lines.append("")

            for item in items:
                lines.append(f"### {item['title']}")
                lines.append("")
                lines.append(f"**Источник:** {item['source']} | **Дата:** {item.get('published_at', 'N/A')[:10]}")
                lines.append("")

                if item.get("summary_ru"):
                    lines.append(item["summary_ru"])
                    lines.append("")

                if item.get("what_is_new"):
                    lines.append(f"**Что нового:** {item['what_is_new']}")
                    lines.append("")

                if item.get("why_important"):
                    lines.append(f"**Почему важно:** {item['why_important']}")
                    lines.append("")

                if item.get("tags"):
                    lines.append(f"**Теги:** {', '.join(item['tags'])}")
                    lines.append("")

                lines.append(f"**Ссылка:** [{item['title']}]({item['url']})")
                lines.append("")
                lines.append("---")
                lines.append("")

        # Footer
        lines.append("*Сгенерировано AI Radar*")

        return "\n".join(lines)

    def save_digest(self, markdown: str, digest: Dict[str, Any]) -> str:
        """Save digest to file. Returns file path."""
        output_dir = Path("/app/output/digests")
        output_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        filename = now.strftime("%Y-%m-%d_%H-%M_AI_RADAR.md")
        filepath = output_dir / filename

        # Atomic write
        tmp_path = filepath.with_suffix(".tmp")
        tmp_path.write_text(markdown, encoding="utf-8")
        tmp_path.rename(filepath)

        # Save metadata
        meta_path = filepath.with_suffix(".json")
        meta_path.write_text(json.dumps(digest.get("stats", {}), indent=2, default=str), encoding="utf-8")

        logger.info("digest_published", path=str(filepath), items=digest.get("stats", {}).get("total_in_digest", 0))
        return str(filepath)
