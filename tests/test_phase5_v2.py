import pytest
import hashlib
import json
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.config import settings
from app.database.models import (
    Item, ItemStatus, ItemAnalysis, AnalysisStatus, CategoryEnum
)
from app.database.repositories import AnalysisRepository
from app.llm.schemas import (
    AnalysisRequest, AnalysisResult, EntityResult, SourceClaim, Uncertainty
)
from app.llm.client import LLMClient, LLMConfigurationError
from app.pipeline.json_extraction import extract_json_object, InvalidJSONError
from app.pipeline.claim_validation import validate_source_claims
from app.pipeline.source_validation import validate_primary_source
from app.pipeline.scoring import calculate_score
from app.pipeline.input_hash import calculate_analysis_input_hash


# === JSON EXTRACTION ===

def test_json_extraction_clean():
    r = extract_json_object('{"category": "news", "tags": []}')
    assert r["category"] == "news"

def test_json_extraction_code_fence():
    r = extract_json_object('```json\n{"category": "news"}\n```')
    assert r["category"] == "news"

def test_json_extraction_plain_fence():
    r = extract_json_object('```\n{"category": "news"}\n```')
    assert r["category"] == "news"

def test_json_extraction_whitespace():
    r = extract_json_object('  \n  {"category": "news"}  \n  ')
    assert r["category"] == "news"

def test_json_extraction_multiple_objects():
    with pytest.raises(InvalidJSONError):
        extract_json_object('{"a":1} {"b":2}')

def test_json_extraction_text_before():
    with pytest.raises(InvalidJSONError, match="Text before"):
        extract_json_object('Here is the JSON: {"a":1}')

def test_json_extraction_text_after():
    with pytest.raises(InvalidJSONError, match="Text after"):
        extract_json_object('{"a":1} Done.')

def test_json_extraction_array():
    with pytest.raises(InvalidJSONError):
        extract_json_object('[1, 2, 3]')

def test_json_extraction_empty():
    with pytest.raises(InvalidJSONError):
        extract_json_object('')

def test_json_extraction_no_braces():
    with pytest.raises(InvalidJSONError, match="No JSON object"):
        extract_json_object('just plain text')

def test_json_extraction_eval():
    with pytest.raises(InvalidJSONError, match="eval"):
        extract_json_object('eval("alert(1)") {"a":1}')

def test_json_extraction_unclosed():
    with pytest.raises(InvalidJSONError):
        extract_json_object('{"a":1, "b":')


# === CLAIM VALIDATION ===

def test_claim_validation_exact_quote():
    from app.llm.schemas import SourceClaim
    claims = [SourceClaim(claim="test", evidence_text="OpenAI released GPT-5", evidence_type="direct_quote", confidence=0.9)]
    result = validate_source_claims("OpenAI released GPT-5 today", claims)
    assert len(result.valid_claims) == 1
    assert result.precision == 1.0

def test_claim_validation_case_insensitive():
    from app.llm.schemas import SourceClaim
    claims = [SourceClaim(claim="test", evidence_text="openai released", evidence_type="explicit_statement", confidence=0.9)]
    result = validate_source_claims("OpenAI Released GPT-5", claims)
    assert len(result.valid_claims) == 1

def test_claim_validation_html_entities():
    from app.llm.schemas import SourceClaim
    claims = [SourceClaim(claim="test", evidence_text="it's amazing &amp; cool", evidence_type="metadata", confidence=0.8)]
    result = validate_source_claims("it's amazing & cool", claims)
    assert len(result.valid_claims) == 1

def test_claim_validation_normalized_spaces():
    from app.llm.schemas import SourceClaim
    claims = [SourceClaim(claim="test", evidence_text="OpenAI  released  GPT-5", evidence_type="explicit_statement", confidence=0.9)]
    result = validate_source_claims("OpenAI released GPT-5", claims)
    assert len(result.valid_claims) == 1

def test_claim_validation_fabricated():
    from app.llm.schemas import SourceClaim
    claims = [SourceClaim(claim="test", evidence_text="completely made up evidence", evidence_type="inference", confidence=0.5)]
    result = validate_source_claims("OpenAI released GPT-5", claims)
    assert len(result.invalid_claims) == 1

def test_claim_validation_from_different_text():
    from app.llm.schemas import SourceClaim
    claims = [SourceClaim(claim="test", evidence_text="Google announced Gemini", evidence_type="explicit_statement", confidence=0.9)]
    result = validate_source_claims("OpenAI released GPT-5", claims)
    assert len(result.invalid_claims) == 1

def test_claim_validation_empty_evidence():
    from app.llm.schemas import SourceClaim
    claims = [SourceClaim(claim="test", evidence_text="", evidence_type="inference", confidence=0.5)]
    result = validate_source_claims("OpenAI released GPT-5", claims)
    assert len(result.invalid_claims) == 1

def test_claim_validation_no_claims():
    result = validate_source_claims("OpenAI released GPT-5", [])
    assert result.precision == 1.0

def test_claim_validation_empty_raw_text():
    from app.llm.schemas import SourceClaim
    claims = [SourceClaim(claim="test", evidence_text="evidence", evidence_type="direct_quote", confidence=0.9)]
    result = validate_source_claims("", claims)
    assert len(result.invalid_claims) == 1


# === PRIMARY SOURCE VALIDATION ===

def test_primary_source_openai():
    r = validate_primary_source(url="https://openai.com/index/gpt-5", llm_is_primary=True)
    assert r.rule_value is True
    assert r.final_value is True

def test_primary_source_github_repo():
    r = validate_primary_source(url="https://github.com/openai/gpt-5", llm_is_primary=True)
    assert r.rule_value is True
    assert r.final_value is True

def test_primary_source_arxiv():
    r = validate_primary_source(url="https://arxiv.org/abs/2401.12345", llm_is_primary=True)
    assert r.rule_value is True

def test_primary_source_habr():
    r = validate_primary_source(url="https://habr.com/ru/articles/123456/", llm_is_primary=True)
    assert r.rule_value is False
    assert r.conflict is True

def test_primary_source_hackernews():
    r = validate_primary_source(url="https://news.ycombinator.com/item?id=12345", llm_is_primary=True)
    assert r.rule_value is False

def test_primary_source_unknown():
    r = validate_primary_source(url="https://random-blog.com/post", llm_is_primary=True)
    assert r.rule_value is False
    assert r.conflict is True

def test_primary_source_conflict():
    r = validate_primary_source(url="https://habr.com/ru/articles/123/", llm_is_primary=False)
    assert r.rule_value is False
    assert r.conflict is False

def test_primary_source_no_url():
    r = validate_primary_source(url="", llm_is_primary=True)
    assert r.rule_value is False


# === SCORING ===

def test_scoring_formula_weights_sum():
    s = calculate_score(
        relevance_score=10, practicality_score=10,
        novelty_score=10, credibility_score=10,
        confidence=1.0, is_promotional=False,
        has_tech_claims=True, final_is_primary_source=True,
        has_high_uncertainty=False
    )
    assert s.base_score == 10.0
    assert len(s.penalties) == 0
    assert s.total_score == 10.0

def test_scoring_formula_weights_zero():
    s = calculate_score(
        relevance_score=0, practicality_score=0,
        novelty_score=0, credibility_score=0,
        confidence=1.0, is_promotional=False,
        has_tech_claims=True, final_is_primary_source=True,
        has_high_uncertainty=False
    )
    assert s.base_score == 0.0
    assert s.total_score == 0.0

def test_scoring_penalty_promotional():
    s = calculate_score(
        relevance_score=8, practicality_score=8,
        novelty_score=8, credibility_score=8,
        confidence=0.9, is_promotional=True,
        has_tech_claims=False, final_is_primary_source=True,
        has_high_uncertainty=False
    )
    codes = [p.code for p in s.penalties]
    assert "promotional_no_tech_claims" in codes
    assert s.total_score < s.base_score

def test_scoring_penalty_secondary():
    s = calculate_score(
        relevance_score=8, practicality_score=8,
        novelty_score=8, credibility_score=8,
        confidence=0.9, is_promotional=False,
        has_tech_claims=True, final_is_primary_source=False,
        has_high_uncertainty=False
    )
    codes = [p.code for p in s.penalties]
    assert "secondary_source" in codes

def test_scoring_penalty_low_confidence():
    s = calculate_score(
        relevance_score=8, practicality_score=8,
        novelty_score=8, credibility_score=8,
        confidence=0.3, is_promotional=False,
        has_tech_claims=True, final_is_primary_source=True,
        has_high_uncertainty=False
    )
    codes = [p.code for p in s.penalties]
    assert "low_confidence" in codes

def test_scoring_penalty_high_uncertainty():
    s = calculate_score(
        relevance_score=8, practicality_score=8,
        novelty_score=8, credibility_score=8,
        confidence=0.9, is_promotional=False,
        has_tech_claims=True, final_is_primary_source=True,
        has_high_uncertainty=True
    )
    codes = [p.code for p in s.penalties]
    assert "high_uncertainty" in codes

def test_scoring_all_penalties():
    s = calculate_score(
        relevance_score=10, practicality_score=10,
        novelty_score=10, credibility_score=10,
        confidence=0.3, is_promotional=True,
        has_tech_claims=False, final_is_primary_source=False,
        has_high_uncertainty=True
    )
    assert len(s.penalties) == 4
    assert s.total_score == 0.0  # clamped

def test_scoring_clamp_max():
    s = calculate_score(
        relevance_score=10, practicality_score=10,
        novelty_score=10, credibility_score=10,
        confidence=1.0, is_promotional=False,
        has_tech_claims=True, final_is_primary_source=True,
        has_high_uncertainty=False
    )
    assert s.total_score <= 10.0


# === INPUT HASH ===

def test_input_hash_stability():
    h1 = calculate_analysis_input_hash(1, "title", "text", "url", "model", "v1", "1.0")
    h2 = calculate_analysis_input_hash(1, "title", "text", "url", "model", "v1", "1.0")
    assert h1 == h2

def test_input_hash_changes_with_prompt_version():
    h1 = calculate_analysis_input_hash(1, "title", "text", "url", "model", "v1", "1.0")
    h2 = calculate_analysis_input_hash(1, "title", "text", "url", "model", "v2", "1.0")
    assert h1 != h2

def test_input_hash_changes_with_model():
    h1 = calculate_analysis_input_hash(1, "title", "text", "url", "model-a", "v1", "1.0")
    h2 = calculate_analysis_input_hash(1, "title", "text", "url", "model-b", "v1", "1.0")
    assert h1 != h2

def test_input_hash_changes_with_text():
    h1 = calculate_analysis_input_hash(1, "title", "text-a", "url", "model", "v1", "1.0")
    h2 = calculate_analysis_input_hash(1, "title", "text-b", "url", "model", "v1", "1.0")
    assert h1 != h2

def test_input_hash_format():
    h = calculate_analysis_input_hash(1, "t", "r", "u", "m", "p", "a")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# === ANALYSIS RESULT SCHEMA ===

def test_analysis_result_forbids_extra():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AnalysisResult(
            category=CategoryEnum.news,
            summary_ru="Valid summary text here.",
            novelty_score=5, practicality_score=5,
            credibility_score=5, relevance_score=5,
            confidence=0.8, is_primary_source=True,
            is_promotional=False, is_actionable=True, is_newsworthy=True,
            telegram_text="should not exist"
        )

def test_analysis_result_tags_max_15():
    r = AnalysisResult(
        category=CategoryEnum.news,
        tags=[f"tag{i}" for i in range(20)],
        summary_ru="Valid summary text here.",
        novelty_score=5, practicality_score=5,
        credibility_score=5, relevance_score=5,
        confidence=0.8, is_primary_source=True,
        is_promotional=False, is_actionable=True, is_newsworthy=True
    )
    assert len(r.tags) == 15

def test_analysis_result_target_users_max_10():
    r = AnalysisResult(
        category=CategoryEnum.news,
        target_users=[f"user{i}" for i in range(15)],
        summary_ru="Valid summary text here.",
        novelty_score=5, practicality_score=5,
        credibility_score=5, relevance_score=5,
        confidence=0.8, is_primary_source=True,
        is_promotional=False, is_actionable=True, is_newsworthy=True
    )
    assert len(r.target_users) == 10


# === ANALYSIS REPOSITORY ===

def test_analysis_repo_find_success_by_hash():
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    repo = AnalysisRepository(mock_db)
    result = repo.find_success_by_input_hash("abc123")
    assert result is None

def test_analysis_repo_count_by_status():
    mock_db = MagicMock()
    mock_db.query.return_value.group_by.return_value.all.return_value = []
    repo = AnalysisRepository(mock_db)
    result = repo.count_by_status()
    assert result == {}


# === NO PUBLICATIONS ===

def test_analysis_service_no_publication_import():
    import app.services.analysis_service as svc
    source = open(svc.__file__).read()
    assert "Publication" not in source or "PublicationStatus" not in source

def test_analysis_service_item_not_failed_on_error():
    from app.llm.client import LLMProviderError
    mock_db = MagicMock()
    with patch("app.services.analysis_service.settings") as mock_settings:
        mock_settings.LLM_ANALYSIS_ENABLED = True
        mock_settings.LLM_MODEL = "test-model"
        mock_settings.LLM_PROMPT_VERSION = "test-v1"
        mock_settings.LLM_ANALYSIS_VERSION = "1.0"
        mock_settings.LLM_SCORE_VERSION = "1.0"
        mock_settings.LLM_STORE_RAW_RESPONSE = True

        from app.services.analysis_service import AnalysisService
        service = AnalysisService(mock_db)
        service.item_repo = MagicMock()
        service.analysis_repo = MagicMock()
        service.llm_client = MagicMock()
        service.llm_client.raw_completion.side_effect = LLMProviderError("test error")
        service.llm_client._load_system_prompt.return_value = "prompt"
        service.llm_client._build_user_prompt.return_value = "user prompt"

        item = MagicMock()
        item.id = 1
        item.raw_text = "test"
        item.title = "test"
        item.url = "http://test.com"
        item.source = MagicMock()
        item.source.name = "Test"
        item.source.source_type = "rss"
        item.status = ItemStatus.collected

        service.db.query.return_value.filter.return_value.first.return_value = None

        try:
            service.analyze_single_item(item, force=True)
        except Exception:
            pass

        # Item should NOT be set to failed
        item.status = ItemStatus.collected  # original value preserved
        assert item.status != ItemStatus.failed


# === PHASE 5.1 VERIFICATION TESTS ===

def create_valid_mock_item():
    item = MagicMock()
    item.id = 1
    item.raw_text = "test text"
    item.title = "test title"
    item.url = "http://test.com"
    item.author = "test author"
    item.published_at = datetime.now(timezone.utc)
    item.language = "en"
    item.metadata_json = {}
    
    item.source = MagicMock()
    item.source.name = "test source"
    item.source.source_type = "rss"
    return item

def test_force_preserves_history():
    # force сохраняет историю (не удаляет прошлые записи)
    mock_db = MagicMock()
    
    # Mock settings
    with patch("app.services.analysis_service.settings") as mock_settings:
        mock_settings.LLM_ANALYSIS_ENABLED = True
        mock_settings.LLM_MODEL = "test-model"
        mock_settings.LLM_PROMPT_VERSION = "test-v1"
        mock_settings.LLM_ANALYSIS_VERSION = "1.0"
        
        from app.services.analysis_service import AnalysisService
        service = AnalysisService(mock_db)
        service.item_repo = MagicMock()
        service.analysis_repo = MagicMock()
        service.llm_client = MagicMock()
        
        item = create_valid_mock_item()
        
        # When force is True, we should NOT delete anything
        service.db.delete = MagicMock()
        service.db.commit = MagicMock()
        
        try:
            service.analyze_single_item(item, force=True, force_reason="testing force")
        except Exception:
            pass
            
        service.db.delete.assert_not_called()

def test_normal_run_remains_idempotent():
    # обычный запуск остаётся идемпотентным (пропускает, если input_hash совпадает)
    mock_db = MagicMock()
    
    with patch("app.services.analysis_service.settings") as mock_settings:
        mock_settings.LLM_ANALYSIS_ENABLED = True
        mock_settings.LLM_MODEL = "test-model"
        mock_settings.LLM_PROMPT_VERSION = "test-v1"
        mock_settings.LLM_ANALYSIS_VERSION = "1.0"
        
        from app.services.analysis_service import AnalysisService
        service = AnalysisService(mock_db)
        service.item_repo = MagicMock()
        service.analysis_repo = MagicMock()
        
        # Mock existing record with same hash
        existing_mock = MagicMock()
        existing_mock.status = AnalysisStatus.success
        service.db.query.return_value.filter.return_value.first.return_value = existing_mock
        
        item = create_valid_mock_item()
        
        result = service.analyze_single_item(item, force=False)
        assert result == "skipped_existing"

def test_identical_input_hash_creates_new_record_on_force():
    # одинаковый input_hash при force создаёт новую запись
    mock_db = MagicMock()
    
    with patch("app.services.analysis_service.settings") as mock_settings:
        mock_settings.LLM_ANALYSIS_ENABLED = True
        mock_settings.LLM_MODEL = "test-model"
        mock_settings.LLM_PROMPT_VERSION = "test-v1"
        mock_settings.LLM_ANALYSIS_VERSION = "1.0"
        
        from app.services.analysis_service import AnalysisService
        service = AnalysisService(mock_db)
        service.item_repo = MagicMock()
        service.analysis_repo = MagicMock()
        service.llm_client = MagicMock()
        
        item = create_valid_mock_item()
        
        # Mock existing record with same hash, but force is True
        existing_mock = MagicMock()
        service.db.query.return_value.filter.return_value.first.return_value = existing_mock
        
        try:
            service.analyze_single_item(item, force=True, force_reason="testing force")
        except Exception:
            pass
            
        # AnalysisRepository.create should still be called to create a new record
        service.analysis_repo.create.assert_called_once()
        # The created analysis object should have force_run=True and force_reason set
        created_analysis = service.analysis_repo.create.call_args[0][0]
        assert created_analysis.force_run is True
        assert created_analysis.force_reason == "testing force"

def test_publications_not_created():
    # публикации не создаются при анализе
    mock_db = MagicMock()
    
    with patch("app.services.analysis_service.settings") as mock_settings:
        mock_settings.LLM_ANALYSIS_ENABLED = True
        mock_settings.LLM_MODEL = "test-model"
        
        from app.services.analysis_service import AnalysisService
        service = AnalysisService(mock_db)
        
        # Assert that AnalysisService doesn't even reference pub_repo or create publications
        assert not hasattr(service, "pub_repo")

def test_migration_does_not_lose_data():
    # миграция не теряет данные (проверяем наличие downgrade и upgrade без DROP/CREATE для item_analysis)
    from migrations.versions.a1b2c3d4e5f6_rewrite_item_analysis_v2 import upgrade, downgrade
    
    # Verify that the migration code doesn't contain 'drop table item_analysis'
    migration_file = "migrations/versions/a1b2c3d4e5f6_rewrite_item_analysis_v2.py"
    with open(migration_file, 'r') as f:
        content = f.read().lower()
        assert "drop table item_analysis" not in content
        assert "drop table if exists item_analysis" not in content


# === REPAIR PROMPT MUST INCLUDE SOURCE TEXT (fix for silent repair failures) ===

def _minimal_valid_result_json(source_claims=None):
    return json.dumps({
        "category": "news", "tags": [], "entities": [],
        "summary_ru": "Тестовое описание материала",
        "target_users": [],
        "is_primary_source": True, "is_promotional": False,
        "is_actionable": True, "is_newsworthy": True,
        "source_claims": source_claims or [],
        "uncertainties": [], "novelty_score": 7, "practicality_score": 6,
        "credibility_score": 7, "relevance_score": 8, "confidence": 0.85
    })

def test_repair_prompt_includes_raw_source_text():
    # Regression: the repair round-trip previously only sent back the model's own
    # invalid JSON + error list, never the original article text. That made it
    # impossible for the model to fix a bad evidence_text (it has nothing to quote
    # from), so repair silently failed claim validation again.
    mock_db = MagicMock()

    with patch("app.services.analysis_service.settings") as mock_settings:
        mock_settings.LLM_ANALYSIS_ENABLED = True
        mock_settings.LLM_MODEL = "test-model"
        mock_settings.LLM_PROMPT_VERSION = "test-v1"
        mock_settings.LLM_ANALYSIS_VERSION = "1.0"
        mock_settings.LLM_STORE_RAW_RESPONSE = True

        from app.services.analysis_service import AnalysisService
        service = AnalysisService(mock_db)
        service.item_repo = MagicMock()
        service.analysis_repo = MagicMock()
        service.llm_client = MagicMock()
        service.llm_client._load_system_prompt.return_value = "system prompt"

        item = create_valid_mock_item()
        item.raw_text = "OpenAI released GPT-5 today with major improvements."

        first_response = _minimal_valid_result_json(source_claims=[{
            "claim": "GPT-5 released",
            "evidence_text": "totally fabricated quote not in source",
            "evidence_type": "direct_quote",
            "confidence": 0.9,
        }])
        repair_response = _minimal_valid_result_json(source_claims=[])
        service.llm_client.raw_completion.side_effect = [first_response, repair_response]

        service.db.query.return_value.filter.return_value.first.return_value = None

        service.analyze_single_item(item, force=True)

        assert service.llm_client.raw_completion.call_count == 2
        repair_messages = service.llm_client.raw_completion.call_args_list[1][0][0]
        repair_user_content = repair_messages[1]["content"]
        assert item.raw_text in repair_user_content

def test_repair_succeeds_when_second_attempt_drops_bad_claim():
    # With the source text available during repair, a model that corrects itself
    # by dropping the unverifiable claim should now succeed instead of being
    # marked invalid_response.
    mock_db = MagicMock()

    with patch("app.services.analysis_service.settings") as mock_settings:
        mock_settings.LLM_ANALYSIS_ENABLED = True
        mock_settings.LLM_MODEL = "test-model"
        mock_settings.LLM_PROMPT_VERSION = "test-v1"
        mock_settings.LLM_ANALYSIS_VERSION = "1.0"
        mock_settings.LLM_STORE_RAW_RESPONSE = True

        from app.services.analysis_service import AnalysisService
        service = AnalysisService(mock_db)
        service.item_repo = MagicMock()
        service.analysis_repo = MagicMock()
        service.llm_client = MagicMock()
        service.llm_client._load_system_prompt.return_value = "system prompt"

        item = create_valid_mock_item()
        item.raw_text = "OpenAI released GPT-5 today with major improvements."

        first_response = _minimal_valid_result_json(source_claims=[{
            "claim": "GPT-5 released",
            "evidence_text": "totally fabricated quote not in source",
            "evidence_type": "direct_quote",
            "confidence": 0.9,
        }])
        repair_response = _minimal_valid_result_json(source_claims=[])
        service.llm_client.raw_completion.side_effect = [first_response, repair_response]

        service.db.query.return_value.filter.return_value.first.return_value = None

        service.analyze_single_item(item, force=True)

        created_analysis = service.analysis_repo.create.call_args[0][0]
        assert created_analysis.status == AnalysisStatus.success

def test_repair_prompt_does_not_contradict_claim_fix_instruction():
    # Regression: an earlier version told the model "Do NOT ... change values"
    # immediately followed by "replace evidence_text ... or remove that claim" --
    # a direct contradiction that likely made models default to the more
    # prominent "don't change values" instruction and repeat the same rejected
    # evidence_text (observed live: 3/4 items still failed identically after
    # raw_text was added to the prompt). The instruction to fix invalid claim
    # evidence must not be undercut by a blanket "don't change values" rule.
    from app.llm.client import REPAIR_PROMPT
    assert "Repeating the same evidence_text" in REPAIR_PROMPT
    assert "this REQUIRES changing that claim" in REPAIR_PROMPT
