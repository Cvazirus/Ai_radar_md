import httpx

urls = {
    "OpenAI News": "https://openai.com/news/rss.xml",
    "OpenAI Blog (alternate)": "https://openai.com/blog/rss.xml",
    "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
    "Habr AI Hub": "https://habr.com/ru/rss/hub/artificial_intelligence/all/",
    "Hacker News AI": "https://hnrss.org/newest?q=AI",
    "GitHub Blog": "https://github.blog/feed/",
    "Google Research Blog": "https://research.google/blog/rss/",
    "AWS Machine Learning": "https://aws.amazon.com/blogs/machine-learning/feed/"
}

headers = {"User-Agent": "AI-Radar/0.1 (+collector)"}

for name, url in urls.items():
    try:
        resp = httpx.get(url, headers=headers, timeout=10.0, follow_redirects=True)
        print(f"{name}: STATUS={resp.status_code}, SIZE={len(resp.content)} bytes, IS_XML={'xml' in resp.headers.get('content-type', '') or b'<?xml' in resp.content[:100]}")
    except Exception as e:
        print(f"{name}: FAILED - {str(e)}")
