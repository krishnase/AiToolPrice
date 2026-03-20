"""
content_generator.py — AI Article Generator for AI Tool Price (aitoolprice.com)
Queries Supabase for pricing data, uses Claude API to write SEO articles,
saves them as Markdown files ready for Hugo.

Run after pipeline.py completes.
"""

import psycopg2
import anthropic
import re
import os
import json
import logging
from datetime import datetime
from pathlib import Path

from config import (
    get_connection, ANTHROPIC_API_KEY, AI_MODEL,
    MAX_TOKENS_PER_ARTICLE, MAX_TOKENS_COMPARISON, MAX_TOKENS_ROUNDUP,
    SITE_OUTPUT_DIR, SITE_BASE_URL, SITE_NAME, MAX_ARTICLES_PER_RUN
)

log    = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Database queries ───────────────────────────────────────────
def get_db():
    return get_connection()


def fetch_tool_pricing(conn, tool_ids: list) -> str:
    cur = conn.cursor()
    placeholders = ",".join(["%s"] * len(tool_ids))
    cur.execute(f"""
        SELECT t.name, t.slug, p.plan_name, p.price_monthly,
               p.price_annual, p.annual_saving_pct, p.is_free_tier, p.features
        FROM pricing_plans p
        JOIN tools t ON t.tool_id = p.tool_id
        WHERE t.tool_id IN ({placeholders})
          AND p.is_current = TRUE
        ORDER BY t.name, p.price_monthly
    """, tool_ids)

    rows = cur.fetchall()
    if not rows:
        return "No pricing data available."

    lines        = []
    current_tool = None
    for row in rows:
        name, slug, plan_name, price_monthly, price_annual, saving_pct, is_free, features = row
        if name != current_tool:
            current_tool = name
            lines.append(f"\n## {name}")
        price_str  = f"${price_monthly:.2f}/month" if price_monthly else "Free"
        annual_str = f" (${price_annual:.2f}/year, save {saving_pct:.0f}%)" if price_annual else ""
        free_tag   = " [FREE TIER]" if is_free else ""
        feat_list  = json.loads(features) if features else []
        feat_str   = ", ".join(feat_list[:4]) if feat_list else ""
        lines.append(
            f"- **{plan_name}**: {price_str}{annual_str}{free_tag}"
            + (f"\n  Features: {feat_str}" if feat_str else "")
        )
    return "\n".join(lines)


def fetch_pending_changes(conn, limit: int = 5):
    cur = conn.cursor()
    cur.execute("""
        SELECT h.history_id, h.tool_id, t.name, t.slug,
               h.plan_name, h.old_price_monthly, h.new_price_monthly,
               h.change_pct, h.change_direction, h.detected_at
        FROM pricing_history h
        JOIN tools t ON t.tool_id = h.tool_id
        WHERE h.article_generated = FALSE
          AND h.change_direction IN ('increase', 'decrease')
        ORDER BY ABS(h.change_pct) DESC
        LIMIT %s
    """, (limit,))
    return cur.fetchall()


def fetch_pending_keywords(conn, limit: int = 5):
    cur = conn.cursor()
    cur.execute("""
        SELECT keyword_id, keyword, article_type, tool_ids, search_volume
        FROM keywords
        WHERE article_generated = FALSE
        ORDER BY priority ASC, search_volume DESC
        LIMIT %s
    """, (limit,))
    return cur.fetchall()


def mark_change_done(conn, history_id: int, article_id: int):
    cur = conn.cursor()
    cur.execute("""
        UPDATE pricing_history
        SET article_generated = TRUE, article_id = %s
        WHERE history_id = %s
    """, (article_id, history_id))


def mark_keyword_done(conn, keyword_id: int, article_id: int):
    cur = conn.cursor()
    cur.execute("""
        UPDATE keywords
        SET article_generated = TRUE, article_id = %s
        WHERE keyword_id = %s
    """, (article_id, keyword_id))


def save_article(conn, title, slug, content_md, meta_desc,
                 article_type, tool_ids, keyword) -> int:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO articles
            (title, slug, content_md, meta_description, article_type,
             tool_ids, target_keyword, word_count, ai_model_used,
             is_published, created_at, last_updated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
        RETURNING article_id
    """,
    (title, slug, content_md, meta_desc[:300], article_type,
     tool_ids, keyword, len(content_md.split()), AI_MODEL))
    return cur.fetchone()[0]


# ── Markdown writer ────────────────────────────────────────────
def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")[:80]


def write_markdown(slug, title, meta_desc, content, article_type, keyword):
    output_dir = Path(SITE_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    front_matter = f"""---
title: "{title}"
date: {date_str}
lastmod: {date_str}
slug: "{slug}"
description: "{meta_desc}"
type: "{article_type}"
keywords: ["{keyword}"]
draft: false
---

"""
    filepath = output_dir / f"{slug}.md"
    filepath.write_text(front_matter + content, encoding="utf-8")
    log.info(f"  Wrote: {filepath}")


# ── Prompt templates ───────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert technology journalist and SEO writer specializing in AI tools.
Write clear, accurate, data-driven content. Always use the exact pricing data provided — never invent prices.
Format all output as clean Markdown."""


def price_change_prompt(tool_name, plan_name, old_price, new_price, change_pct, direction, pricing_data):
    action = "raised" if direction == "increase" else "lowered"
    return f"""Write a 400-500 word news article about a pricing change.

FACTS (use exactly):
- Tool: {tool_name}
- Plan: {plan_name}
- Old price: ${old_price:.2f}/month
- New price: ${new_price:.2f}/month
- Change: {change_pct:+.1f}% ({action})
- Date: {datetime.now().strftime("%B %Y")}

CURRENT PRICING for {tool_name}:
{pricing_data}

Write: H1 headline, what changed, who is affected, comparison to 1-2 competitors, bottom line recommendation.
Format as Markdown with H1 and H2 sections."""


def comparison_prompt(tool_names, keyword, pricing_data):
    return f"""Write a 600-700 word comparison article for: "{keyword}"

Tools: {" vs ".join(tool_names)}

PRICING DATA (use exact figures only):
{pricing_data}

Include: H1 with keyword, intro, Markdown comparison table, one H2 per tool, "Which should you choose?" section, 3-question FAQ, conclusion.
Tone: helpful, direct, unbiased."""


def roundup_prompt(keyword, pricing_data, tool_names):
    return f"""Write a 700-800 word roundup article for: "{keyword}"

Tools: {", ".join(tool_names)}

PRICING DATA (use exact figures only):
{pricing_data}

Include: H1, intro with criteria, H2 per tool (summary/pricing/pros/cons/best for), summary comparison table, "How to choose" section, 3-question FAQ."""


# ── Article generation ─────────────────────────────────────────
def call_claude(prompt: str, max_tokens: int = MAX_TOKENS_PER_ARTICLE) -> str:
    msg = client.messages.create(
        model=AI_MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text


def generate_price_change_article(conn, change) -> int:
    history_id, tool_id, tool_name, slug, plan_name, old_price, new_price, change_pct, direction, detected_at = change
    log.info(f"  Generating price-change article: {tool_name} {plan_name}")

    pricing_data = fetch_tool_pricing(conn, [tool_id])
    prompt       = price_change_prompt(tool_name, plan_name, old_price, new_price,
                                       change_pct, direction, pricing_data)
    content      = call_claude(prompt)

    lines  = content.strip().split("\n")
    title  = lines[0].lstrip("#").strip() if lines else f"{tool_name} Pricing Update"
    slug   = slugify(title)
    meta   = f"{tool_name} {plan_name} price changed from ${old_price:.2f} to ${new_price:.2f}/month."

    article_id = save_article(conn, title, slug, content, meta,
                              "price_change", str(tool_id),
                              f"{tool_name} pricing {datetime.now().year}")
    write_markdown(slug, title, meta, content, "price_change", f"{tool_name} pricing")
    conn.commit()
    return article_id


def generate_keyword_article(conn, kw) -> int:
    keyword_id, keyword, article_type, tool_ids_str, search_volume = kw
    log.info(f"  Generating keyword article: '{keyword}'")

    tool_id_list = [int(x.strip()) for x in tool_ids_str.split(",") if x.strip()]
    pricing_data = fetch_tool_pricing(conn, tool_id_list)

    cur = conn.cursor()
    placeholders = ",".join(["%s"] * len(tool_id_list))
    cur.execute(f"SELECT name FROM tools WHERE tool_id IN ({placeholders})", tool_id_list)
    tool_names = [r[0] for r in cur.fetchall()]

    if article_type == "comparison":
        prompt     = comparison_prompt(tool_names, keyword, pricing_data)
        max_tokens = MAX_TOKENS_COMPARISON
    else:
        prompt     = roundup_prompt(keyword, pricing_data, tool_names)
        max_tokens = MAX_TOKENS_ROUNDUP

    content = call_claude(prompt, max_tokens)

    lines  = content.strip().split("\n")
    title  = lines[0].lstrip("#").strip() if lines else keyword.title()
    slug   = slugify(title)
    meta   = f"Compare {', '.join(tool_names[:3])} pricing and features. Updated {datetime.now().strftime('%B %Y')}."

    article_id = save_article(conn, title, slug, content, meta,
                              article_type, tool_ids_str, keyword)
    write_markdown(slug, title, meta, content, article_type, keyword)
    conn.commit()
    return article_id


# ── Main runner ────────────────────────────────────────────────
def run_content_generator():
    log.info("=" * 60)
    log.info(f"Content generator started at {datetime.now().isoformat()}")
    log.info("=" * 60)

    conn               = get_db()
    articles_generated = 0

    # Priority 1: price change articles
    changes = fetch_pending_changes(conn, limit=3)
    log.info(f"Found {len(changes)} unaddressed price changes")
    for change in changes:
        if articles_generated >= MAX_ARTICLES_PER_RUN:
            break
        try:
            article_id = generate_price_change_article(conn, change)
            mark_change_done(conn, change[0], article_id)
            conn.commit()
            articles_generated += 1
        except Exception as e:
            log.error(f"Failed on price change: {e}")
            conn.rollback()

    # Priority 2: keyword articles
    keywords = fetch_pending_keywords(conn, limit=MAX_ARTICLES_PER_RUN)
    log.info(f"Found {len(keywords)} pending keyword articles")
    for kw in keywords:
        if articles_generated >= MAX_ARTICLES_PER_RUN:
            break
        try:
            article_id = generate_keyword_article(conn, kw)
            mark_keyword_done(conn, kw[0], article_id)
            conn.commit()
            articles_generated += 1
        except Exception as e:
            log.error(f"Failed on keyword '{kw[1]}': {e}")
            conn.rollback()

    conn.close()
    log.info(f"\nDone. Articles written: {articles_generated}")
    return articles_generated


if __name__ == "__main__":
    run_content_generator()