import sys
import argparse
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from app.database.session import SessionLocal
from app.database.models import ModerationQueue, ModerationQueueStatus, ModerationDecisionLog
from app.database.repositories import ModerationQueueRepository, ModerationDecisionLogRepository
from app.pipeline.moderation_state_machine import is_transition_allowed

def handle_list(args, db):
    queue_repo = ModerationQueueRepository(db)
    status_str = args.status or "pending"
    try:
        status_enum = ModerationQueueStatus[status_str]
    except KeyError:
        print(f"Invalid status: {status_str}")
        return

    items = queue_repo.list_by_status(status_enum, limit=args.limit)
    print(f"=== Moderation Queue Items [status={status_str}] (count: {len(items)}) ===")
    for item in items:
        print(f"ID: {item.id} | Item ID: {item.item_id} | Analysis ID: {item.analysis_id}")
        print(f"  Decision: {item.decision} | Priority: {item.priority} | Score: {item.decision_score}")
        print(f"  Assigned To: {item.assigned_to} | Reviewed By: {item.reviewed_by}")
        print("-" * 50)

def handle_show(args, db):
    queue_repo = ModerationQueueRepository(db)
    log_repo = ModerationDecisionLogRepository(db)
    item = queue_repo.get_by_id(args.queue_id)
    if not item:
        print(f"Queue item {args.queue_id} not found")
        return

    print(f"=== Moderation Queue Item #{item.id} ===")
    print(f"Item ID: {item.item_id}")
    print(f"Analysis ID: {item.analysis_id}")
    print(f"Queue Status: {item.queue_status}")
    print(f"Decision: {item.decision}")
    print(f"Priority: {item.priority}")
    print(f"Decision Score: {item.decision_score}")
    print(f"Decision Reasons: {item.decision_reasons}")
    print(f"Blocking Reasons: {item.blocking_reasons}")
    print(f"Warnings: {item.warnings}")
    print(f"Assigned To: {item.assigned_to}")
    print(f"Reviewed By: {item.reviewed_by}")
    print(f"Review Notes: {item.review_notes}")
    print(f"Queued At: {item.queued_at}")
    print(f"Review Started: {item.review_started_at}")
    print(f"Reviewed At: {item.reviewed_at}")
    
    logs = log_repo.list_for_queue(item.id)
    print(f"\n--- History Logs (count: {len(logs)}) ---")
    for log in logs:
        print(f"[{log.created_at}] Action: {log.action} | Status: {log.previous_status} -> {log.new_status} | Actor: {log.actor}")
        if log.reason:
            print(f"  Reason: {log.reason}")

def handle_transition(args, db, target_status, action_name):
    queue_repo = ModerationQueueRepository(db)
    log_repo = ModerationDecisionLogRepository(db)
    item = queue_repo.get_by_id(args.queue_id)
    if not item:
        print(f"Queue item {args.queue_id} not found")
        return

    prev_status = item.queue_status
    reviewer = args.reviewer or "system"
    reason = args.reason or ""

    if not is_transition_allowed(prev_status, target_status, reason):
        print(f"Transition from {prev_status} to {target_status} is NOT allowed!")
        return

    # Update queue status
    queue_repo.update_status(item.id, target_status, reviewer=reviewer, notes=reason)
    
    # Create log
    log = ModerationDecisionLog(
        queue_id=item.id,
        previous_status=prev_status,
        new_status=target_status,
        action=action_name,
        actor=reviewer,
        reason=reason
    )
    log_repo.create(log)
    print(f"Successfully transitioned queue item #{item.id} status: {prev_status} -> {target_status} ({action_name} by {reviewer})")

def handle_assign(args, db):
    queue_repo = ModerationQueueRepository(db)
    log_repo = ModerationDecisionLogRepository(db)
    item = queue_repo.get_by_id(args.queue_id)
    if not item:
        print(f"Queue item {args.queue_id} not found")
        return

    assignee = args.assignee
    queue_repo.assign(item.id, assignee)
    
    log = ModerationDecisionLog(
        queue_id=item.id,
        previous_status=item.queue_status,
        new_status=item.queue_status,
        action="assign",
        actor="system",
        reason=f"Assigned to {assignee}"
    )
    log_repo.create(log)
    print(f"Successfully assigned queue item #{item.id} to {assignee}")

def main():
    parser = argparse.ArgumentParser(description="AI Radar Moderation Review CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    list_parser = subparsers.add_parser("list", help="List moderation queue items")
    list_parser.add_argument("--status", type=str, default="pending", help="Filter by status (pending, approved, rejected, etc.)")
    list_parser.add_argument("--limit", type=int, default=50, help="Max items to list")

    # show
    show_parser = subparsers.add_parser("show", help="Show details and history of a queue item")
    show_parser.add_argument("--queue-id", type=int, required=True, help="Queue item ID")

    # approve
    approve_parser = subparsers.add_parser("approve", help="Approve a queue item")
    approve_parser.add_argument("--queue-id", type=int, required=True)
    approve_parser.add_argument("--reviewer", type=str, required=True)
    approve_parser.add_argument("--reason", type=str)

    # reject
    reject_parser = subparsers.add_parser("reject", help="Reject a queue item")
    reject_parser.add_argument("--queue-id", type=int, required=True)
    reject_parser.add_argument("--reviewer", type=str, required=True)
    reject_parser.add_argument("--reason", type=str)

    # needs-revision
    revision_parser = subparsers.add_parser("needs-revision", help="Set queue item status to needs_revision")
    revision_parser.add_argument("--queue-id", type=int, required=True)
    revision_parser.add_argument("--reviewer", type=str, required=True)
    revision_parser.add_argument("--reason", type=str)

    # assign
    assign_parser = subparsers.add_parser("assign", help="Assign queue item to a moderator")
    assign_parser.add_argument("--queue-id", type=int, required=True)
    assign_parser.add_argument("--assignee", type=str, required=True)

    args = parser.parse_args()
    db = SessionLocal()
    try:
        if args.command == "list":
            handle_list(args, db)
        elif args.command == "show":
            handle_show(args, db)
        elif args.command == "approve":
            handle_transition(args, db, ModerationQueueStatus.approved, "approve")
        elif args.command == "reject":
            handle_transition(args, db, ModerationQueueStatus.rejected, "reject")
        elif args.command == "needs-revision":
            handle_transition(args, db, ModerationQueueStatus.needs_revision, "needs_revision")
        elif args.command == "assign":
            handle_assign(args, db)
    finally:
        db.close()

if __name__ == "__main__":
    main()
