from datetime import datetime, timezone
from typing import List
import feedparser
import structlog
from app.collectors.base import BaseCollector
from app.collectors.schemas import CollectedItem
from app.collectors.http_utils import fetch_text

logger = structlog.get_logger()

ARXIV_API_URL = "http://export.arxiv.org/api/query"


class ArxivCollector(BaseCollector):
    """Собирает недавние статьи через arXiv Query API (export.arxiv.org/api/query)."""

    def __init__(
        self,
        source_name: str,
        query: str,
        max_results: int = 30,
        timeout_seconds: int = 20,
    ):
        self._source_name = source_name
        self.query = query
        self.max_results = min(max(max_results, 1), 100)
        self.timeout = timeout_seconds

    @property
    def name(self) -> str:
        return self._source_name

    @property
    def source_type(self) -> str:
        return "arxiv"

    def collect(self) -> List[CollectedItem]:
        logger.info("arxiv_collection_started", source_name=self.name, query=self.query)
        try:
            feed_content = fetch_text(
                ARXIV_API_URL,
                params={
                    "search_query": self.query,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                    "max_results": self.max_results,
                },
                headers={"User-Agent": "AI-Radar/0.1 (+collector)"},
                timeout_seconds=self.timeout,
                source_name=self.name,
            )
        except Exception as e:
            logger.error("arxiv_fetch_failed", source_name=self.name, query=self.query, error=str(e))
            raise

        parsed = feedparser.parse(feed_content)
        items: List[CollectedItem] = []
        for entry in parsed.entries:
            try:
                url = entry.get("link")
                title = entry.get("title")
                if not url or not title:
                    continue

                authors = [a.get("name") for a in entry.get("authors", []) if a.get("name")]
                categories = [t.get("term") for t in entry.get("tags", []) if t.get("term")]

                pub_parsed = entry.get("published_parsed")
                published_at = None
                if pub_parsed:
                    try:
                        published_at = datetime(*pub_parsed[:6], tzinfo=timezone.utc)
                    except Exception:
                        pass

                arxiv_id = entry.get("id")

                items.append(CollectedItem(
                    source_name=self.name,
                    source_type=self.source_type,
                    external_id=arxiv_id,
                    url=url,
                    title=" ".join(title.split()),
                    author=", ".join(authors) if authors else None,
                    text=entry.get("summary"),
                    published_at=published_at,
                    metadata={"categories": categories, "arxiv_id": arxiv_id},
                ))
            except Exception as e:
                logger.warn("arxiv_item_parse_failed", source_name=self.name, error=str(e))

        logger.info("arxiv_collection_finished", source_name=self.name, items_found=len(items))
        return items
