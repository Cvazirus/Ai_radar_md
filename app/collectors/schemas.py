from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, field_validator

class CollectedItem(BaseModel):
    source_name: str
    source_type: str
    external_id: Optional[str] = None
    url: str
    title: str
    author: Optional[str] = None
    text: Optional[str] = None
    published_at: Optional[datetime] = None
    metadata: dict = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def url_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")
        return v.strip()

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip()

    @field_validator("source_name")
    @classmethod
    def source_name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Source name cannot be empty")
        return v.strip()

    @field_validator("published_at")
    @classmethod
    def make_tz_aware(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
