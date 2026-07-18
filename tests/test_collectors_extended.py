from unittest.mock import MagicMock, patch

from app.collectors.github import GithubCollector
from app.collectors.arxiv import ArxivCollector
from app.collectors.huggingface import HuggingFaceCollector
from app.collectors.web import WebCollector


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    resp.text = text
    return resp


# --- GithubCollector ---

@patch("httpx.Client")
def test_github_collect(mock_client):
    payload = {
        "items": [
            {
                "id": 123,
                "full_name": "acme/agent-framework",
                "html_url": "https://github.com/acme/agent-framework",
                "description": "An AI agent framework",
                "stargazers_count": 500,
                "forks_count": 10,
                "language": "Python",
                "topics": ["ai", "agents"],
                "pushed_at": "2026-07-10T12:00:00Z",
                "owner": {"login": "acme"},
            }
        ]
    }
    mock_client.return_value.__enter__.return_value.get.return_value = _mock_response(json_data=payload)

    collector = GithubCollector("GitHub Test", query="topic:llm")
    items = collector.collect()

    assert len(items) == 1
    item = items[0]
    assert item.title == "acme/agent-framework"
    assert item.url == "https://github.com/acme/agent-framework"
    assert item.author == "acme"
    assert "Topics: ai, agents" in item.text
    assert item.published_at is not None
    assert item.metadata["stars"] == 500


@patch("httpx.Client")
def test_github_skips_incomplete_items(mock_client):
    payload = {"items": [{"id": 1, "full_name": None, "html_url": None}]}
    mock_client.return_value.__enter__.return_value.get.return_value = _mock_response(json_data=payload)

    collector = GithubCollector("GitHub Test", query="topic:llm")
    items = collector.collect()
    assert items == []


# --- ArxivCollector ---

ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <title>A Great Paper About LLMs</title>
    <summary>This paper presents a great advance in LLMs.</summary>
    <published>2026-07-10T12:00:00Z</published>
    <link href="http://arxiv.org/abs/2401.12345v1" rel="alternate"/>
    <author><name>Jane Doe</name></author>
    <category term="cs.AI"/>
  </entry>
</feed>"""


@patch("httpx.Client")
def test_arxiv_collect(mock_client):
    mock_client.return_value.__enter__.return_value.get.return_value = _mock_response(text=ARXIV_ATOM)

    collector = ArxivCollector("arXiv Test", query="cat:cs.AI")
    items = collector.collect()

    assert len(items) == 1
    item = items[0]
    assert item.title == "A Great Paper About LLMs"
    assert item.url == "http://arxiv.org/abs/2401.12345v1"
    assert item.author == "Jane Doe"
    assert item.text == "This paper presents a great advance in LLMs."
    assert item.published_at is not None
    assert item.metadata["categories"] == ["cs.AI"]


# --- HuggingFaceCollector ---

@patch("httpx.Client")
def test_huggingface_collect(mock_client):
    payload = [
        {
            "id": "acme/cool-model",
            "pipeline_tag": "text-generation",
            "tags": ["pytorch", "llm"],
            "downloads": 1000,
            "likes": 50,
            "createdAt": "2026-07-01T00:00:00.000Z",
        }
    ]
    mock_client.return_value.__enter__.return_value.get.return_value = _mock_response(json_data=payload)

    collector = HuggingFaceCollector("HF Test")
    items = collector.collect()

    assert len(items) == 1
    item = items[0]
    assert item.title == "acme/cool-model"
    assert item.url == "https://huggingface.co/acme/cool-model"
    assert item.author == "acme"
    assert "Pipeline: text-generation" in item.text
    assert item.metadata["likes"] == 50


# --- WebCollector ---

LISTING_HTML = """
<html><body>
<nav><a href="/about">About</a></nav>
<div class="posts">
  <a href="/blog/post-1">Read post 1</a>
</div>
</body></html>
"""

ARTICLE_HTML = """
<html><head>
<meta property="og:title" content="My Article Title">
<meta name="author" content="Jane Doe">
<meta property="article:published_time" content="2026-07-10">
</head><body>
<article>
<h1>My Article Title</h1>
<p>This is the first paragraph of the article with enough content to be extracted properly by trafilatura, since it needs a reasonable amount of text to consider this the main content region of the page.</p>
<p>This is a second paragraph continuing the article with more substantive discussion of the topic at hand, ensuring extraction succeeds reliably in this test.</p>
</article>
</body></html>
"""


@patch("httpx.Client")
def test_web_collect(mock_client):
    mock_client.return_value.__enter__.return_value.get.side_effect = [
        _mock_response(text=LISTING_HTML),
        _mock_response(text=ARTICLE_HTML),
    ]

    collector = WebCollector(
        "Web Test",
        listing_url="https://example.com/blog",
        link_selector=".posts a",
    )
    items = collector.collect()

    assert len(items) == 1
    item = items[0]
    assert item.title == "My Article Title"
    assert item.url == "https://example.com/blog/post-1"
    assert item.author == "Jane Doe"
    assert "first paragraph" in item.text
    assert item.published_at is not None
