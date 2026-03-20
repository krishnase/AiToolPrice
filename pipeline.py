"""
pipeline.py — Data pipeline for AI Tool Price (aitoolprice.com)

Most AI pricing pages are JavaScript-rendered so simple HTML scraping
won't work. This pipeline uses a two-track approach:

  Track A — Manual seed: pricing data is inserted directly into the DB
             by the seed_prices() function below. Run once to populate.

  Track B — Live scrape: for tools whose pages are scrapeable, we attempt
             BeautifulSoup extraction with generous fallback selectors.

Run daily via: python3 run.py
"""

import psycopg2
import requests
import time
import logging
import json
import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from bs4 import BeautifulSoup

from config import (
    get_connection, SCRAPE_DELAY_SECONDS, REQUEST_TIMEOUT,
    MAX_RETRIES, USER_AGENT, PRICE_CHANGE_THRESHOLD_PCT, LOG_FILE, LOG_LEVEL
)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)


# ── Data class ─────────────────────────────────────────────────
@dataclass
class PricingPlan:
    plan_name:     str
    price_monthly: Optional[float]
    price_annual:  Optional[float] = None
    is_free_tier:  bool = False
    features:      list = field(default_factory=list)


# ── Database layer ─────────────────────────────────────────────
class Database:
    def __init__(self):
        self.conn = get_connection()
        self.conn.autocommit = False
        log.info("Connected to Supabase")

    def cursor(self): return self.conn.cursor()
    def commit(self):  self.conn.commit()
    def rollback(self): self.conn.rollback()
    def close(self):   self.conn.close()

    def get_active_tools(self):
        cur = self.cursor()
        cur.execute("""
            SELECT tool_id, name, slug, pricing_url, scrape_method
            FROM tools WHERE is_active = TRUE ORDER BY tool_id
        """)
        return cur.fetchall()

    def get_current_plans(self, tool_id: int) -> dict:
        cur = self.cursor()
        cur.execute("""
            SELECT plan_name, price_monthly FROM pricing_plans
            WHERE tool_id = %s AND is_current = TRUE
        """, (tool_id,))
        return {r[0]: r[1] for r in cur.fetchall()}

    def mark_plans_outdated(self, tool_id: int):
        self.cursor().execute("""
            UPDATE pricing_plans SET is_current = FALSE
            WHERE tool_id = %s AND is_current = TRUE
        """, (tool_id,))

    def insert_plans(self, tool_id: int, plans: list):
        cur = self.cursor()
        for p in plans:
            saving = None
            if p.price_monthly and p.price_annual:
                saving = round((1 - (p.price_annual/12) / p.price_monthly) * 100, 1)
            cur.execute("""
                INSERT INTO pricing_plans
                    (tool_id, plan_name, price_monthly, price_annual,
                     annual_saving_pct, is_free_tier, features, is_current, scraped_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE,NOW())
            """, (tool_id, p.plan_name, p.price_monthly, p.price_annual,
                  saving, p.is_free_tier, json.dumps(p.features)))

    def record_price_change(self, tool_id, plan_name, old_price, new_price):
        change = (new_price - old_price) if (old_price and new_price) else 0
        pct    = (change / old_price * 100) if old_price else 0
        if   old_price is None: direction = "new_plan"
        elif new_price is None: direction = "removed"
        elif change > 0:        direction = "increase"
        else:                   direction = "decrease"
        self.cursor().execute("""
            INSERT INTO pricing_history
                (tool_id, plan_name, old_price_monthly, new_price_monthly,
                 change_amount, change_pct, change_direction, detected_at, article_generated)
            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),FALSE)
        """, (tool_id, plan_name, old_price, new_price,
              round(change,2), round(pct,1), direction))
        log.info(f"  Price change: {plan_name} ${old_price} -> ${new_price} ({pct:+.1f}%)")

    def log_scrape(self, tool_id, status, error="",
                   plans_found=0, changes=0, duration_ms=0):
        self.cursor().execute("""
            INSERT INTO scrape_log
                (tool_id,status,error_msg,plans_found,changes_detected,duration_ms,scraped_at)
            VALUES (%s,%s,%s,%s,%s,%s,NOW())
        """, (tool_id, status, (error or "")[:2000], plans_found, changes, duration_ms))


# ── Seed data — manually verified current prices (March 2026) ──
# These are inserted once on first run. The pipeline then tracks
# any changes from this baseline going forward.
SEED_PRICES = {
    "chatgpt": [
        PricingPlan("Free",    0.00,  None,  is_free_tier=True,  features=["GPT-4o mini", "Limited GPT-4o"]),
        PricingPlan("Plus",    20.00, None,  features=["GPT-4o", "DALL-E 3", "Advanced data analysis"]),
        PricingPlan("Team",    25.00, 300.0, features=["GPT-4o", "Higher limits", "Admin console"]),
        PricingPlan("Enterprise", None, None, features=["Custom limits", "SSO", "Dedicated support"]),
    ],
    "claude": [
        PricingPlan("Free",    0.00,  None,  is_free_tier=True,  features=["Claude Sonnet", "Limited usage"]),
        PricingPlan("Pro",     20.00, None,  features=["Claude Opus", "5x more usage", "Priority access"]),
        PricingPlan("Team",    25.00, None,  features=["Claude Opus", "Team admin", "Higher limits"]),
    ],
    "jasper": [
        PricingPlan("Creator", 49.00, 468.0, features=["1 seat", "50+ templates", "Browser extension"]),
        PricingPlan("Teams",   125.0, 1188.0,features=["3 seats", "Collaboration", "Brand voice"]),
        PricingPlan("Business",None,  None,  features=["Custom seats", "API access", "SSO"]),
    ],
    "copyai": [
        PricingPlan("Free",    0.00,  None,  is_free_tier=True,  features=["2,000 words/mo", "90+ tools"]),
        PricingPlan("Pro",     49.00, 432.0, features=["Unlimited words", "Priority support"]),
        PricingPlan("Team",    249.0, 2388.0,features=["5 seats", "Workflows", "API access"]),
    ],
    "writesonic": [
        PricingPlan("Free",    0.00,  None,  is_free_tier=True,  features=["10k words/mo"]),
        PricingPlan("Individual", 20.0, 192.0, features=["Unlimited words", "GPT-4"]),
        PricingPlan("Teams",   30.00, 288.0, features=["3 seats", "Custom AI voices"]),
    ],
    "midjourney": [
        PricingPlan("Basic",   10.00, 96.0,  features=["200 images/mo", "3.3 GPU hrs"]),
        PricingPlan("Standard",30.00, 288.0, features=["15 GPU hrs/mo", "Relax mode"]),
        PricingPlan("Pro",     60.00, 576.0, features=["30 GPU hrs/mo", "Stealth mode"]),
        PricingPlan("Mega",    120.0, 1152.0,features=["60 GPU hrs/mo", "Stealth mode"]),
    ],
    "github-copilot": [
        PricingPlan("Free",    0.00,  None,  is_free_tier=True,  features=["2000 completions/mo"]),
        PricingPlan("Individual", 10.0, 100.0, features=["Unlimited completions", "Chat"]),
        PricingPlan("Business",19.00, 228.0, features=["Policy management", "Audit logs"]),
        PricingPlan("Enterprise",39.0, 468.0, features=["Custom models", "Advanced security"]),
    ],
    "perplexity": [
        PricingPlan("Free",    0.00,  None,  is_free_tier=True,  features=["Unlimited searches", "GPT-4o mini"]),
        PricingPlan("Pro",     20.00, 200.0, features=["300 Pro searches/day", "Claude/GPT-4o"]),
    ],
    "notion-ai": [
        PricingPlan("Free",    0.00,  None,  is_free_tier=True,  features=["Limited AI responses"]),
        PricingPlan("Plus",    10.00, 96.0,  features=["Unlimited AI", "Unlimited pages"]),
        PricingPlan("Business",15.00, 144.0, features=["Advanced permissions", "Audit log"]),
        PricingPlan("AI add-on",8.00, 96.0,  features=["AI on any plan"]),
    ],
    "grammarly": [
        PricingPlan("Free",    0.00,  None,  is_free_tier=True,  features=["Basic corrections"]),
        PricingPlan("Premium", 30.00, 144.0, features=["Full rewrites", "Plagiarism check"]),
        PricingPlan("Business",15.00, 180.0, features=["Per member", "Style guide", "Analytics"]),
    ],
}


def seed_prices_if_empty(db: Database):
    """Insert manually verified pricing on first run if DB has no plans yet."""
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM pricing_plans")
    count = cur.fetchone()[0]
    if count > 0:
        log.info(f"Pricing plans already seeded ({count} rows) — skipping seed")
        return

    log.info("Seeding initial pricing data from verified manual data...")
    cur.execute("SELECT tool_id, slug FROM tools WHERE is_active = TRUE")
    tools = {row[1]: row[0] for row in cur.fetchall()}

    for slug, plans in SEED_PRICES.items():
        tool_id = tools.get(slug)
        if not tool_id:
            log.warning(f"  Tool slug '{slug}' not found in DB — skipping")
            continue
        db.insert_plans(tool_id, plans)
        log.info(f"  Seeded {len(plans)} plans for {slug}")

    db.commit()
    log.info("Seed complete.")


# ── Generic HTML scraper ────────────────────────────────────────
class GenericScraper:
    """
    Best-effort HTML scraper using broad selectors.
    Works for simple pricing pages. JS-heavy pages return empty
    and fall back to keeping the existing DB data unchanged.
    """
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def fetch_html(self, url: str) -> Optional[str]:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = self.session.get(url, timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
                return r.text
            except requests.RequestException as e:
                log.warning(f"  Attempt {attempt} failed: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(SCRAPE_DELAY_SECONDS * attempt)
        return None

    @staticmethod
    def parse_price(text: str) -> Optional[float]:
        if not text: return None
        text = text.lower().strip()
        if any(w in text for w in ["free","contact","custom","enterprise","talk"]): return None
        m = re.search(r"\$\s*([\d,]+\.?\d*)", text)
        return float(m.group(1).replace(",","")) if m else None

    def scrape(self, url: str) -> list:
        html = self.fetch_html(url)
        if not html: return []
        soup  = BeautifulSoup(html, "html.parser")
        plans = []

        # Try common pricing card selectors across many sites
        card_selectors = [
            "[class*='pricing-card']", "[class*='PricingCard']",
            "[class*='price-card']",   "[class*='plan-card']",
            "[class*='pricing-tier']", "[class*='PricingTier']",
            "[class*='pricing-plan']", "[data-testid*='pricing']",
        ]
        cards = []
        for sel in card_selectors:
            cards = soup.select(sel)
            if cards: break

        for card in cards:
            name_el  = card.select_one(
                "h2, h3, h4, [class*='plan-name'], [class*='tier-name'], "
                "[class*='title'], [class*='Name']"
            )
            price_el = card.select_one(
                "[class*='price']:not([class*='original']), "
                "[class*='amount'], [class*='cost'], "
                "[class*='monthly'], [class*='per-month']"
            )
            if not name_el: continue

            name  = name_el.get_text(strip=True)
            price = self.parse_price(price_el.get_text(strip=True) if price_el else "")
            feats = [li.get_text(strip=True) for li in card.select("li")[:5]]

            if name and len(name) < 50:
                plans.append(PricingPlan(
                    plan_name=name, price_monthly=price, price_annual=None,
                    is_free_tier=("free" in name.lower() or price == 0),
                    features=feats
                ))

        return plans


class ManualScraper(GenericScraper):
    """For JS-only pages — skip scraping, keep existing DB data."""
    def scrape(self, url: str) -> list:
        log.info(f"  Manual tool — keeping existing DB prices")
        return []


def get_scraper(method: str) -> GenericScraper:
    return ManualScraper() if method == "manual" else GenericScraper()


# ── Change detector ────────────────────────────────────────────
def detect_changes(db, tool_id, old_plans, new_plans) -> int:
    changes = 0
    new_map = {p.plan_name: p.price_monthly for p in new_plans}

    for name, old_price in old_plans.items():
        new_price = new_map.get(name)
        if name not in new_map:
            db.record_price_change(tool_id, name, old_price, None)
            changes += 1
            continue
        if old_price and new_price:
            pct = abs((new_price - old_price) / old_price * 100)
            if pct >= PRICE_CHANGE_THRESHOLD_PCT:
                db.record_price_change(tool_id, name, old_price, new_price)
                changes += 1

    for name, new_price in new_map.items():
        if name not in old_plans:
            db.record_price_change(tool_id, name, None, new_price)
            changes += 1

    return changes


# ── Main pipeline ──────────────────────────────────────────────
def run_pipeline():
    log.info("=" * 60)
    log.info(f"Pipeline started at {datetime.now().isoformat()}")
    log.info("=" * 60)

    db = Database()

    # First run: seed verified pricing data if DB is empty
    seed_prices_if_empty(db)

    tools         = db.get_active_tools()
    total_changes = 0
    log.info(f"Checking {len(tools)} tools for price changes...")

    for tool in tools:
        tool_id, name, slug, url, method = tool
        log.info(f"\nChecking: {name}")
        start = int(time.time() * 1000)

        try:
            old_plans = db.get_current_plans(tool_id)
            scraper   = get_scraper(method)
            new_plans = scraper.scrape(url)

            # If scraper returned nothing (JS page), keep existing data — no update
            if not new_plans:
                log.info(f"  No scraped data — keeping existing {len(old_plans)} plans in DB")
                db.log_scrape(tool_id, "skipped", "js-rendered or no plans found")
                db.commit()
                time.sleep(SCRAPE_DELAY_SECONDS)
                continue

            changes = detect_changes(db, tool_id, old_plans, new_plans)
            total_changes += changes
            db.mark_plans_outdated(tool_id)
            db.insert_plans(tool_id, new_plans)
            db.log_scrape(tool_id, "success", plans_found=len(new_plans),
                          changes=changes, duration_ms=int(time.time()*1000)-start)
            db.commit()
            log.info(f"  Updated {len(new_plans)} plans, {changes} change(s) detected")

        except Exception as e:
            db.rollback()
            log.error(f"  Error: {e}", exc_info=True)
            db.log_scrape(tool_id, "failed", str(e))
            db.commit()

        time.sleep(SCRAPE_DELAY_SECONDS)

    db.close()
    log.info(f"\nPipeline complete. Total changes: {total_changes}")
    return total_changes


if __name__ == "__main__":
    run_pipeline()