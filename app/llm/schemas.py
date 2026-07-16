from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.config import settings
from app.database.models import CategoryEnum, ModerationDecision, ModerationPriority


class AnalysisRequest(BaseModel):
    item_id: int
    source_name: str
    source_type: str
    source_url: str
    title: str
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    language: Optional[str] = None
    raw_text: str
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def enforce_text_limits(cls, data):
        if not isinstance(data, dict):
            return data

        raw_text = data.get("raw_text")
        title = data.get("title")
        url = data.get("source_url")

        if not title:
            raise ValueError("title cannot be empty")
        if not url:
            raise ValueError("source_url cannot be empty")
        if not raw_text:
            raise ValueError("raw_text cannot be empty")

        max_chars = settings.LLM_MAX_INPUT_CHARS
        if len(raw_text) > max_chars:
            truncated_text = raw_text[:max_chars]
            data["raw_text"] = truncated_text

            meta = data.setdefault("metadata", {})
            meta["truncated"] = True
            meta["original_length"] = len(raw_text)
            meta["truncated_length"] = max_chars
        return data


class EntityResult(BaseModel):
    type: Literal[
        "company", "product", "model", "repository", "framework",
        "skill", "mcp_server", "dataset", "benchmark",
        "research_paper", "person", "other"
    ]
    name: str
    canonical_name: Optional[str] = None
    url: Optional[str] = None
    version: Optional[str] = None


class SourceClaim(BaseModel):
    claim: str
    evidence_text: str
    evidence_type: Literal[
        "direct_quote", "explicit_statement", "metadata", "inference"
    ]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("evidence_text")
    @classmethod
    def truncate_evidence(cls, v):
        if len(v) > 500:
            return v[:500]
        return v


class Uncertainty(BaseModel):
    field: str
    reason: str
    severity: Literal["low", "medium", "high"]


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: CategoryEnum
    tags: List[str] = Field(default_factory=list)
    entities: List[EntityResult] = Field(default_factory=list)
    summary_ru: str = Field(min_length=10)
    what_is_new: Optional[str] = None
    why_important: Optional[str] = None
    practical_use: Optional[str] = None
    target_users: List[str] = Field(default_factory=list)
    is_primary_source: bool
    is_promotional: bool
    is_actionable: bool
    is_newsworthy: bool
    source_claims: List[SourceClaim] = Field(default_factory=list)
    uncertainties: List[Uncertainty] = Field(default_factory=list)
    novelty_score: int = Field(ge=0, le=10)
    practicality_score: int = Field(ge=0, le=10)
    credibility_score: int = Field(ge=0, le=10)
    relevance_score: int = Field(ge=0, le=10)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, v):
        if not isinstance(v, list):
            return v
        cleaned = []
        seen = set()
        for tag in v:
            if not isinstance(tag, str):
                continue
            tag = tag.strip()
            if not tag or len(tag) > 60:
                continue
            if tag in seen:
                continue
            seen.add(tag)
            cleaned.append(tag)
        return cleaned[:15]

    @field_validator("target_users", mode="before")
    @classmethod
    def validate_target_users(cls, v):
        if not isinstance(v, list):
            return v
        cleaned = []
        seen = set()
        for u in v:
            if not isinstance(u, str):
                continue
            u = u.strip()
            if not u or u in seen:
                continue
            seen.add(u)
            cleaned.append(u)
        return cleaned[:10]

class ModerationDecisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int
    analysis_id: int
    decision: ModerationDecision
    priority: ModerationPriority
    decision_score: float = Field(ge=0.0, le=10.0)
    blocking_reasons: List[str] = Field(default_factory=list)
    decision_reasons: dict = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    rules_version: str
    eligible_for_queue: bool
