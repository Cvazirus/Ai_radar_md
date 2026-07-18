"""Telegram Publisher — real Telegram Bot API integration."""
import httpx
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import structlog
from app.config import settings

logger = structlog.get_logger()


@dataclass
class TelegramResult:
    success: bool
    message_id: Optional[int] = None
    error: Optional[str] = None
    error_code: Optional[int] = None
    data: Optional[Any] = None


class TelegramPublisher:
    """Real Telegram Bot API publisher using httpx."""

    BASE_URL = "https://api.telegram.org"

    RETRYABLE_CODES = {429, 500, 502, 503, 504}
    NON_RETRYABLE_CODES = {400, 401, 403, 404}

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML",
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHANNEL_ID
        self.parse_mode = parse_mode
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        if not self.bot_token or self.bot_token == "mock-token":
            logger.warning("telegram_no_token", message="Telegram bot token not configured")

        self._client = httpx.Client(
            base_url=f"{self.BASE_URL}/bot{self.bot_token}",
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": "AIRadar/1.0"},
        )

    def _request(self, method: str, data: Dict[str, Any]) -> TelegramResult:
        """Make API request with retry logic."""
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(f"/{method}", json=data)

                if response.status_code == 200:
                    result = response.json()
                    if result.get("ok"):
                        response_data = result.get("result")
                        msg_id = response_data.get("message_id") if isinstance(response_data, dict) else None
                        logger.info(
                            "telegram_api_success",
                            method=method,
                            message_id=msg_id,
                            attempt=attempt + 1,
                        )
                        return TelegramResult(success=True, message_id=msg_id, data=response_data)
                    else:
                        error_desc = result.get("description", "Unknown error")
                        error_code = result.get("error_code")
                        logger.error(
                            "telegram_api_error",
                            method=method,
                            error_code=error_code,
                            description=error_desc,
                        )
                        return TelegramResult(
                            success=False, error=error_desc, error_code=error_code
                        )

                if response.status_code in self.RETRYABLE_CODES:
                    last_error = f"HTTP {response.status_code}"
                    retry_after = self.retry_delay

                    if response.status_code == 429:
                        try:
                            retry_after = response.json().get("parameters", {}).get(
                                "retry_after", self.retry_delay
                            )
                        except Exception:
                            pass

                    if attempt < self.max_retries:
                        logger.warning(
                            "telegram_retry",
                            method=method,
                            status_code=response.status_code,
                            attempt=attempt + 1,
                            retry_after=retry_after,
                        )
                        time.sleep(retry_after)
                        continue

                if response.status_code in self.NON_RETRYABLE_CODES:
                    try:
                        error_data = response.json()
                        error_desc = error_data.get(
                            "description", f"HTTP {response.status_code}"
                        )
                        error_code = error_data.get(
                            "error_code", response.status_code
                        )
                    except Exception:
                        error_desc = f"HTTP {response.status_code}"
                        error_code = response.status_code

                    logger.error(
                        "telegram_non_retryable_error",
                        method=method,
                        status_code=response.status_code,
                        description=error_desc,
                    )
                    return TelegramResult(
                        success=False, error=error_desc, error_code=error_code
                    )

                last_error = f"HTTP {response.status_code}"
                if attempt < self.max_retries:
                    logger.warning(
                        "telegram_retry",
                        method=method,
                        status_code=response.status_code,
                        attempt=attempt + 1,
                    )
                    time.sleep(self.retry_delay)
                    continue

            except httpx.TimeoutException:
                last_error = "Timeout"
                if attempt < self.max_retries:
                    logger.warning(
                        "telegram_timeout",
                        method=method,
                        attempt=attempt + 1,
                    )
                    time.sleep(self.retry_delay)
                    continue
            except httpx.RequestError as e:
                last_error = str(e)
                if attempt < self.max_retries:
                    logger.warning(
                        "telegram_request_error",
                        method=method,
                        error=str(e),
                        attempt=attempt + 1,
                    )
                    time.sleep(self.retry_delay)
                    continue

        logger.error(
            "telegram_max_retries_exceeded",
            method=method,
            last_error=last_error,
            attempts=self.max_retries + 1,
        )
        return TelegramResult(
            success=False, error=f"Max retries exceeded: {last_error}"
        )

    def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: Optional[str] = None,
        disable_web_page_preview: bool = True,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> TelegramResult:
        """Send a text message."""
        data = {
            "chat_id": chat_id or self.chat_id,
            "text": text[:4096],
            "parse_mode": parse_mode or self.parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup is not None:
            data["reply_markup"] = reply_markup
        return self._request("sendMessage", data)

    def send_markdown(
        self,
        text: str,
        chat_id: Optional[str] = None,
        disable_web_page_preview: bool = True,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> TelegramResult:
        """Send a Markdown-formatted message."""
        return self.send_message(text, chat_id, "Markdown", disable_web_page_preview, reply_markup)

    def send_html(
        self,
        text: str,
        chat_id: Optional[str] = None,
        disable_web_page_preview: bool = True,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> TelegramResult:
        """Send an HTML-formatted message."""
        return self.send_message(text, chat_id, "HTML", disable_web_page_preview, reply_markup)

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> TelegramResult:
        data: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            data["text"] = text[:200]
        return self._request("answerCallbackQuery", data)

    def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: Optional[Dict[str, Any]],
    ) -> TelegramResult:
        return self._request("editMessageReplyMarkup", {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup,
        })

    def delete_message(self, chat_id: int, message_id: int) -> TelegramResult:
        return self._request("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    def get_updates(
        self,
        offset: Optional[int] = None,
        timeout: int = 20,
        limit: int = 100,
    ) -> TelegramResult:
        data: Dict[str, Any] = {"timeout": max(1, min(timeout, 50)), "limit": max(1, min(limit, 100))}
        if offset is not None:
            data["offset"] = offset
        return self._request("getUpdates", data)

    def send_photo(
        self,
        photo: str,
        caption: Optional[str] = None,
        chat_id: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> TelegramResult:
        """Send a photo with optional caption."""
        data = {
            "chat_id": chat_id or self.chat_id,
            "photo": photo,
        }
        if caption:
            data["caption"] = caption[:1024]
            data["parse_mode"] = parse_mode or self.parse_mode
        return self._request("sendPhoto", data)

    def send_media_group(
        self,
        media: List[Dict[str, Any]],
        chat_id: Optional[str] = None,
    ) -> TelegramResult:
        """Send a group of photos/videos/documents."""
        data = {
            "chat_id": chat_id or self.chat_id,
            "media": media[:10],
        }
        return self._request("sendMediaGroup", data)

    def send_document(
        self,
        document: str,
        caption: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> TelegramResult:
        """Send a document."""
        data = {
            "chat_id": chat_id or self.chat_id,
            "document": document,
        }
        if caption:
            data["caption"] = caption[:1024]
        return self._request("sendDocument", data)

    def get_me(self) -> TelegramResult:
        """Get bot information (for testing connection)."""
        return self._request("getMe", {})

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
