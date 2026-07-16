import time
from datetime import datetime, timezone
from typing import List, Optional
import feedparser
import httpx
import structlog
from app.collectors.base import BaseCollector
from app.collectors.schemas import CollectedItem

logger = structlog.get_logger()

class RSSCollector(BaseCollector):
    def __init__(self, source_name: str, feed_url: str, timeout_seconds: int = 20):
        self._source_name = source_name
        self.feed_url = feed_url
        self.timeout = timeout_seconds

    @property
    def name(self) -> str:
        return self._source_name

    @property
    def source_type(self) -> str:
        return "rss"

    def _fetch_feed(self) -> str:
        headers = {"User-Agent": "AI-Radar/0.1 (+collector)"}
        max_retries = 3
        retry_delay = 2.0
        retry_status_codes = {429, 500, 502, 503, 504}
        
        for attempt in range(1, max_retries + 1):
            try:
                # Ограничиваем максимальный размер ответа (5 МБ)
                with httpx.Client(follow_redirects=True, timeout=self.timeout) as client:
                    resp = client.get(self.feed_url, headers=headers)
                    
                    if resp.status_code == 200:
                        if len(resp.content) > 5 * 1024 * 1024:
                            raise ValueError(f"Response too large: {len(resp.content)} bytes")
                        return resp.text
                    
                    if resp.status_code in retry_status_codes:
                        raise httpx.HTTPStatusError(
                            f"HTTP Status {resp.status_code}", 
                            request=resp.request, 
                            response=resp
                        )
                    
                    resp.raise_for_status()
                    
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
                logger.warn(
                    "rss_fetch_attempt_failed",
                    source_name=self.name,
                    feed_url=self.feed_url,
                    attempt=attempt,
                    error=str(e)
                )
                if attempt == max_retries:
                    raise e
                time.sleep(retry_delay * attempt)
                
        raise RuntimeError("Unexpected end of retry loop")

    def collect(self) -> List[CollectedItem]:
        logger.info("rss_collection_started", source_name=self.name, feed_url=self.feed_url)
        start_time = time.time()
        
        try:
            feed_content = self._fetch_feed()
            logger.info("rss_fetch_success", source_name=self.name, feed_url=self.feed_url)
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "rss_fetch_failed",
                source_name=self.name,
                feed_url=self.feed_url,
                duration_ms=duration_ms,
                error_type=type(e).__name__,
                error=str(e)
            )
            raise e

        try:
            parsed = feedparser.parse(feed_content)
            if parsed.get("bozo"):
                bozo_exc = parsed.get("bozo_exception")
                logger.warn(
                    "rss_parse_warning",
                    source_name=self.name,
                    feed_url=self.feed_url,
                    exception=str(bozo_exc)
                )
                
            logger.info(
                "rss_parse_success",
                source_name=self.name,
                feed_url=self.feed_url,
                entries_count=len(parsed.entries)
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "rss_parse_failed",
                source_name=self.name,
                feed_url=self.feed_url,
                duration_ms=duration_ms,
                error_type=type(e).__name__,
                error=str(e)
            )
            raise e

        collected_items = []
        for entry in parsed.entries:
            try:
                ext_id = entry.get("id") or entry.get("guid") or entry.get("link")
                url = entry.get("link")
                title = entry.get("title")
                
                if not url or not title:
                    logger.warn(
                        "rss_item_invalid",
                        source_name=self.name,
                        feed_url=self.feed_url,
                        reason="missing_link_or_title"
                    )
                    continue

                author = entry.get("author")
                if not author and entry.get("author_detail"):
                    author = entry.author_detail.get("name")
                    
                text_val = None
                if entry.get("content"):
                    text_val = entry.content[0].get("value")
                
                if not text_val:
                    text_val = entry.get("summary") or entry.get("description")
                    
                pub_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                published_at = None
                if pub_parsed:
                    try:
                        published_at = datetime(*pub_parsed[:6], tzinfo=timezone.utc)
                    except Exception:
                        pass

                tags = []
                if entry.get("tags"):
                    tags = [t.get("term") for t in entry.tags if t.get("term")]
                    
                metadata = {
                    "tags": tags,
                    "updated": entry.get("updated"),
                    "comments": entry.get("comments")
                }

                item = CollectedItem(
                    source_name=self.name,
                    source_type=self.source_type,
                    external_id=ext_id,
                    url=url,
                    title=title,
                    author=author,
                    text=text_val,
                    published_at=published_at,
                    metadata=metadata
                )
                collected_items.append(item)
                
            except Exception as e:
                logger.warn(
                    "rss_item_parse_failed",
                    source_name=self.name,
                    feed_url=self.feed_url,
                    error=str(e)
                )
                
        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "rss_collection_finished",
            source_name=self.name,
            feed_url=self.feed_url,
            duration_ms=duration_ms,
            items_found=len(collected_items)
        )
        return collected_items
