from typing import Optional, List
"""CLI for viewing latest AI Radar digest."""
import sys
import json
import argparse
from os.path import abspath, dirname
from pathlib import Path
sys.path.insert(0, dirname(dirname(abspath(__file__))))

DIGESTS_DIR = Path("/app/output/digests")


def find_latest_digest() -> Optional[Path]:
    """Find the latest digest file."""
    if not DIGESTS_DIR.exists():
        return None

    md_files = sorted(DIGESTS_DIR.glob("*.md"), reverse=True)
    return md_files[0] if md_files else None


def list_digests() -> List[Path]:
    """List all digest files."""
    if not DIGESTS_DIR.exists():
        return []
    return sorted(DIGESTS_DIR.glob("*.md"), reverse=True)


def main():
    from typing import Optional, List

    parser = argparse.ArgumentParser(description="AI Radar Latest Digest")
    parser.add_argument("--list", action="store_true", help="List all digests")
    parser.add_argument("--path", action="store_true", help="Show path to latest digest")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.list:
        digests = list_digests()
        if not digests:
            print("No digests found.")
            return

        if args.json:
            result = [{"path": str(d), "name": d.name, "size": d.stat().st_size} for d in digests]
            print(json.dumps(result, indent=2))
        else:
            print(f"Found {len(digests)} digest(s):")
            for d in digests:
                print(f"  {d.name} ({d.stat().st_size} bytes)")
        return

    if args.path:
        latest = find_latest_digest()
        if latest:
            print(str(latest))
        else:
            print("No digests found.")
        return

    # Default: show latest digest content
    latest = find_latest_digest()
    if not latest:
        print("No digests found. Run the pipeline first.")
        return

    content = latest.read_text(encoding="utf-8")
    if args.json:
        meta_path = latest.with_suffix(".json")
        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        print(json.dumps({"path": str(latest), "content": content, "metadata": meta}, indent=2, default=str))
    else:
        print(content)


if __name__ == "__main__":
    main()
