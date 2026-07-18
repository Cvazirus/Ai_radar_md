"""Tests for TelegramPublisher."""
import pytest
from unittest.mock import Mock, patch, MagicMock
import httpx
from app.publishers.telegram import TelegramPublisher, TelegramResult


class TestTelegramPublisher:
    """Test TelegramPublisher."""

    def test_init_with_config(self):
        """Publisher initializes with config values."""
        with patch("app.publishers.telegram.settings") as mock_settings:
            mock_settings.TELEGRAM_BOT_TOKEN = "test-token"
            mock_settings.TELEGRAM_CHANNEL_ID = "-100123"
            publisher = TelegramPublisher()
            assert publisher.bot_token == "test-token"
            assert publisher.chat_id == "-100123"

    def test_init_with_params(self):
        """Publisher accepts explicit parameters."""
        publisher = TelegramPublisher(
            bot_token="custom-token",
            chat_id="-100999",
        )
        assert publisher.bot_token == "custom-token"
        assert publisher.chat_id == "-100999"

    def test_send_message_success(self):
        """Successful message send."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 123},
        }
        publisher._client.post = Mock(return_value=mock_response)

        result = publisher.send_message("Hello")
        assert result.success is True
        assert result.message_id == 123

    def test_send_message_401_error(self):
        """401 Unauthorized returns error without retry."""
        publisher = TelegramPublisher(bot_token="bad-token", chat_id="-100")
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "ok": False,
            "error_code": 401,
            "description": "Unauthorized",
        }
        publisher._client.post = Mock(return_value=mock_response)

        result = publisher.send_message("Hello")
        assert result.success is False
        assert result.error_code == 401
        assert publisher._client.post.call_count == 1

    def test_send_message_429_retry(self):
        """429 Too Many Requests triggers retry."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100", retry_delay=0.01)

        rate_limit_response = Mock()
        rate_limit_response.status_code = 429
        rate_limit_response.json.return_value = {
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests",
            "parameters": {"retry_after": 0.01},
        }

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 456},
        }

        publisher._client.post = Mock(side_effect=[rate_limit_response, success_response])

        result = publisher.send_message("Hello")
        assert result.success is True
        assert result.message_id == 456
        assert publisher._client.post.call_count == 2

    def test_send_message_timeout_retry(self):
        """Timeout triggers retry."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100", retry_delay=0.01)

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 789},
        }

        publisher._client.post = Mock(
            side_effect=[
                httpx.TimeoutException("timeout"),
                success_response,
            ]
        )

        result = publisher.send_message("Hello")
        assert result.success is True
        assert publisher._client.post.call_count == 2

    def test_send_html(self):
        """send_html uses HTML parse mode."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        publisher._client.post = Mock(return_value=mock_response)

        result = publisher.send_html("<b>Hello</b>")
        assert result.success is True
        call_data = publisher._client.post.call_args[1]["json"]
        assert call_data["parse_mode"] == "HTML"

    def test_inline_callback_and_update_methods(self):
        publisher = TelegramPublisher(bot_token="test", chat_id="-100")
        response = Mock()
        response.status_code = 200
        response.json.side_effect = [
            {"ok": True, "result": {"message_id": 1}},
            {"ok": True, "result": True},
            {"ok": True, "result": True},
            {"ok": True, "result": True},
            {"ok": True, "result": [{"update_id": 1}]},
        ]
        publisher._client.post = Mock(return_value=response)

        markup = {"inline_keyboard": [[{"text": "Like", "callback_data": "feedback:like:1"}]]}
        assert publisher.send_html("<b>Hi</b>", reply_markup=markup).success is True
        assert publisher.answer_callback_query("callback").success is True
        assert publisher.edit_message_reply_markup(-100, 2, markup).success is True
        assert publisher.delete_message(-100, 2).success is True
        updates = publisher.get_updates(offset=1, timeout=10, limit=5)

        assert updates.success is True
        assert updates.data == [{"update_id": 1}]
        calls = [call.kwargs["json"] for call in publisher._client.post.call_args_list]
        assert calls[0]["reply_markup"] == markup
        assert calls[1]["callback_query_id"] == "callback"
        assert calls[2]["chat_id"] == -100
        assert calls[3]["message_id"] == 2
        assert calls[4] == {"offset": 1, "timeout": 10, "limit": 5}

    def test_send_markdown(self):
        """send_markdown uses Markdown parse mode."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        publisher._client.post = Mock(return_value=mock_response)

        result = publisher.send_markdown("*Hello*")
        assert result.success is True
        call_data = publisher._client.post.call_args[1]["json"]
        assert call_data["parse_mode"] == "Markdown"

    def test_send_photo(self):
        """send_photo sends photo with caption."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        publisher._client.post = Mock(return_value=mock_response)

        result = publisher.send_photo("https://example.com/photo.jpg", "Caption")
        assert result.success is True
        call_data = publisher._client.post.call_args[1]["json"]
        assert call_data["photo"] == "https://example.com/photo.jpg"
        assert call_data["caption"] == "Caption"

    def test_send_document(self):
        """send_document sends document."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        publisher._client.post = Mock(return_value=mock_response)

        result = publisher.send_document("https://example.com/file.pdf")
        assert result.success is True
        call_data = publisher._client.post.call_args[1]["json"]
        assert call_data["document"] == "https://example.com/file.pdf"

    def test_message_truncation(self):
        """Messages longer than 4096 chars are truncated."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        publisher._client.post = Mock(return_value=mock_response)

        long_text = "x" * 5000
        publisher.send_message(long_text)
        call_data = publisher._client.post.call_args[1]["json"]
        assert len(call_data["text"]) == 4096

    def test_context_manager(self):
        """Publisher works as context manager."""
        with TelegramPublisher(bot_token="test", chat_id="-100") as publisher:
            assert publisher is not None

    def test_send_message_500_retry(self):
        """500 Internal Server Error triggers retry."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100", retry_delay=0.01)

        error_response = Mock()
        error_response.status_code = 500

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 999},
        }

        publisher._client.post = Mock(side_effect=[error_response, success_response])

        result = publisher.send_message("Hello")
        assert result.success is True
        assert publisher._client.post.call_count == 2

    def test_max_retries_exceeded(self):
        """Exceeding max retries returns error."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100", max_retries=2, retry_delay=0.01)

        error_response = Mock()
        error_response.status_code = 503
        publisher._client.post = Mock(return_value=error_response)

        result = publisher.send_message("Hello")
        assert result.success is False
        assert "Max retries exceeded" in result.error
        assert publisher._client.post.call_count == 3

    def test_api_error_response(self):
        """API error in response body returns error."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": False,
            "error_code": 400,
            "description": "Bad Request: message text is empty",
        }
        publisher._client.post = Mock(return_value=mock_response)

        result = publisher.send_message("")
        assert result.success is False
        assert result.error_code == 400
        assert "Bad Request" in result.error

    def test_get_me(self):
        """get_me returns bot info."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"id": 123456, "is_bot": True, "first_name": "TestBot"},
        }
        publisher._client.post = Mock(return_value=mock_response)

        result = publisher.get_me()
        assert result.success is True

    def test_send_photo_caption_truncation(self):
        """Photo captions longer than 1024 chars are truncated."""
        publisher = TelegramPublisher(bot_token="test", chat_id="-100")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        publisher._client.post = Mock(return_value=mock_response)

        long_caption = "x" * 2000
        publisher.send_photo("https://example.com/photo.jpg", long_caption)
        call_data = publisher._client.post.call_args[1]["json"]
        assert len(call_data["caption"]) == 1024
