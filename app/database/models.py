import enum
from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, Integer, Boolean, DateTime, Float, ForeignKey, Enum, Text, Index, Numeric, CheckConstraint, UniqueConstraint
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

class RelationType(str, enum.Enum):
    exact_external_id = "exact_external_id"
    exact_canonical_url = "exact_canonical_url"
    exact_content_hash = "exact_content_hash"
    same_source_title = "same_source_title"
    cross_source_story = "cross_source_story"
    manual = "manual"

class AnalysisStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    invalid_response = "invalid_response"
    skipped = "skipped"

class ReviewStatus(str, enum.Enum):
    auto_confirmed = "auto_confirmed"
    pending_review = "pending_review"
    confirmed = "confirmed"
    rejected = "rejected"

class ModerationQueueStatus(str, enum.Enum):
    pending = "pending"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    needs_revision = "needs_revision"
    expired = "expired"
    cancelled = "cancelled"

class ModerationPriority(str, enum.Enum):
    low = "low"
    normal = "normal"
    high = "high"
    critical = "critical"

class ModerationDecision(str, enum.Enum):
    archive = "archive"
    digest_candidate = "digest_candidate"
    manual_review = "manual_review"
    priority_review = "priority_review"
    blocked = "blocked"

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
    analyses: Mapped[List["ItemAnalysis"]] = relationship("ItemAnalysis", back_populates="item", cascade="all, delete-orphan")
    publication: Mapped[Optional["Publication"]] = relationship("Publication", back_populates="item", cascade="all, delete-orphan")
    moderation_queues: Mapped[List["ModerationQueue"]] = relationship("ModerationQueue", back_populates="item", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_items_status", "status"),
        Index("ix_items_published_at", "published_at"),
        Index("ix_items_source_id", "source_id"),
        Index("ix_items_canonical_url", "canonical_url"),
    )

class ItemAnalysis(Base):
    __tablename__ = "item_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[AnalysisStatus] = mapped_column(Enum(AnalysisStatus), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[Optional[CategoryEnum]] = mapped_column(Enum(CategoryEnum), nullable=True)
    tags: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    entities: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    summary_ru: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    what_is_new: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    why_important: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    practical_use: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_users: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    is_primary_source: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_promotional: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_actionable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_newsworthy: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    source_claims: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    uncertainties: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    novelty_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    practicality_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    credibility_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    relevance_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    base_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    penalties: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    total_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    score_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    raw_llm_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_chars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_chars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    force_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    force_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default='false')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    item: Mapped["Item"] = relationship("Item", back_populates="analyses")
    moderation_queue: Mapped[Optional["ModerationQueue"]] = relationship("ModerationQueue", back_populates="analysis", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_item_analysis_item_id", "item_id"),
        Index("ix_item_analysis_status", "status"),
        Index("ix_item_analysis_input_hash", "input_hash"),
        Index("ix_item_analysis_created_at", "created_at"),
        Index("ix_item_analysis_model_name", "model_name"),
    )

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

class DuplicateRelation(Base):
    __tablename__ = "duplicate_relations"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    duplicate_of_item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[RelationType] = mapped_column(Enum(RelationType), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), 
        default=ReviewStatus.pending_review, 
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint("item_id", "duplicate_of_item_id", "relation_type", name="uq_item_duplicate_relation"),
        CheckConstraint("item_id != duplicate_of_item_id", name="chk_no_self_duplicate"),
        Index("ix_duplicate_relations_item_id", "item_id"),
        Index("ix_duplicate_relations_duplicate_of_item_id", "duplicate_of_item_id"),
    )

class ModerationQueue(Base):
    __tablename__ = "moderation_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("item_analysis.id", ondelete="CASCADE"), nullable=False, unique=True)
    queue_status: Mapped[ModerationQueueStatus] = mapped_column(Enum(ModerationQueueStatus), nullable=False)
    priority: Mapped[ModerationPriority] = mapped_column(Enum(ModerationPriority), nullable=False)
    decision: Mapped[ModerationDecision] = mapped_column(Enum(ModerationDecision), nullable=False)
    decision_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    decision_reasons: Mapped[dict] = mapped_column(JSONB, nullable=False)
    blocking_reasons: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    assigned_to: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    review_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )

    item: Mapped["Item"] = relationship("Item", back_populates="moderation_queues")
    analysis: Mapped["ItemAnalysis"] = relationship("ItemAnalysis", back_populates="moderation_queue")

    __table_args__ = (
        Index("ix_moderation_queue_queue_status", "queue_status"),
        Index("ix_moderation_queue_priority", "priority"),
        Index("ix_moderation_queue_decision", "decision"),
        Index("ix_moderation_queue_queued_at", "queued_at"),
        Index("ix_moderation_queue_item_id", "item_id"),
        Index("ix_moderation_queue_analysis_id", "analysis_id"),
    )

class ModerationDecisionLog(Base):
    __tablename__ = "moderation_decision_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("moderation_queue.id", ondelete="CASCADE"), nullable=False)
    previous_status: Mapped[Optional[ModerationQueueStatus]] = mapped_column(Enum(ModerationQueueStatus), nullable=True)
    new_status: Mapped[ModerationQueueStatus] = mapped_column(Enum(ModerationQueueStatus), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    queue: Mapped["ModerationQueue"] = relationship("ModerationQueue")


class PipelineRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[PipelineRunStatus] = mapped_column(Enum(PipelineRunStatus), default=PipelineRunStatus.pending, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_step: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    items_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    summary_json: Mapped[Optional[dict]] = mapped_column("summary", JSONB, nullable=True)

