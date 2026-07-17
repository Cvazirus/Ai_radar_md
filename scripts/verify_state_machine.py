import sys
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from app.database.models import ModerationQueueStatus
from app.pipeline.moderation_state_machine import is_transition_allowed

def run():
    checks = [
        (None, ModerationQueueStatus.pending, "", True),
        (ModerationQueueStatus.pending, ModerationQueueStatus.in_review, "", True),
        (ModerationQueueStatus.pending, ModerationQueueStatus.approved, "", True),
        (ModerationQueueStatus.pending, ModerationQueueStatus.rejected, "", True),
        (ModerationQueueStatus.pending, ModerationQueueStatus.needs_revision, "", True),
        (ModerationQueueStatus.in_review, ModerationQueueStatus.approved, "", True),
        (ModerationQueueStatus.in_review, ModerationQueueStatus.rejected, "", True),
        (ModerationQueueStatus.in_review, ModerationQueueStatus.needs_revision, "", True),
        (ModerationQueueStatus.needs_revision, ModerationQueueStatus.pending, "", True),
        (ModerationQueueStatus.approved, ModerationQueueStatus.cancelled, "", True),
        (ModerationQueueStatus.rejected, ModerationQueueStatus.pending, "Re-evaluation after audit", True),
        (ModerationQueueStatus.rejected, ModerationQueueStatus.pending, "", False),
        (ModerationQueueStatus.approved, ModerationQueueStatus.in_review, "", False),
    ]

    print("# STATE MACHINE VERIFICATION REPORT")
    print("| Transition | Reason | Expected Result | Actual Result | Status |")
    print("|---|---|---|---|---|")
    for prev, target, reason, expected in checks:
        actual = is_transition_allowed(prev, target, reason)
        status = "PASS" if actual == expected else "FAIL"
        print(f"| {prev} -> {target} | '{reason}' | {expected} | {actual} | {status} |")

if __name__ == "__main__":
    run()
