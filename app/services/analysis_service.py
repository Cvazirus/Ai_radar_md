import structlog
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy.orm import Session
from app.config import settings
from app.database.models import (
    Item, ItemStatus, ItemAnalysis, AnalysisStatus
)
from app.database.repositories import (
    ItemRepository, AnalysisRepository
)
from app.llm.client import LLMClient, LLMError, LLMInvalidResponseError
from app.llm.schemas import AnalysisRequest, AnalysisResult
from app.pipeline.input_hash import calculate_analysis_input_hash
from app.pipeline.json_extraction import extract_json_object, InvalidJSONError
from app.pipeline.claim_validation import validate_source_claims
from app.pipeline.source_validation import validate_primary_source
from app.pipeline.scoring import calculate_score

logger = structlog.get_logger()


class AnalysisService:
    def __init__(self, db: Session):
        self.db = db
        self.item_repo = ItemRepository(db)
        self.analysis_repo = AnalysisRepository(db)
        self.llm_client = LLMClient()

    def analyze_batch(self, limit: int = 10, force: bool = False,
                      force_reason: Optional[str] = None,
                      only_source_id: Optional[int] = None) -> dict:
        stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0, "invalid": 0}

        if not settings.LLM_ANALYSIS_ENABLED:
            logger.info("llm_analysis_disabled_in_config")
            return stats

        query = self.db.query(Item).filter(
            Item.status.in_([ItemStatus.collected, ItemStatus.normalized])
        )
        if only_source_id:
            query = query.filter(Item.source_id == only_source_id)

        pending_items = query.order_by(Item.id.asc()).limit(limit).all()
        stats["total"] = len(pending_items)

        if not pending_items:
            logger.info("no_pending_items_to_analyze")
            return stats

        for item in pending_items:
            try:
                result = self.analyze_single_item(item, force=force, force_reason=force_reason)
                if result == "skipped_existing":
                    stats["skipped"] += 1
                else:
                    stats["success"] += 1
            except Exception as e:
                error_type = type(e).__name__
                if "invalid" in str(e).lower() or isinstance(e, InvalidJSONError):
                    stats["invalid"] += 1
                else:
                    stats["failed"] += 1
                logger.error("item_analysis_failed", item_id=item.id, error=str(e))

        return stats

    def analyze_single_item(self, item: Item, force: bool = False, force_reason: Optional[str] = None):
        if not settings.LLM_ANALYSIS_ENABLED:
            raise ValueError("LLM analysis is disabled in configuration.")

        raw_text = item.raw_text or item.title
        input_chars = len(raw_text)

        request = AnalysisRequest(
            item_id=item.id,
            source_name=item.source.name if item.source else "Unknown",
            source_type=item.source.source_type if item.source else "rss",
            source_url=item.url,
            title=item.title,
            author=item.author,
            published_at=item.published_at,
            language=item.language,
            raw_text=raw_text,
            metadata=item.metadata_json or {}
        )

        input_hash = calculate_analysis_input_hash(
            item_id=item.id,
            title=item.title,
            raw_text=raw_text,
            source_url=item.url,
            model_name=settings.LLM_MODEL,
            prompt_version=settings.LLM_PROMPT_VERSION,
            analysis_version=settings.LLM_ANALYSIS_VERSION,
        )

        if not force:
            existing = self.db.query(ItemAnalysis).filter(
                ItemAnalysis.input_hash == input_hash,
                ItemAnalysis.status == AnalysisStatus.success,
            ).first()
            if existing:
                logger.info("analysis_skipped_existing", item_id=item.id, input_hash=input_hash[:16], existing_status=str(existing.status))
                return "skipped_existing"

        analysis = ItemAnalysis(
            item_id=item.id,
            model_name=settings.LLM_MODEL,
            prompt_version=settings.LLM_PROMPT_VERSION,
            analysis_version=settings.LLM_ANALYSIS_VERSION,
            status=AnalysisStatus.pending,
            input_hash=input_hash,
            input_chars=input_chars,
            attempt_count=0,
            force_reason=force_reason if force else None,
            force_run=force
        )
        self.analysis_repo.create(analysis)

        analysis.status = AnalysisStatus.running
        analysis.started_at = datetime.now(timezone.utc)
        analysis.attempt_count = 1
        self.analysis_repo.update(analysis)

        try:
            self._run_analysis(analysis, item, request, attempt=1)
            return "success"
        except Exception as e:
            analysis.status = AnalysisStatus.failed
            analysis.error_type = type(e).__name__
            analysis.error_message = str(e)[:2000]
            analysis.finished_at = datetime.now(timezone.utc)
            if analysis.started_at:
                analysis.duration_ms = int((analysis.finished_at - analysis.started_at).total_seconds() * 1000)
            self.analysis_repo.update(analysis)
            raise

    def _run_analysis(self, analysis: ItemAnalysis, item: Item,
                      request: AnalysisRequest, attempt: int):
        system_prompt = self.llm_client._load_system_prompt()
        user_prompt = self.llm_client._build_user_prompt(request)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        raw_response = self.llm_client.raw_completion(messages)
        self.llm_client.last_raw_response = raw_response

        analysis.raw_llm_response = raw_response if settings.LLM_STORE_RAW_RESPONSE else None
        analysis.response_chars = len(raw_response)

        # Step 1: Extract JSON
        try:
            json_data = extract_json_object(raw_response)
        except InvalidJSONError as e:
            if attempt < 2:
                return self._attempt_repair(analysis, item, request, raw_response, [str(e)])
            analysis.status = AnalysisStatus.invalid_response
            analysis.error_type = "InvalidJSONError"
            analysis.error_message = str(e)
            analysis.finished_at = datetime.now(timezone.utc)
            if analysis.started_at:
                analysis.duration_ms = int((analysis.finished_at - analysis.started_at).total_seconds() * 1000)
            self.analysis_repo.update(analysis)
            return

        # Step 2: Pydantic validation
        try:
            result = AnalysisResult.model_validate(json_data)
        except Exception as e:
            if attempt < 2:
                return self._attempt_repair(analysis, item, request, raw_response, [str(e)])
            analysis.status = AnalysisStatus.invalid_response
            analysis.error_type = "ValidationError"
            analysis.error_message = str(e)[:2000]
            analysis.finished_at = datetime.now(timezone.utc)
            if analysis.started_at:
                analysis.duration_ms = int((analysis.finished_at - analysis.started_at).total_seconds() * 1000)
            self.analysis_repo.update(analysis)
            return

        # Step 3: Claim validation
        claim_result = validate_source_claims(raw_text=item.raw_text or item.title, claims=result.source_claims)
        if claim_result.invalid_claims:
            if attempt < 2:
                errors = [f"Invalid claim evidence: {c.claim}" for c in claim_result.invalid_claims]
                return self._attempt_repair(analysis, item, request, raw_response, errors)
            analysis.status = AnalysisStatus.invalid_response
            analysis.error_type = "InvalidClaims"
            analysis.error_message = f"{len(claim_result.invalid_claims)} claims with invalid evidence"
            analysis.finished_at = datetime.now(timezone.utc)
            if analysis.started_at:
                analysis.duration_ms = int((analysis.finished_at - analysis.started_at).total_seconds() * 1000)
            self.analysis_repo.update(analysis)
            return

        # Step 4: Primary source validation
        source_result = validate_primary_source(url=item.url, llm_is_primary=result.is_primary_source)

        # Step 5: Calculate score
        has_tech_claims = any(
            c.evidence_type in ("direct_quote", "explicit_statement")
            for c in result.source_claims
        )
        has_high_uncertainty = any(u.severity == "high" for u in result.uncertainties)

        score = calculate_score(
            relevance_score=result.relevance_score,
            practicality_score=result.practicality_score,
            novelty_score=result.novelty_score,
            credibility_score=result.credibility_score,
            confidence=result.confidence,
            is_promotional=result.is_promotional,
            has_tech_claims=has_tech_claims,
            final_is_primary_source=source_result.final_value,
            has_high_uncertainty=has_high_uncertainty,
            score_version=settings.LLM_SCORE_VERSION,
        )

        # Step 6: Save success
        analysis.status = AnalysisStatus.success
        analysis.category = result.category
        analysis.tags = {"tags": result.tags}
        analysis.entities = {"entities": [e.model_dump() for e in result.entities]}
        analysis.summary_ru = result.summary_ru
        analysis.what_is_new = result.what_is_new
        analysis.why_important = result.why_important
        analysis.practical_use = result.practical_use
        analysis.target_users = {"target_users": result.target_users}
        analysis.is_primary_source = result.is_primary_source
        analysis.is_promotional = result.is_promotional
        analysis.is_actionable = result.is_actionable
        analysis.is_newsworthy = result.is_newsworthy
        analysis.source_claims = {"claims": [c.model_dump() for c in result.source_claims]}
        analysis.uncertainties = {"uncertainties": [u.model_dump() for u in result.uncertainties]}
        analysis.novelty_score = result.novelty_score
        analysis.practicality_score = result.practicality_score
        analysis.credibility_score = result.credibility_score
        analysis.relevance_score = result.relevance_score
        analysis.base_score = score.base_score
        analysis.penalties = {"penalties": score.to_penalties_json()}
        analysis.total_score = score.total_score
        analysis.score_version = score.score_version
        analysis.confidence = result.confidence
        analysis.finished_at = datetime.now(timezone.utc)
        if analysis.started_at:
            analysis.duration_ms = int((analysis.finished_at - analysis.started_at).total_seconds() * 1000)

        self.analysis_repo.update(analysis)

        item.status = ItemStatus.analyzed
        self.item_repo.update(item)

        logger.info(
            "item_analyzed_successfully",
            item_id=item.id,
            category=result.category.value,
            total_score=score.total_score,
        )

    def _attempt_repair(self, analysis: ItemAnalysis, item: Item,
                        request: AnalysisRequest, original_response: str,
                        errors: List[str]):
        analysis.attempt_count = 2
        analysis.status = AnalysisStatus.running
        self.analysis_repo.update(analysis)

        try:
            system_prompt = self.llm_client._load_system_prompt()
            from app.llm.client import REPAIR_PROMPT
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
            raw_response = self.llm_client.raw_completion(messages)
            self.llm_client.last_raw_response = raw_response
            analysis.raw_llm_response = (analysis.raw_llm_response or "") + "\n---REPAIR---\n" + raw_response
            analysis.response_chars = len(raw_response)

            json_data = extract_json_object(raw_response)
            result = AnalysisResult.model_validate(json_data)

            claim_result = validate_source_claims(raw_text=item.raw_text or item.title, claims=result.source_claims)
            if claim_result.invalid_claims:
                logger.warn(
                    "repair_dropping_unverifiable_claims",
                    item_id=item.id,
                    dropped_count=len(claim_result.invalid_claims),
                )
                result.source_claims = claim_result.valid_claims

            source_result = validate_primary_source(url=item.url, llm_is_primary=result.is_primary_source)
            has_tech_claims = any(c.evidence_type in ("direct_quote", "explicit_statement") for c in result.source_claims)
            has_high_uncertainty = any(u.severity == "high" for u in result.uncertainties)

            score = calculate_score(
                relevance_score=result.relevance_score,
                practicality_score=result.practicality_score,
                novelty_score=result.novelty_score,
                credibility_score=result.credibility_score,
                confidence=result.confidence,
                is_promotional=result.is_promotional,
                has_tech_claims=has_tech_claims,
                final_is_primary_source=source_result.final_value,
                has_high_uncertainty=has_high_uncertainty,
                score_version=settings.LLM_SCORE_VERSION,
            )

            analysis.status = AnalysisStatus.success
            analysis.category = result.category
            analysis.tags = {"tags": result.tags}
            analysis.entities = {"entities": [e.model_dump() for e in result.entities]}
            analysis.summary_ru = result.summary_ru
            analysis.what_is_new = result.what_is_new
            analysis.why_important = result.why_important
            analysis.practical_use = result.practical_use
            analysis.target_users = {"target_users": result.target_users}
            analysis.is_primary_source = result.is_primary_source
            analysis.is_promotional = result.is_promotional
            analysis.is_actionable = result.is_actionable
            analysis.is_newsworthy = result.is_newsworthy
            analysis.source_claims = {"claims": [c.model_dump() for c in result.source_claims]}
            analysis.uncertainties = {"uncertainties": [u.model_dump() for u in result.uncertainties]}
            analysis.novelty_score = result.novelty_score
            analysis.practicality_score = result.practicality_score
            analysis.credibility_score = result.credibility_score
            analysis.relevance_score = result.relevance_score
            analysis.base_score = score.base_score
            analysis.penalties = {"penalties": score.to_penalties_json()}
            analysis.total_score = score.total_score
            analysis.score_version = score.score_version
            analysis.confidence = result.confidence
            analysis.finished_at = datetime.now(timezone.utc)
            if analysis.started_at:
                analysis.duration_ms = int((analysis.finished_at - analysis.started_at).total_seconds() * 1000)
            self.analysis_repo.update(analysis)

            item.status = ItemStatus.analyzed
            self.item_repo.update(item)
            return

        except Exception as e:
            analysis.status = AnalysisStatus.invalid_response
            analysis.error_type = type(e).__name__
            analysis.error_message = str(e)[:2000]
            analysis.finished_at = datetime.now(timezone.utc)
            if analysis.started_at:
                analysis.duration_ms = int((analysis.finished_at - analysis.started_at).total_seconds() * 1000)
            self.analysis_repo.update(analysis)
            raise
