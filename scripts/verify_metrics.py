import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from datetime import datetime, timezone, timedelta
from app.database.models import Item, ItemAnalysis, Source, ModerationDecision
from app.pipeline.moderation_rules import evaluate_item_moderation

def create_mock_fixture(item_id, url, title, category, confidence, total_score, is_primary=False, status="success", age_days=5, is_promotional=False, claims=None, uncertainties=None, is_spam=False, item_status="collected"):
    item = Item(
        id=item_id,
        title=title,
        url=url,
        raw_text="This is a verified fact sentence from the original article. It has tech details.",
        published_at=datetime.now(timezone.utc) - timedelta(days=age_days),
        collected_at=datetime.now(timezone.utc) - timedelta(days=age_days),
        status=item_status,
        metadata_json={"spam": is_spam}
    )
    source = Source(trust_level=1)
    item.source = source
    
    analysis = ItemAnalysis(
        id=item_id,
        item_id=item_id,
        status=status,
        summary_ru="Краткое описание на русском языке.",
        what_is_new="Новая функциональность добавлена.",
        practical_use="Можно применить в разработке.",
        category=category,
        confidence=confidence,
        total_score=total_score,
        is_primary_source=is_primary,
        is_promotional=is_promotional,
        source_claims=claims or [],
        uncertainties=uncertainties or []
    )
    return item, analysis

def main():
    dataset = [
        # Expected: blocked
        (create_mock_fixture(1, "https://example.com/1", "Blocked Status", "news", 0.8, 8.0, status="failed"), ModerationDecision.blocked),
        (create_mock_fixture(2, "https://example.com/2", "", "news", 0.8, 8.0), ModerationDecision.blocked), # empty title
        (create_mock_fixture(3, "https://example.com/3", "Blocked Confidence", "news", 0.3, 8.0), ModerationDecision.blocked),
        (create_mock_fixture(4, "https://example.com/4", "Blocked Age", "news", 0.8, 8.0, age_days=40), ModerationDecision.blocked), # too old
        (create_mock_fixture(5, "https://example.com/5", "Blocked Spam", "news", 0.8, 8.0, is_spam=True), ModerationDecision.blocked),
        (create_mock_fixture(6, "https://example.com/6", "Blocked Category Other", "other", 0.8, 8.0), ModerationDecision.blocked), # other with relevance < 7
        
        # Expected: archive
        (create_mock_fixture(7, "https://example.com/7", "Archive Low Score", "news", 0.8, 4.0), ModerationDecision.archive),
        (create_mock_fixture(8, "https://example.com/8", "Archive Category not allowed", "prompt", 0.8, 6.0), ModerationDecision.archive), # prompt category not allowed in digest
        
        # Expected: digest_candidate
        (create_mock_fixture(9, "https://example.com/9", "Digest 5.0", "news", 0.8, 5.0), ModerationDecision.digest_candidate),
        (create_mock_fixture(10, "https://example.com/10", "Digest 6.5", "opinion", 0.8, 6.5), ModerationDecision.digest_candidate),
        
        # Expected: manual_review
        (create_mock_fixture(11, "https://example.com/11", "Manual 7.0", "news", 0.8, 7.0), ModerationDecision.manual_review),
        (create_mock_fixture(12, "https://example.com/12", "Manual 8.0", "news", 0.8, 8.0), ModerationDecision.manual_review),
        
        # Expected: priority_review
        (create_mock_fixture(13, "https://example.com/13", "Priority 8.5", "agent", 0.8, 8.5), ModerationDecision.priority_review),
        (create_mock_fixture(14, "https://example.com/14", "Priority 9.0", "mcp_server", 0.8, 9.0), ModerationDecision.priority_review),
    ]

    total = len(dataset)
    correct = 0
    true_blocked = 0
    pred_blocked = 0
    false_blocked = 0
    false_priority = 0
    
    expected_counts = {
        ModerationDecision.blocked: 0,
        ModerationDecision.archive: 0,
        ModerationDecision.digest_candidate: 0,
        ModerationDecision.manual_review: 0,
        ModerationDecision.priority_review: 0,
    }
    correct_counts = expected_counts.copy()

    for (item, analysis), expected in dataset:
        expected_counts[expected] += 1
        res = evaluate_item_moderation(item, analysis)
        actual = res.decision
        
        if actual == expected:
            correct += 1
            correct_counts[expected] += 1
            
        if expected == ModerationDecision.blocked:
            if actual == ModerationDecision.blocked:
                true_blocked += 1
        else:
            if actual == ModerationDecision.blocked:
                false_blocked += 1
                
        if actual == ModerationDecision.blocked:
            pred_blocked += 1
            
        if actual == ModerationDecision.priority_review and expected != ModerationDecision.priority_review:
            false_priority += 1

    decision_accuracy = correct / total if total > 0 else 0.0
    blocking_precision = true_blocked / pred_blocked if pred_blocked > 0 else 0.0
    
    archive_accuracy = correct_counts[ModerationDecision.archive] / expected_counts[ModerationDecision.archive] if expected_counts[ModerationDecision.archive] > 0 else 0.0
    digest_accuracy = correct_counts[ModerationDecision.digest_candidate] / expected_counts[ModerationDecision.digest_candidate] if expected_counts[ModerationDecision.digest_candidate] > 0 else 0.0
    manual_accuracy = correct_counts[ModerationDecision.manual_review] / expected_counts[ModerationDecision.manual_review] if expected_counts[ModerationDecision.manual_review] > 0 else 0.0
    priority_accuracy = correct_counts[ModerationDecision.priority_review] / expected_counts[ModerationDecision.priority_review] if expected_counts[ModerationDecision.priority_review] > 0 else 0.0

    print("# INTEGRATION DECISION METRICS REPORT")
    print(f"* **Dataset size:** {total}")
    print(f"* **decision_accuracy:** {decision_accuracy:.2%}")
    print(f"* **blocking_precision:** {blocking_precision:.2%}")
    print(f"* **false_blocked:** {false_blocked}")
    print(f"* **false_priority:** {false_priority}")
    print(f"* **archive_accuracy:** {archive_accuracy:.2%}")
    print(f"* **digest_candidate_accuracy:** {digest_accuracy:.2%}")
    print(f"* **manual_review_accuracy:** {manual_accuracy:.2%}")
    print(f"* **priority_accuracy:** {priority_accuracy:.2%}")

if __name__ == "__main__":
    main()
