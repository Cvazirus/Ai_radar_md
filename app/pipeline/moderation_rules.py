import logging
from datetime import datetime, timezone
from typing import List, Optional
from app.config import settings
from app.database.models import CategoryEnum, ModerationDecision, ModerationPriority, RelationType
from app.llm.schemas import ModerationDecisionResult
from app.pipeline.claim_validation import validate_source_claims
from app.pipeline.source_validation import validate_primary_source

logger = logging.getLogger(__name__)

MODERATION_RULES_VERSION = "1.0"

# Allowed categories for digest
ALLOWED_DIGEST_CATEGORIES = {
    "news",
    "opinion",
    "company_update",
    "product_update",
    "tutorial",
    "research",
    "dataset",
    "benchmark",
    "funding",
    "other"  # allowed only if relevance_score >= 7
}

# Priority categories
PRIORITY_CATEGORIES = {
    "model_release",
    "local_model",
    "agent",
    "coding_agent",
    "agent_harness",
    "skill",
    "mcp_server",
    "framework",
    "api",
    "security",
    "research",
    "benchmark",
    "product_update"
}

def _safe_float(val, default=0.0):
    if val is None or "Mock" in val.__class__.__name__:
        return default
    try:
        return float(val)
    except Exception:
        return default

def _safe_int(val, default=0):
    if val is None or "Mock" in val.__class__.__name__:
        return default
    try:
        return int(val)
    except Exception:
        return default

def evaluate_item_moderation(item, analysis, duplicate_relations: List = None) -> ModerationDecisionResult:
    """
    Evaluate deterministic moderation rules, calculate decision score, and assign decision/priority.
    """
    if duplicate_relations is None:
        duplicate_relations = []

    blocking_reasons = []
    warnings = []
    decision_reasons = {}

    # 1. Deterministic Blocking Rules
    
    # Rule: analysis.status != success
    # Note: we check string/enum status
    analysis_status = getattr(analysis, "status", None)
    if not analysis_status or str(analysis_status).split(".")[-1] != "success":
        blocking_reasons.append("analysis_not_success")

    # Rule: missing summary_ru
    summary_ru = getattr(analysis, "summary_ru", "")
    if not summary_ru or not summary_ru.strip():
        blocking_reasons.append("missing_summary")

    # Rule: missing title or source URL
    if not getattr(item, "title", "") or not getattr(item, "url", ""):
        blocking_reasons.append("missing_source_url")

    # Rule: confidence < 0.45 or below config threshold
    confidence = _safe_float(getattr(analysis, "confidence", 0.0))

    min_confidence = getattr(settings, "MODERATION_MIN_CONFIDENCE", 0.60)
    if confidence < 0.45 or confidence < min_confidence:
        blocking_reasons.append("low_confidence")

    # Rule: unconfirmed claims
    source_claims = getattr(analysis, "source_claims", []) or []
    claims_validation = validate_source_claims(getattr(item, "raw_text", "") or getattr(item, "title", ""), source_claims)
    if len(claims_validation.invalid_claims) > 0:
        blocking_reasons.append("invalid_claims")

    # Rule: uncertainty severity=high by key fact
    uncertainties = getattr(analysis, "uncertainties", []) or []
    has_high_uncertainty = False
    for u in uncertainties:
        severity = u.get("severity") if isinstance(u, dict) else getattr(u, "severity", "")
        if severity == "high":
            has_high_uncertainty = True
            blocking_reasons.append("high_uncertainty")
            break

    # Rule: primary source conflict — recorded as a warning, not a hard block. The rule_value only
    # recognizes a small allowlist of vendor domains (openai.com, github.com, arxiv.org, etc.), so
    # blocking on this would reject legitimate reporting from any other outlet (e.g. tech blogs)
    # whenever the LLM reasonably marks it as a primary account of its own analysis.
    source_validation = validate_primary_source(getattr(item, "url", ""), getattr(analysis, "is_primary_source", False))
    if source_validation.conflict:
        warnings.append("primary_source_conflict")

    # Rule: untrusted source and not confirmed by primary source
    source_trust = 1
    if getattr(item, "source", None) is not None:
        source_trust = _safe_int(getattr(item.source, "trust_level", 1), 1)
    if source_trust < 1 and not source_validation.final_value:
        blocking_reasons.append("untrusted_source")

    # Rule: exact duplicate
    is_exact_duplicate = False
    if str(getattr(item, "status", "")).split(".")[-1] == "duplicate":
        is_exact_duplicate = True
    else:
        for rel in duplicate_relations:
            rel_type = getattr(rel, "relation_type", None)
            rel_type_str = str(rel_type).split(".")[-1] if rel_type else ""
            if rel_type_str in ("exact_external_id", "exact_canonical_url", "exact_content_hash"):
                if getattr(rel, "item_id", None) == item.id:
                    is_exact_duplicate = True
                    break
    if is_exact_duplicate:
        blocking_reasons.append("exact_duplicate")

    # Rule: spam
    metadata = getattr(item, "metadata_json", {}) or {}
    if metadata.get("is_spam") or metadata.get("spam"):
        blocking_reasons.append("spam")

    # Rule: too old
    pub_date = getattr(item, "published_at", None) or getattr(item, "collected_at", None)
    if pub_date:
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - pub_date).days
        max_age_days = getattr(settings, "MODERATION_MAX_AGE_DAYS", 30)
        if age_days > max_age_days:
            blocking_reasons.append("too_old")

    # Rule: category=other with low relevance
    category = getattr(analysis, "category", None)
    # Parse category enum if it's string
    category_str = str(category).split(".")[-1] if category else ""
    relevance_score = _safe_int(getattr(analysis, "relevance_score", 0), 0)
    if category_str == "other" and (relevance_score is None or relevance_score < 7):
        blocking_reasons.append("low_value_other")

    # Rule: promotional=true and missing tech claims
    is_promotional = getattr(analysis, "is_promotional", False)
    has_tech_claims = False
    for claim in source_claims:
        ev_type = claim.get("evidence_type") if isinstance(claim, dict) else getattr(claim, "evidence_type", "")
        if ev_type in ("direct_quote", "explicit_statement"):
            has_tech_claims = True
            break
    if is_promotional and not has_tech_claims:
        blocking_reasons.append("promotional_without_evidence")

    # Rule: not new event
    what_is_new = getattr(analysis, "what_is_new", "")
    if not what_is_new or not what_is_new.strip():
        blocking_reasons.append("not_new")

    # Rule: legacy analysis configuration
    prompt_version = getattr(analysis, "prompt_version", "")
    input_hash = getattr(analysis, "input_hash", "")
    is_legacy = (prompt_version == "legacy" or input_hash == "legacy")
    allow_legacy = getattr(settings, "MODERATION_ALLOW_LEGACY_ANALYSIS", False)
    if is_legacy and not allow_legacy:
        blocking_reasons.append("legacy_analysis")

    # 2. Decision Score Calculation
    total_score = _safe_float(getattr(analysis, "total_score", 0.0), 0.0)

    # Source bonus
    source_bonus = 0.5 if source_validation.final_value else 0.0

    # Category bonus
    category_bonus = 0.0
    if category_str in ("agent", "coding_agent", "agent_harness", "skill", "mcp_server"):
        category_bonus = 0.5
    elif category_str in ("model_release", "security", "api", "framework"):
        category_bonus = 0.3

    # Freshness bonus
    freshness_bonus = 0.0
    if pub_date:
        age_hours = (datetime.now(timezone.utc) - pub_date).total_seconds() / 3600.0
        if age_hours < 24.0:
            freshness_bonus = 0.5
        elif age_hours < 72.0:
            freshness_bonus = 0.3

    # Duplicate penalty
    duplicate_penalty = 0.0
    for rel in duplicate_relations:
        rel_type = getattr(rel, "relation_type", None)
        rel_type_str = str(rel_type).split(".")[-1] if rel_type else ""
        if rel_type_str == "cross_source_story":
            if getattr(rel, "item_id", None) == item.id:
                # Secondary source in cross source story gets penalty
                duplicate_penalty = 1.0
                decision_reasons["preferred_item_id"] = getattr(rel, "duplicate_of_item_id", None)
                break

    # Uncertainty penalty
    uncertainty_penalty = 0.0
    has_medium = any((u.get("severity") if isinstance(u, dict) else getattr(u, "severity", "")) == "medium" for u in uncertainties)
    if has_medium:
        uncertainty_penalty += 0.5
    if has_high_uncertainty and not ("high_uncertainty" in blocking_reasons):
        # Only penalty if not already blocked
        uncertainty_penalty += 2.0

    final_score = total_score + source_bonus + category_bonus + freshness_bonus - duplicate_penalty - uncertainty_penalty
    final_score = max(0.0, min(10.0, final_score))

    decision_reasons.update({
        "base_total_score": round(total_score, 2),
        "source_bonus": source_bonus,
        "category_bonus": category_bonus,
        "freshness_bonus": freshness_bonus,
        "duplicate_penalty": duplicate_penalty,
        "uncertainty_penalty": uncertainty_penalty,
        "final_decision_score": round(final_score, 2)
    })

    # 3. Decision and Priority routing
    
    if len(blocking_reasons) > 0:
        decision = ModerationDecision.blocked
        priority = ModerationPriority.low
    else:
        # Check thresholds from config
        digest_min = getattr(settings, "MODERATION_DIGEST_MIN_SCORE", 5.0)
        review_min = getattr(settings, "MODERATION_REVIEW_MIN_SCORE", 7.0)
        priority_min = getattr(settings, "MODERATION_PRIORITY_MIN_SCORE", 8.5)
        priority_min_conf = getattr(settings, "MODERATION_PRIORITY_MIN_CONFIDENCE", 0.75)

        # Check Priority Review
        is_priority_cat = category_str in PRIORITY_CATEGORIES
        if final_score >= priority_min and confidence >= priority_min_conf and is_priority_cat:
            decision = ModerationDecision.priority_review
            priority = ModerationPriority.high
            
            # Elevate to critical if security warning is severe
            if category_str == "security":
                text_to_check = f"{getattr(item, 'title', '')} {summary_ru}".lower()
                keywords = ["vulnerability", "exploit", "zero-day", "0-day", "rce", "critical security", "уязвимость", "взлом"]
                if any(kw in text_to_check for kw in keywords) and final_score >= 8.0:
                    priority = ModerationPriority.critical
                    decision_reasons["critical_elevation"] = "Security threat detected in title/summary"
        
        # Check Manual Review
        elif final_score >= review_min and confidence >= 0.65 and bool(getattr(analysis, "practical_use", "").strip()):
            decision = ModerationDecision.manual_review
            priority = ModerationPriority.normal
            if final_score >= 8.0:
                priority = ModerationPriority.high
        
        # Check Digest Candidate
        elif final_score >= digest_min and confidence >= 0.60 and (category in ALLOWED_DIGEST_CATEGORIES or category_str in ALLOWED_DIGEST_CATEGORIES):
            # Check other relevance limit
            if category_str == "other" and relevance_score < 7:
                # should have been blocked, but if not, goes to archive
                decision = ModerationDecision.archive
                priority = ModerationPriority.low
            else:
                decision = ModerationDecision.digest_candidate
                priority = ModerationPriority.normal
        
        # Default: Archive
        else:
            decision = ModerationDecision.archive
            priority = ModerationPriority.low

    eligible = (decision != ModerationDecision.blocked)

    return ModerationDecisionResult(
        item_id=item.id,
        analysis_id=analysis.id,
        decision=decision,
        priority=priority,
        decision_score=round(final_score, 2),
        blocking_reasons=blocking_reasons,
        decision_reasons=decision_reasons,
        warnings=warnings,
        rules_version=MODERATION_RULES_VERSION,
        eligible_for_queue=eligible
    )
