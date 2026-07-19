from datetime import datetime
from typing import List, Optional
import structlog
from app.collectors.base import BaseCollector
from app.collectors.schemas import CollectedItem
from app.collectors.http_utils import fetch_json

logger = structlog.get_logger()

HF_API_URL = "https://huggingface.co/api/models"


class HuggingFaceCollector(BaseCollector):
    """Собирает недавно созданные/трендовые модели через Hugging Face Hub API."""

    def __init__(
        self,
        source_name: str,
        sort: str = "createdAt",
        direction: int = -1,
        limit: int = 20,
        search: Optional[str] = None,
        timeout_seconds: int = 20,
    ):
        self._source_name = source_name
        self.sort = sort
        self.direction = direction
        self.limit = min(max(limit, 1), 100)
        self.search = search
        self.timeout = timeout_seconds

    @property
    def name(self) -> str:
        return self._source_name

    @property
    def source_type(self) -> str:
        return "huggingface"

    def collect(self) -> List[CollectedItem]:
        logger.info("huggingface_collection_started", source_name=self.name)
        params = {"sort": self.sort, "direction": self.direction, "limit": self.limit}
        if self.search:
            params["search"] = self.search

        try:
            data = fetch_json(
                HF_API_URL,
                params=params,
                headers={"User-Agent": "AI-Radar/0.1 (+collector)"},
                timeout_seconds=self.timeout,
                source_name=self.name,
            )
        except Exception as e:
            logger.error("huggingface_fetch_failed", source_name=self.name, error=str(e))
            raise

        items: List[CollectedItem] = []
        for model in data:
            try:
                model_id = model.get("id") or model.get("modelId")
                if not model_id:
                    continue
                url = f"https://huggingface.co/{model_id}"

                tags = model.get("tags") or []
                pipeline_tag = model.get("pipeline_tag")
                text_parts = []
                if pipeline_tag:
                    text_parts.append(f"Pipeline: {pipeline_tag}")
                if tags:
                    text_parts.append(f"Tags: {', '.join(tags)}")

                created_at = None
                if model.get("createdAt"):
                    try:
                        created_at = datetime.fromisoformat(model["createdAt"].replace("Z", "+00:00"))
                    except ValueError:
                        created_at = None

                author = model_id.split("/")[0] if "/" in model_id else None

                items.append(CollectedItem(
                    source_name=self.name,
                    source_type=self.source_type,
                    external_id=model_id,
                    url=url,
                    title=model_id,
                    author=author,
                    text="\n".join(text_parts) or None,
                    published_at=created_at,
                    metadata={
                        "downloads": model.get("downloads", 0),
                        "likes": model.get("likes", 0),
                        "pipeline_tag": pipeline_tag,
                        "tags": tags,
                    },
                ))
            except Exception as e:
                logger.warn("huggingface_item_parse_failed", source_name=self.name, error=str(e))

        logger.info("huggingface_collection_finished", source_name=self.name, items_found=len(items))
        return items
