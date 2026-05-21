"""CLI: python -m scripts.ingest_url <URL> [--doc-type news]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make sibling modules importable when run as `python -m scripts.ingest_url`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from editorial.ingest import ingest_url  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a single URL into the editorial RAG store.")
    parser.add_argument("url", help="URL to ingest")
    parser.add_argument("--doc-type", default="news",
                        choices=["news", "press_conference", "technical_analysis", "other"])
    args = parser.parse_args()

    result = ingest_url(args.url, doc_type=args.doc_type)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("action") in ("inserted", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
