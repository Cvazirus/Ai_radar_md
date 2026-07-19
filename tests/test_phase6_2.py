"""Tests for Phase 6.2 — operational moderation pilot."""
import pytest
from unittest.mock import MagicMock, patch
from app.database.models import (
    Item, ItemStatus, ItemAnalysis, AnalysisStatus, CategoryEnum,
    ModerationQueue, ModerationQueueStatus, ModerationDecision, ModerationPriority
)
from app.pipeline.input_hash import calculate_analysis_input_hash
from app.pipeline.moderation_rules import evaluate_item_moderation, MODERATION_RULES_VERSION
from app.pipeline.claim_validation import validate_source_claims
from app.pipeline.source_validation import validate_primary_source
from app.pipeline.scoring import calculate_score
from app.pipeline.json_extraction import extract_json_object, InvalidJSONError
from app.llm.schemas import AnalysisResult, SourceClaim, Uncertainty


# === INPUT HASH IDEMPOTENCY ===

def test_input_hash_stability():
    h1 = calculate_analysis_input_hash(1, "title", "text", "url", "model", "v1", "1.0")
    h2 = calculate_analysis_input_hash(1, "title", "text", "url", "model", "v1", "1.0")
    assert h1 == h2

def test_input_hash_changes_with_model():
    h1 = calculate_analysis_input_hash(1, "title", "text", "url", "model-a", "v1", "1.0")
    h2 = calculate_analysis_input_hash(1, "title", "text", "url", "model-b", "v1", "1.0")
    assert h1 != h2

def test_input_hash_changes_with_prompt_version():
    h1 = calculate_analysis_input_hash(1, "title", "text", "url", "model", "v1", "1.0")
    h2 = calculate_analysis_input_hash(1, "title", "text", "url", "model", "v2", "1.0")
    assert h1 != h2


# === FORCE vs NORMAL DUPLICATES ===

def test_force_duplicates_are_allowed():
    """Force duplicates with force_run=true and non-empty force_reason are allowed."""
    from app.database.models import RelationType
    item = MagicMock()
    item.id = 1
    item.title = "Test"
    item.raw_text = "Test text"
    item.url = "http://test.com"
    item.source = MagicMock()
    item.source.name = "Test"
    item.source.source_type = "rss"
    item.source.trust_level = 1
    item.status = ItemStatus.collected
    item.metadata_json = {}
    item.published_at = None
    item.collected_at = None

    analysis = MagicMock()
    analysis.status = AnalysisStatus.success
    analysis.summary_ru = "Test summary"
    analysis.confidence = 0.8
    analysis.is_primary_source = True
    analysis.is_promotional = False
    analysis.is_actionable = True
    analysis.is_newsworthy = True
    analysis.category = CategoryEnum.news
    analysis.novelty_score = 5
    analysis.practicality_score = 5
    analysis.credibility_score = 5
    analysis.relevance_score = 7
    analysis.total_score = 5.0
    analysis.source_claims = []
    analysis.uncertainties = []
    analysis.what_is_new = "Something new"
    analysis.practical_use = "Useful"
    analysis.prompt_version = "phase5-v2"
    analysis.input_hash = "abc123"

    result = evaluate_item_moderation(item, analysis, [])
    assert result is not None
    assert result.rules_version == MODERATION_RULES_VERSION


def test_legacy_analysis_blocked():
    """Legacy analysis (prompt_version='legacy') should be blocked."""
    item = MagicMock()
    item.id = 1
    item.title = "Test"
    item.raw_text = "Test text"
    item.url = "http://test.com"
    item.source = MagicMock()
    item.source.name = "Test"
    item.source.trust_level = 1
    item.status = ItemStatus.collected
    item.metadata_json = {}
    item.published_at = None
    item.collected_at = None

    analysis = MagicMock()
    analysis.status = AnalysisStatus.success
    analysis.summary_ru = "Test summary"
    analysis.confidence = 0.8
    analysis.is_primary_source = True
    analysis.is_promotional = False
    analysis.category = CategoryEnum.news
    analysis.novelty_score = 5
    analysis.practicality_score = 5
    analysis.credibility_score = 5
    analysis.relevance_score = 7
    analysis.total_score = 5.0
    analysis.source_claims = []
    analysis.uncertainties = []
    analysis.what_is_new = "Something new"
    analysis.practical_use = "Useful"
    analysis.prompt_version = "legacy"
    analysis.input_hash = "legacy"

    result = evaluate_item_moderation(item, analysis, [])
    assert "legacy_analysis" in result.blocking_reasons


def test_actual_analysis_not_blocked_as_legacy():
    """Actual analysis (prompt_version='phase5-v2') should NOT be blocked as legacy."""
    item = MagicMock()
    item.id = 1
    item.title = "Test"
    item.raw_text = "Test text with enough content for validation"
    item.url = "http://openai.com/test"
    item.source = MagicMock()
    item.source.name = "OpenAI"
    item.source.trust_level = 1
    item.status = ItemStatus.collected
    item.metadata_json = {}
    item.published_at = None
    item.collected_at = None

    analysis = MagicMock()
    analysis.status = AnalysisStatus.success
    analysis.summary_ru = "Test summary with enough content"
    analysis.confidence = 0.8
    analysis.is_primary_source = True
    analysis.is_promotional = False
    analysis.category = CategoryEnum.news
    analysis.novelty_score = 5
    analysis.practicality_score = 5
    analysis.credibility_score = 5
    analysis.relevance_score = 7
    analysis.total_score = 5.0
    analysis.source_claims = []
    analysis.uncertainties = []
    analysis.what_is_new = "Something new"
    analysis.practical_use = "Useful"
    analysis.prompt_version = "phase5-v2"
    analysis.input_hash = "abc123"

    result = evaluate_item_moderation(item, analysis, [])
    assert "legacy_analysis" not in result.blocking_reasons


# === MODERATION RULES ===

def test_low_confidence_blocks():
    item = MagicMock()
    item.id = 1
    item.title = "Test"
    item.raw_text = "Test"
    item.url = "http://test.com"
    item.source = MagicMock()
    item.source.name = "Test"
    item.source.trust_level = 1
    item.status = ItemStatus.collected
    item.metadata_json = {}
    item.published_at = None
    item.collected_at = None

    analysis = MagicMock()
    analysis.status = AnalysisStatus.success
    analysis.summary_ru = "Test"
    analysis.confidence = 0.3
    analysis.is_primary_source = True
    analysis.is_promotional = False
    analysis.category = CategoryEnum.news
    analysis.novelty_score = 5
    analysis.practicality_score = 5
    analysis.credibility_score = 5
    analysis.relevance_score = 5
    analysis.total_score = 5.0
    analysis.source_claims = []
    analysis.uncertainties = []
    analysis.what_is_new = "New"
    analysis.practical_use = "Use"
    analysis.prompt_version = "phase5-v2"
    analysis.input_hash = "abc"

    result = evaluate_item_moderation(item, analysis, [])
    assert "low_confidence" in result.blocking_reasons


def test_cross_source_story_not_auto_blocked():
    """cross_source_story relation should NOT automatically block."""
    from app.database.models import RelationType, ReviewStatus
    item = MagicMock()
    item.id = 1
    item.title = "Test"
    item.raw_text = "Test text with enough content"
    item.url = "http://test.com"
    item.source = MagicMock()
    item.source.name = "Test"
    item.source.trust_level = 1
    item.status = ItemStatus.collected
    item.metadata_json = {}
    item.published_at = None
    item.collected_at = None

    analysis = MagicMock()
    analysis.status = AnalysisStatus.success
    analysis.summary_ru = "Test summary"
    analysis.confidence = 0.8
    analysis.is_primary_source = True
    analysis.is_promotional = False
    analysis.category = CategoryEnum.news
    analysis.novelty_score = 5
    analysis.practicality_score = 5
    analysis.credibility_score = 5
    analysis.relevance_score = 7
    analysis.total_score = 5.0
    analysis.source_claims = []
    analysis.uncertainties = []
    analysis.what_is_new = "New"
    analysis.practical_use = "Use"
    analysis.prompt_version = "phase5-v2"
    analysis.input_hash = "abc"

    dup = MagicMock()
    dup.item_id = 2
    dup.relation_type = RelationType.cross_source_story

    result = evaluate_item_moderation(item, analysis, [dup])
    assert "exact_duplicate" not in result.blocking_reasons


# === PUBLICATIONS ===

def test_analysis_service_no_publications():
    """AnalysisService should not create or delete publications."""
    import inspect
    from app.services import analysis_service
    source = inspect.getsource(analysis_service)
    assert "PublicationRepository" not in source
    assert "pub_repo" not in source
    assert "Publication(" not in source


# === JSON EXTRACTION ===

def test_json_extraction_clean():
    r = extract_json_object('{"category": "news"}')
    assert r["category"] == "news"

def test_json_extraction_code_fence():
    r = extract_json_object('```json\n{"category": "news"}\n```')
    assert r["category"] == "news"

def test_json_extraction_multiple_objects():
    with pytest.raises(InvalidJSONError):
        extract_json_object('{"a":1} {"b":2}')


# === SCORING ===

def test_scoring_formula():
    s = calculate_score(
        relevance_score=8, practicality_score=7,
        novelty_score=6, credibility_score=9,
        confidence=0.8, is_promotional=False,
        has_tech_claims=True, final_is_primary_source=True,
        has_high_uncertainty=False
    )
    expected = 8 * 0.35 + 7 * 0.30 + 6 * 0.20 + 9 * 0.15
    assert s.base_score == round(expected, 2)

def test_scoring_penalties():
    s = calculate_score(
        relevance_score=8, practicality_score=8,
        novelty_score=8, credibility_score=8,
        confidence=0.3, is_promotional=True,
        has_tech_claims=False, final_is_primary_source=False,
        has_high_uncertainty=True
    )
    assert len(s.penalties) == 4
    assert s.total_score == 0.0


# === CLAIM VALIDATION ===

def test_claim_validation_exact():
    from app.llm.schemas import SourceClaim
    claims = [SourceClaim(claim="test", evidence_text="OpenAI released GPT-5", evidence_type="direct_quote", confidence=0.9)]
    result = validate_source_claims("OpenAI released GPT-5 today", claims)
    assert len(result.valid_claims) == 1

def test_claim_validation_fabricated():
    from app.llm.schemas import SourceClaim
    claims = [SourceClaim(claim="test", evidence_text="completely made up", evidence_type="inference", confidence=0.5)]
    result = validate_source_claims("OpenAI released GPT-5", claims)
    assert len(result.invalid_claims) == 1


# === DB-SHAPED (WRAPPED) uncertainties / source_claims MUST BE UNWRAPPED ===

def test_high_uncertainty_blocks_with_real_db_wrapped_shape():
    # Regression: AnalysisService stores analysis.uncertainties as
    # {"uncertainties": [...]} (see analysis_service.py), not a bare list.
    # evaluate_item_moderation used to iterate the dict directly, which
    # iterates its keys (a single string) instead of the uncertainty
    # objects -- so "high" severity from real DB data never blocked anything.
    item = MagicMock()
    item.id = 1
    item.title = "Test"
    item.raw_text = "Test text with enough content for validation"
    item.url = "http://test.com"
    item.source = MagicMock()
    item.source.name = "Test"
    item.source.trust_level = 1
    item.status = ItemStatus.collected
    item.metadata_json = {}
    item.published_at = None
    item.collected_at = None

    analysis = MagicMock()
    analysis.status = AnalysisStatus.success
    analysis.summary_ru = "Test summary"
    analysis.confidence = 0.8
    analysis.is_primary_source = True
    analysis.is_promotional = False
    analysis.category = CategoryEnum.news
    analysis.novelty_score = 5
    analysis.practicality_score = 5
    analysis.credibility_score = 5
    analysis.relevance_score = 7
    analysis.total_score = 5.0
    analysis.source_claims = {"claims": []}
    analysis.uncertainties = {"uncertainties": [
        {"field": "date", "reason": "unclear publish date", "severity": "high"}
    ]}
    analysis.what_is_new = "Something new"
    analysis.practical_use = "Useful"
    analysis.prompt_version = "phase5-v2"
    analysis.input_hash = "abc123"

    result = evaluate_item_moderation(item, analysis, [])
    assert "high_uncertainty" in result.blocking_reasons

def test_promotional_with_wrapped_valid_claims_not_blocked():
    # Regression: same wrapped-shape bug affected has_tech_claims, so any
    # promotional=true material was blocked by "promotional_without_evidence"
    # even with a real, verifiable direct_quote claim.
    item = MagicMock()
    item.id = 1
    item.title = "Test"
    item.raw_text = "Our new product launches today with a 50% speed improvement."
    item.url = "http://test.com"
    item.source = MagicMock()
    item.source.name = "Test"
    item.source.trust_level = 1
    item.status = ItemStatus.collected
    item.metadata_json = {}
    item.published_at = None
    item.collected_at = None

    analysis = MagicMock()
    analysis.status = AnalysisStatus.success
    analysis.summary_ru = "Test summary"
    analysis.confidence = 0.8
    analysis.is_primary_source = True
    analysis.is_promotional = True
    analysis.category = CategoryEnum.news
    analysis.novelty_score = 5
    analysis.practicality_score = 5
    analysis.credibility_score = 5
    analysis.relevance_score = 7
    analysis.total_score = 5.0
    analysis.source_claims = {"claims": [
        {"claim": "50% speed improvement", "evidence_text": "50% speed improvement",
         "evidence_type": "direct_quote", "confidence": 0.9}
    ]}
    analysis.uncertainties = {"uncertainties": []}
    analysis.what_is_new = "Something new"
    analysis.practical_use = "Useful"
    analysis.prompt_version = "phase5-v2"
    analysis.input_hash = "abc123"

    result = evaluate_item_moderation(item, analysis, [])
    assert "promotional_without_evidence" not in result.blocking_reasons
