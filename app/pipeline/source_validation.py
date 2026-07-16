from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


# Trusted primary source domains
TRUSTED_PRIMARY_DOMAINS = {
    "openai.com", "blog.openai.com", "platform.openai.com",
    "anthropic.com", "claude.ai",
    "google.com", "deepmind.google", "ai.google",
    "meta.ai", "ai.meta.com",
    "microsoft.com", "github.com", "github.blog",
    "huggingface.co",
    "arxiv.org",
    "deepseek.com",
    "mistral.ai",
    "cohere.com",
    "stability.ai",
    "nvidia.com",
    "apple.com",
    "amazon.com", "aws.amazon.com",
    "ibm.com",
    "open-source", "opensource",
}

TRUSTED_PRIMARY_HOSTS = {
    "github.com", "huggingface.co", "arxiv.org",
    "openai.com", "anthropic.com", "google.com",
    "deepmind.google", "ai.google", "meta.ai",
    "ai.meta.com", "microsoft.com", "github.blog",
    "deepseek.com", "mistral.ai", "cohere.com",
    "stability.ai", "nvidia.com",
}


@dataclass
class PrimarySourceResult:
    llm_value: bool
    rule_value: bool
    final_value: bool
    conflict: bool
    reason: str


def _extract_host(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        # Strip www.
        if host.startswith("www."):
            host = host[4:]
        return host.lower()
    except Exception:
        return ""


def _is_primary_by_domain(host: str) -> tuple:
    if not host:
        return False, "No domain"

    if host in TRUSTED_PRIMARY_HOSTS:
        return True, f"Trusted primary domain: {host}"

    for trusted in TRUSTED_PRIMARY_HOSTS:
        if host.endswith("." + trusted):
            return True, f"Subdomain of trusted primary: {trusted}"

    return False, f"Secondary/news domain: {host}"


def _is_primary_by_url(url: str) -> tuple:
    if not url:
        return False, "No URL"

    host = _extract_host(url)

    # arXiv papers
    if host == "arxiv.org":
        if "/abs/" in url or "/pdf/" in url:
            return True, "arXiv paper"

    # GitHub repos
    if host == "github.com":
        parts = url.rstrip("/").split("/")
        if len(parts) >= 5 and parts[3] not in ("", "orgs", "topics", "trending", "explore"):
            return True, "GitHub repository"

    # HuggingFace
    if host == "huggingface.co":
        parts = url.rstrip("/").split("/")
        if len(parts) >= 4 and parts[3] not in ("", "models", "datasets", "spaces", "papers"):
            return True, "HuggingFace model/dataset"

    return _is_primary_by_domain(host)


def validate_primary_source(url: str = "", llm_is_primary: bool = False) -> PrimarySourceResult:
    rule_value, reason = _is_primary_by_url(url)
    conflict = (llm_is_primary != rule_value) and rule_value is not None
    final_value = rule_value

    return PrimarySourceResult(
        llm_value=llm_is_primary,
        rule_value=rule_value,
        final_value=final_value,
        conflict=conflict,
        reason=reason
    )
