"""
config.py — Central configuration for AI Pricing Tracker
Copy .env.example to .env and fill in your values.
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# ── Database (Supabase / PostgreSQL) ──────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_connection():
    """Return a live psycopg2 connection to Supabase."""
    return psycopg2.connect(DATABASE_URL)

# ── AI API ─────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Which model to use for content generation
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-4-6")

# Token limits — keep costs low
MAX_TOKENS_PER_ARTICLE = 1500
MAX_TOKENS_COMPARISON  = 2000
MAX_TOKENS_ROUNDUP     = 2500

# ── Site output ────────────────────────────────────────────────
SITE_OUTPUT_DIR = os.getenv("SITE_OUTPUT_DIR", "./site/content/articles")
SITE_BASE_URL   = os.getenv("SITE_BASE_URL",   "https://aitoolprice.com")
SITE_NAME       = os.getenv("SITE_NAME",        "AI Tool Price")

# ── Scraping ───────────────────────────────────────────────────
SCRAPE_DELAY_SECONDS = 3
REQUEST_TIMEOUT      = 15
MAX_RETRIES          = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)

# ── Pipeline behavior ──────────────────────────────────────────
PRICE_CHANGE_THRESHOLD_PCT = 5.0
MAX_ARTICLES_PER_RUN       = 15

# ── Logging ────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE  = os.getenv("LOG_FILE",  "pipeline.log")