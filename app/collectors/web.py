import json
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin
import structlog
import trafilatura
from bs4 import BeautifulSoup
from app.collectors.base import BaseCollector
from app.collectors.schemas import CollectedItem
from app.collectors.http_utils import fetch_text

logger = structlog.get_logger()


class WebCollector(BaseCollector):
    """Общий коллектор для сайтов без RSS: собирает ссылки со страницы-листинга
    (`listing_url`) и вытаскивает чистый текст/заголовок/автора/дату каждой
    статьи через trafilatura."""

    def __init__(
        self,
        source_name: str,
        listing_url: str,
        link_selector: str = "a",
        link_pattern: Optional[str] = None,
        max_items: int = 15,
        timeout_seconds: int = 20,
    ):
        self._source_name = source_name
        self.listing_url = listing_url
        self.link_selector = link_selector
        self.link_pattern = re.compile(link_pattern) if link_pattern else None
        self.max_items = max(1, max_items)
        self.timeout = timeout_seconds

    @property
    def name(self) -> str:
        return self._source_name

    @property
    def source_type(self) -> str:
        return "web"

    def _extract_links(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        seen = set()
        links: List[str] = []
        for a in soup.select(self.link_selector):
            href = a.get("href")
            if not href:
                continue
            absolute = urljoin(self.listing_url, href)
            if self.link_pattern and not self.link_pattern.search(absolute):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append(absolute)
            if len(links) >= self.max_items:
                break
        return links

    def collect(self) -> List[CollectedItem]:
        logger.info("web_collection_started", source_name=self.name, listing_url=self.listing_url)
        headers = {"User-Agent": "AI-Radar/0.1 (+collector)"}

        try:
            listing_html = fetch_text(
                self.listing_url, headers=headers, timeout_seconds=self.timeout, source_name=self.name,
            )
        except Exception as e:
            logger.error("web_listing_fetch_failed", source_name=self.name, url=self.listing_url, error=str(e))
            raise

        links = self._extract_links(listing_html)
        items: List[CollectedItem] = []

        for link in links:
            try:
                page_html = fetch_text(link, headers=headers, timeout_seconds=self.timeout, source_name=self.name)
            except Exception as e:
                logger.warn("web_page_fetch_failed", source_name=self.name, url=link, error=str(e))
                continue

            extracted = self._extract_article(page_html, link)
            if not extracted:
                continue

            title = extracted.get("title")
            text = extracted.get("text")
            if not title or not text:
                continue

            published_at = None
            date_str = extracted.get("date")
            if date_str:
                try:
                    published_at = datetime.fromisoformat(date_str)
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    published_at = None

            items.append(CollectedItem(
                source_name=self.name,
                source_type=self.source_type,
                external_id=link,
                url=link,
                title=title,
                author=extracted.get("author"),
                text=text,
                published_at=published_at,
                metadata={"hostname": extracted.get("hostname")},
            ))

        logger.info("web_collection_finished", source_name=self.name, items_found=len(items))
        return items

    def _extract_article(self, page_html: str, url: str) -> Optional[dict]:
        try:
            extracted_json = trafilatura.extract(
                page_html, url=url, output_format="json", with_metadata=True
            )
            if not extracted_json:
                return None
            return json.loads(extracted_json)
        except Exception as e:
            logger.warn("web_page_extract_failed", source_name=self.name, url=url, error=str(e))
            return None
