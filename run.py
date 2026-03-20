"""
run.py — Master runner for AI Pricing Tracker
Runs the full daily cycle:
  1. Scrape pricing data → store in SQL
  2. Detect price changes → log to pricing_history
  3. Generate AI articles → write Markdown files
  4. Commit everything for deployment

Run manually:
    python run.py

Or let GitHub Actions run it via .github/workflows/daily.yml
"""

import logging
import sys
from datetime import datetime

from config import LOG_FILE, LOG_LEVEL

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)


def main():
    start = datetime.now()
    log.info("=" * 60)
    log.info(f"AI PRICING TRACKER — Daily Run — {start.strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)

    # Step 1: Data pipeline
    log.info("\n[STEP 1/2] Running data pipeline...")
    from pipeline import run_pipeline
    changes = run_pipeline()

    # Step 2: Content generation
    log.info("\n[STEP 2/2] Running content generator...")
    from content_generator import run_content_generator
    articles = run_content_generator()

    # Summary
    elapsed = (datetime.now() - start).seconds
    log.info("\n" + "=" * 60)
    log.info(f"Run complete in {elapsed}s")
    log.info(f"  Price changes detected : {changes}")
    log.info(f"  Articles generated     : {articles}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
