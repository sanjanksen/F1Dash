"""CLI: python -m scripts.ingest_fia_pdf <PDF_URL>"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(dotenv_path=str(Path(__file__).resolve().parent.parent.parent / ".env"))

from editorial.ingest import ingest_fia_pdf  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a FIA scrutineering PDF into the editorial RAG store.")
    parser.add_argument("url", help="FIA PDF URL")
    args = parser.parse_args()

    result = ingest_fia_pdf(args.url)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("action") in ("inserted", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
