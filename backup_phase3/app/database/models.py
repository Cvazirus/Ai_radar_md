import enum
from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, Integer, Boolean, DateTime, Float, ForeignKey, Enum, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database.base import Base

class ItemStatus(str, enum.Enum):
    collected = "collected"
    normalized = "normalized"
    duplicate = "duplicate"
    pending_analysis = "pending_analysis"
    analyzed = "analyzed"
    rejected = "rejected"
    pending_review = "pending_review"
    approved = "approved"
    published = "published"
    failed = "failed"

class PublicationStatus(str, enum.Enum):
    draft = "draft"
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    published = "published"
    failed = "failed"

class CategoryEnum(str, enum.Enum):
    news = "news"
    model_release = "model_release"
    local_model = "local_model"
    agent = "agent"
    coding_agent = "coding_agent"
    agent_harness = "agent_harness"
    skill = "skill"
    prompt = "prompt"
    mcp_server = "mcp_server"
    framework = "framework"
    research = "research"
    dataset = "dataset"
    benchmark = "benchmark"
    api = "api"
    tutorial = "tutorial"
    security = "security"
    funding = "funding"
    opinion = "opinion"
    other = "other"

class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trust_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )

    items: Mapped[List["Item"]] = relationship("Item", back_populates="source", cascade="all, delete-orphan")

class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    status: Mapped[ItemStatus] = mapped_column(
        Enum(ItemStatus), 
        default=ItemStatus.collected, 
        nullable=False
    )
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )

    source: Mapped["Source"] = relationship("Source", back_populates="items")
    analysis: Mapped[Optional["ItemAnalysis"]] = relationship("ItemAnalysis", back_populates="item", cascade="all, delete-orphan")
    publication: Mapped[Optional["Publication"]] = relationship("Publication", back_populates="item", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_items_status", "status"),
        Index("ix_items_published_at", "published_at"),
        Index("ix_items_source_id", "source_id"),
        Index("ix_items_canonical_url", "canonical_url"),
    )

class ItemAnalysis(Base):
    __tablename__ = "item_analysis"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    category: Mapped[CategoryEnum] = mapped_column(Enum(CategoryEnum), nullable=False)
    tags: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    entities: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    summary_ru: Mapped[str] = mapped_column(Text, nullable=False)
    what_is_new: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    why_important: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    practical_use: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_users: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    is_primary_source: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_promotional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    novelty_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    practicality_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    credibility_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    relevance_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    popularity_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    raw_llm_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )

    item: Mapped["Item"] = relationship("Item", back_populates="analysis")

class Publication(Base):
    __tablename__ = "publications"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    telegram_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PublicationStatus] = mapped_column(
        Enum(PublicationStatus), 
        default=PublicationStatus.draft, 
        nullable=False
    )
    moderation_chat_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    moderation_message_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    telegram_channel_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )

    item: Mapped["Item"] = relationship("Item", back_populates="publication")

class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    collector_name: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    items_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
