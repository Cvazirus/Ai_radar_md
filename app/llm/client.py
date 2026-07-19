import time
import json
from pathlib import Path
import httpx
import structlog
from typing import List, Dict, Optional
from app.config import settings
from app.llm.schemas import AnalysisRequest, AnalysisResult
from app.pipeline.json_extraction import extract_json_object, InvalidJSONError

_PROMPT_DIR = Path(__file__).parent / "prompts"

logger = structlog.get_logger()


class LLMError(Exception):
    pass

class LLMConfigurationError(LLMError):
    pass

class LLMTimeoutError(LLMError):
    pass

class LLMRateLimitError(LLMError):
    pass

class LLMAuthenticationError(LLMError):
    pass

class LLMInvalidResponseError(LLMError):
    pass

class LLMProviderError(LLMError):
    pass


REPAIR_PROMPT = """You previously returned an invalid JSON response. Here is your original response and the errors found:

SOURCE RAW CONTENT (for verifying evidence_text):
{raw_text}

ORIGINAL RESPONSE:
{original_response}

ERRORS:
{errors}

You MUST fix ONLY the format/structural issues. Do NOT add new facts or change values.
If an error is about invalid claim evidence, either replace evidence_text with an exact
verbatim substring copied from SOURCE RAW CONTENT above, or remove that claim from
source_claims. Do not guess evidence_text that is not a literal substring of SOURCE RAW CONTENT.
Return ONLY a single valid JSON object. No markdown, no explanation, just the JSON.

Required JSON schema:
{{
  "category": "one of: news, model_release, local_model, agent, coding_agent, agent_harness, skill, prompt, mcp_server, framework, research, dataset, benchmark, api, tutorial, security, funding, opinion, other",
  "tags": ["max 15 tags, each max 60 chars"],
  "entities": [{{"type": "company|product|model|repository|framework|skill|mcp_server|dataset|benchmark|research_paper|person|other", "name": "string"}}],
  "summary_ru": "min 10 chars in Russian",
  "what_is_new": "string or null",
  "why_important": "string or null",
  "practical_use": "string or null",
  "target_users": ["max 10"],
  "is_primary_source": true/false,
  "is_promotional": true/false,
  "is_actionable": true/false,
  "is_newsworthy": true/false,
  "source_claims": [{{"claim": "string", "evidence_text": "short excerpt from source max 500 chars", "evidence_type": "direct_quote|explicit_statement|metadata|inference", "confidence": 0.0-1.0}}],
  "uncertainties": [{{"field": "string", "reason": "string", "severity": "low|medium|high"}}],
  "novelty_score": 0-10,
  "practicality_score": 0-10,
  "credibility_score": 0-10,
  "relevance_score": 0-10,
  "confidence": 0.0-1.0
}}"""


class LLMClient:
    def __init__(self):
        if settings.LLM_ANALYSIS_ENABLED:
            if not settings.LLM_BASE_URL:
                raise LLMConfigurationError("LLM_BASE_URL is not set.")
            if not settings.LLM_API_KEY:
                raise LLMConfigurationError("LLM_API_KEY is not set.")
            if not settings.LLM_MODEL:
                raise LLMConfigurationError("LLM_MODEL is not set.")

        self.base_url = settings.LLM_BASE_URL
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self.timeout = httpx.Timeout(
            timeout=settings.LLM_TIMEOUT_SECONDS,
            connect=settings.LLM_CONNECT_TIMEOUT_SECONDS
        )
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key not in ("", "test", "your-api-key-here"):
            headers["Authorization"] = f"Bearer {self.api_key}"
        self.http_client = httpx.Client(
            headers=headers,
            timeout=self.timeout
        )
        self.last_raw_response: Optional[str] = None

    def raw_completion(self, messages: List[Dict[str, str]]) -> str:
        if not settings.LLM_ANALYSIS_ENABLED:
            raise LLMConfigurationError("LLM analysis is disabled in configuration.")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_OUTPUT_TOKENS,
            "stream": False,
        }

        for attempt in range(settings.LLM_MAX_RETRIES + 1):
            try:
                start_time = time.time()
                response = self.http_client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload
                )
                duration = time.time() - start_time
                logger.info("llm_request_completed", duration_seconds=duration, attempt=attempt)

                if response.status_code == 200:
                    try:
                        content = response.json()["choices"][0]["message"]["content"]
                        self.last_raw_response = content
                        return content
                    except (KeyError, IndexError, json.JSONDecodeError) as e:
                        raise LLMInvalidResponseError(f"Invalid response structure from provider: {e}")

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    sleep_time = int(retry_after) if retry_after and retry_after.isdigit() else (2 ** attempt)
                    logger.warn("llm_rate_limited", attempt=attempt, sleep_seconds=sleep_time)
                    if attempt < settings.LLM_MAX_RETRIES:
                        time.sleep(sleep_time)
                        continue
                    raise LLMRateLimitError("Rate limit exceeded (HTTP 429). Retry attempts failed.")

                if response.status_code in [401, 403]:
                    raise LLMAuthenticationError(f"Authentication failed (HTTP {response.status_code}). Check API key.")

                if response.status_code in [500, 502, 503, 504]:
                    logger.warn("llm_temporary_server_error", status_code=response.status_code, attempt=attempt)
                    if attempt < settings.LLM_MAX_RETRIES:
                        time.sleep(2 ** attempt)
                        continue
                    raise LLMProviderError(f"Temporary server error (HTTP {response.status_code}). Retry attempts failed.")

                raise LLMProviderError(f"API request failed with status code {response.status_code}: {response.text}")

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warn("llm_network_timeout_error", error=str(exc), attempt=attempt)
                if attempt < settings.LLM_MAX_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMTimeoutError(f"Request to LLM provider timed out: {exc}")
            except httpx.RequestError as exc:
                logger.warn("llm_network_request_error", error=str(exc), attempt=attempt)
                if attempt < settings.LLM_MAX_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMProviderError(f"Network error during LLM request: {exc}")

        raise LLMProviderError("All retry attempts failed due to unknown errors.")

    def _build_user_prompt(self, request: AnalysisRequest) -> str:
        return (
            f"Please analyze the following article.\n"
            f"Title: {request.title}\n"
            f"Source Name: {request.source_name}\n"
            f"Source URL: {request.source_url}\n"
            f"Raw Content:\n{request.raw_text}\n"
        )

    def _load_system_prompt(self) -> str:
        prompt_path = _PROMPT_DIR / "analyzer.txt"
        try:
            return prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise LLMConfigurationError(f"System prompt not found: {prompt_path}")

    def analyze_item(self, request: AnalysisRequest) -> AnalysisResult:
        system_prompt = self._load_system_prompt()
        user_prompt = self._build_user_prompt(request)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        logger.info("llm_analysis_started", item_id=request.item_id, source_name=request.source_name)
        raw_response = self.raw_completion(messages)
        self.last_raw_response = raw_response

        json_data = extract_json_object(raw_response)
        return AnalysisResult.model_validate(json_data)

    def repair_item(self, request: AnalysisRequest, original_response: str, errors: List[str]) -> AnalysisResult:
        system_prompt = self._load_system_prompt()
        repair_user = REPAIR_PROMPT.format(
            raw_text=request.raw_text,
            original_response=original_response[:2000],
            errors="\n".join(f"- {e}" for e in errors),
            errors_list="\n".join(f"- {e}" for e in errors),
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": repair_user}
        ]

        logger.info("llm_repair_started", item_id=request.item_id)
        raw_response = self.raw_completion(messages)
        self.last_raw_response = raw_response

        json_data = extract_json_object(raw_response)
        return AnalysisResult.model_validate(json_data)
