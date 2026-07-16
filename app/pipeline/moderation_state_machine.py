from typing import Optional
from app.database.models import ModerationQueueStatus

ALLOWED_TRANSITIONS = {
    (None, ModerationQueueStatus.pending): True,
    (ModerationQueueStatus.pending, ModerationQueueStatus.in_review): True,
    (ModerationQueueStatus.pending, ModerationQueueStatus.approved): True,
    (ModerationQueueStatus.pending, ModerationQueueStatus.rejected): True,
    (ModerationQueueStatus.pending, ModerationQueueStatus.needs_revision): True,
    (ModerationQueueStatus.in_review, ModerationQueueStatus.approved): True,
    (ModerationQueueStatus.in_review, ModerationQueueStatus.rejected): True,
    (ModerationQueueStatus.in_review, ModerationQueueStatus.needs_revision): True,
    (ModerationQueueStatus.needs_revision, ModerationQueueStatus.pending): True,
    (ModerationQueueStatus.approved, ModerationQueueStatus.cancelled): True,
}

def is_transition_allowed(from_status: Optional[ModerationQueueStatus], to_status: ModerationQueueStatus, reason: Optional[str] = None) -> bool:
    """
    Check if the state transition for a moderation queue item is allowed.
    """
    if from_status == to_status:
        return True

    # Check mapping
    if (from_status, to_status) in ALLOWED_TRANSITIONS:
        return True

    # Rejected -> Pending transition requires a non-empty reason
    if from_status == ModerationQueueStatus.rejected and to_status == ModerationQueueStatus.pending:
        if reason and reason.strip():
            return True

    return False
