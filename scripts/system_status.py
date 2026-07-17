"""CLI for AI Radar system status and health monitoring."""
import sys
import json
import argparse
from os.path import abspath, dirname
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from app.database.session import SessionLocal
from app.services.operations_service import OperationsService


def main():
    parser = argparse.ArgumentParser(description="AI Radar System Status")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--summary", action="store_true", help="Output human-readable summary")
    parser.add_argument("--health", action="store_true", help="Output health status only")
    parser.add_argument("--component", type=str, help="Show specific component (pipeline, scheduler, moderation, publication, collection, items, analysis)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        service = OperationsService(db)

        if args.component:
            result = service.get_component_status(args.component)
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(f"=== {args.component.upper()} ===")
                for k, v in result.items():
                    print(f"  {k}: {v}")
        elif args.health:
            status = service.get_full_status()
            health = status["health"]
            if args.json:
                print(json.dumps(health, indent=2, default=str))
            else:
                print(f"Health: {health['status'].upper()} (score: {health['score']}/100)")
                if health["issues"]:
                    for issue in health["issues"]:
                        print(f"  - {issue}")
        elif args.summary:
            print(service.get_summary())
        else:
            # Full status
            status = service.get_full_status()
            if args.json:
                print(json.dumps(status, indent=2, default=str))
            else:
                print(service.get_summary())
                print()
                # Print component details
                for comp in ["pipeline", "scheduler", "collection", "moderation", "publication"]:
                    data = status.get(comp, {})
                    if data and not data.get("error"):
                        print(f"=== {comp.upper()} ===")
                        for k, v in data.items():
                            print(f"  {k}: {v}")
                        print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
