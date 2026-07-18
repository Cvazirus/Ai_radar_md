from datetime import datetime
from typing import List, Optional
import structlog
from app.collectors.base import BaseCollector
from app.collectors.schemas import CollectedItem
from app.collectors.http_utils import fetch_json

logger = structlog.get_logger()

GITHUB_API_URL = "https://api.github.com/search/repositories"


class GithubCollector(BaseCollector):
    """Собирает трендовые/недавно обновлённые репозитории через GitHub Search API."""

    def __init__(
        self,
        source_name: str,
        query: str,
        per_page: int = 20,
        sort: str = "stars",
        order: str = "desc",
        token: Optional[str] = None,
        timeout_seconds: int = 20,
    ):
        self._source_name = source_name
        self.query = query
        self.per_page = min(max(per_page, 1), 100)
        self.sort = sort
        self.order = order
        self.token = token
        self.timeout = timeout_seconds

    @property
    def name(self) -> str:
        return self._source_name

    @property
    def source_type(self) -> str:
        return "github"

    def _headers(self) -> dict:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "AI-Radar/0.1 (+collector)"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def collect(self) -> List[CollectedItem]:
        logger.info("github_collection_started", source_name=self.name, query=self.query)
        try:
            data = fetch_json(
                GITHUB_API_URL,
                params={"q": self.query, "sort": self.sort, "order": self.order, "per_page": self.per_page},
                headers=self._headers(),
                timeout_seconds=self.timeout,
                source_name=self.name,
            )
        except Exception as e:
            logger.error("github_fetch_failed", source_name=self.name, query=self.query, error=str(e))
            raise

        items: List[CollectedItem] = []
        for repo in data.get("items", []):
            try:
                url = repo.get("html_url")
                title = repo.get("full_name")
                if not url or not title:
                    continue

                description = repo.get("description") or ""
                topics = repo.get("topics") or []
                text = description
                if topics:
                    text = f"{text}\n\nTopics: {', '.join(topics)}".strip()

                pushed_at = None
                if repo.get("pushed_at"):
                    try:
                        pushed_at = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
                    except ValueError:
                        pushed_at = None

                items.append(CollectedItem(
                    source_name=self.name,
                    source_type=self.source_type,
                    external_id=str(repo["id"]) if repo.get("id") is not None else None,
                    url=url,
                    title=title,
                    author=(repo.get("owner") or {}).get("login"),
                    text=text or None,
                    published_at=pushed_at,
                    metadata={
                        "stars": repo.get("stargazers_count", 0),
                        "forks": repo.get("forks_count", 0),
                        "language": repo.get("language"),
                        "topics": topics,
                    },
                ))
            except Exception as e:
                logger.warn("github_item_parse_failed", source_name=self.name, error=str(e))

        logger.info("github_collection_finished", source_name=self.name, items_found=len(items))
        return items
