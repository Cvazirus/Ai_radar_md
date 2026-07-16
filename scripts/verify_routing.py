import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from datetime import datetime, timezone, timedelta
from app.database.models import Item, ItemAnalysis, Source, AnalysisStatus, CategoryEnum
from app.pipeline.moderation_rules import evaluate_item_moderation

def create_item(url, title, status="collected"):
    item = Item(
        id=1,
        title=title,
        url=url,
        raw_text="This is a verified fact sentence from the original article. It has tech details.",
        published_at=datetime.now(timezone.utc) - timedelta(days=5),
        collected_at=datetime.now(timezone.utc) - timedelta(days=5),
        status=status,
        metadata_json={}
    )
    # Mock source
    source = Source(trust_level=1)
    item.source = source
    return item

def create_analysis(category, confidence, total_score, status="success"):
    analysis = ItemAnalysis(
        id=1,
        item_id=1,
        status=status,
        summary_ru="Краткое описание на русском языке.",
        what_is_new="Новая функциональность добавлена.",
        practical_use="Можно применить в разработке.",
        category=category,
        confidence=confidence,
        total_score=total_score,
        is_primary_source=False,
        is_promotional=False,
        source_claims=[],
        uncertainties=[]
    )
    return analysis

def run():
    # 1. Blocked
    item_blocked = create_item("https://example.com/blocked", "Blocked Item")
    analysis_blocked = create_analysis("news", 0.3, 8.0) # low confidence -> blocked
    res_blocked = evaluate_item_moderation(item_blocked, analysis_blocked)

    # 2. Archive
    item_archive = create_item("https://example.com/archive", "Archive Item")
    analysis_archive = create_analysis("news", 0.8, 4.0) # valid, score = 4.0 -> archive
    res_archive = evaluate_item_moderation(item_archive, analysis_archive)

    # 3. Digest Candidate
    item_digest = create_item("https://example.com/digest", "Digest Item")
    analysis_digest = create_analysis("news", 0.8, 6.0) # valid, score = 6.0 -> digest_candidate
    res_digest = evaluate_item_moderation(item_digest, analysis_digest)

    # 4. Manual Review
    item_review = create_item("https://example.com/review", "Review Item")
    analysis_review = create_analysis("news", 0.8, 7.5) # valid, score = 7.5 -> manual_review
    res_review = evaluate_item_moderation(item_review, analysis_review)

    # 5. Priority Review
    item_priority = create_item("https://example.com/priority", "Priority Item")
    analysis_priority = create_analysis("agent", 0.8, 8.8) # valid, score = 8.8 + category bonus 0.5 = 9.3 -> priority_review
    res_priority = evaluate_item_moderation(item_priority, analysis_priority)

    # Output details
    cases = [
        ("Blocked", res_blocked, analysis_blocked, item_blocked),
        ("Archive", res_archive, analysis_archive, item_archive),
        ("Digest Candidate", res_digest, analysis_digest, item_digest),
        ("Manual Review", res_review, analysis_review, item_review),
        ("Priority Review", res_priority, analysis_priority, item_priority),
    ]

    print("# INTEGRATION FIXTURES ROUTING VERIFICATION")
    for name, res, analysis, item in cases:
        print(f"\n### Case: {name}")
        print(f"* **Input Category:** {analysis.category}")
        print(f"* **Input Score:** {analysis.total_score}")
        print(f"* **Input Confidence:** {analysis.confidence}")
        print(f"* **Decision Score:** {res.decision_score}")
        print(f"* **Blocking Reasons:** {res.blocking_reasons}")
        print(f"* **Decision Reasons Breakdown:** {res.decision_reasons}")
        print(f"* **Итоговое решение (decision):** {res.decision}")
        print(f"* **Приоритет (priority):** {res.priority}")
        print("-" * 50)

if __name__ == "__main__":
    run()
