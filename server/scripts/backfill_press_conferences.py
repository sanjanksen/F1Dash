"""One-off backfill of FIA press-conference transcripts for past seasons.

NOT part of the 2-hour editorial cron (which stays current-year only). Run
manually when you want to ingest historical seasons:

    cd server && PYTHONPATH=. python -m scripts.backfill_press_conferences 2024 2025

Defaults to 2024 + 2025 if no years are given. Idempotent — already-ingested
transcripts are skipped without a fetch. Embeddings are cheap (~$0 on the free
tier, rate-limited) and the run is resumable: re-running just fills any gaps.
"""
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=str(Path(__file__).resolve().parent.parent.parent / ".env"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from editorial.press_conference_poller import backfill_seasons  # noqa: E402


def main() -> None:
    years = [int(a) for a in sys.argv[1:]] or [2024, 2025]
    print(f"Backfilling FIA press-conference transcripts for seasons: {years}")
    out = backfill_seasons(years)
    print("\n=== DONE ===")
    print(
        f"total: +{out['new_articles']} new | {out['skipped']} skipped | {out['errors']} errors"
    )
    for year, counts in out["by_year"].items():
        print(
            f"  {year}: +{counts['new_articles']} new, "
            f"{counts['skipped']} skipped, {counts['errors']} errors"
        )


if __name__ == "__main__":
    main()
