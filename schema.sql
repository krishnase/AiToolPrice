-- ============================================================
-- AI Tool Pricing Tracker — SQL Server Schema
-- Run once to set up your database
-- ============================================================

CREATE DATABASE AIPricingTracker;
GO

USE AIPricingTracker;
GO

-- ============================================================
-- TOOLS: master list of AI tools we track
-- ============================================================
CREATE TABLE tools (
    tool_id       INT IDENTITY(1,1) PRIMARY KEY,
    name          NVARCHAR(100)  NOT NULL,
    slug          NVARCHAR(100)  NOT NULL UNIQUE,   -- used in URLs: /tools/chatgpt
    website_url   NVARCHAR(500)  NOT NULL,
    pricing_url   NVARCHAR(500)  NOT NULL,           -- page to scrape
    category      NVARCHAR(100),                     -- 'writing', 'image', 'coding', 'chat'
    description   NVARCHAR(2000),
    logo_url      NVARCHAR(500),
    affiliate_url NVARCHAR(500),                     -- your affiliate tracking link
    affiliate_commission NVARCHAR(50),               -- e.g. '30% recurring'
    scrape_method NVARCHAR(50) DEFAULT 'html',       -- 'html', 'api', 'manual'
    is_active     BIT DEFAULT 1,
    created_at    DATETIME DEFAULT GETDATE(),
    updated_at    DATETIME DEFAULT GETDATE()
);

-- ============================================================
-- PRICING_PLANS: current pricing snapshot per tool
-- ============================================================
CREATE TABLE pricing_plans (
    plan_id        INT IDENTITY(1,1) PRIMARY KEY,
    tool_id        INT NOT NULL REFERENCES tools(tool_id),
    plan_name      NVARCHAR(100) NOT NULL,           -- 'Free', 'Pro', 'Enterprise'
    price_monthly  DECIMAL(10,2),                    -- NULL = contact sales
    price_annual   DECIMAL(10,2),                    -- annual price (often discounted)
    annual_saving_pct DECIMAL(5,2),                  -- calculated: how much you save annually
    is_free_tier   BIT DEFAULT 0,
    user_limit     INT,                              -- NULL = unlimited
    api_calls_limit INT,                             -- NULL = unlimited
    features       NVARCHAR(MAX),                    -- JSON array of key features
    is_current     BIT DEFAULT 1,                    -- 0 = outdated (superseded)
    scraped_at     DATETIME DEFAULT GETDATE(),
    CONSTRAINT uq_plan UNIQUE (tool_id, plan_name, scraped_at)
);

-- ============================================================
-- PRICING_HISTORY: every price change ever detected
-- ============================================================
CREATE TABLE pricing_history (
    history_id        INT IDENTITY(1,1) PRIMARY KEY,
    tool_id           INT NOT NULL REFERENCES tools(tool_id),
    plan_name         NVARCHAR(100) NOT NULL,
    old_price_monthly DECIMAL(10,2),
    new_price_monthly DECIMAL(10,2),
    change_amount     DECIMAL(10,2),                  -- new - old (negative = price drop)
    change_pct        DECIMAL(5,2),                   -- % change
    change_direction  NVARCHAR(10),                   -- 'increase', 'decrease', 'new_plan', 'removed'
    detected_at       DATETIME DEFAULT GETDATE(),
    article_generated BIT DEFAULT 0,                  -- has AI content been written about this?
    article_id        INT                              -- FK set after article is generated
);

-- ============================================================
-- ARTICLES: AI-generated content ready for publishing
-- ============================================================
CREATE TABLE articles (
    article_id      INT IDENTITY(1,1) PRIMARY KEY,
    title           NVARCHAR(500) NOT NULL,
    slug            NVARCHAR(500) NOT NULL UNIQUE,   -- URL slug
    content_md      NVARCHAR(MAX) NOT NULL,           -- full markdown content
    meta_description NVARCHAR(300),
    article_type    NVARCHAR(50),
        -- 'comparison'   : Tool A vs Tool B
        -- 'roundup'      : Best tools for X
        -- 'price_change' : Tool X raised/lowered prices
        -- 'review'       : Single tool deep-dive
        -- 'data_report'  : Monthly pricing trends
    tool_ids        NVARCHAR(500),                   -- comma-separated tool_ids covered
    target_keyword  NVARCHAR(300),                   -- primary SEO keyword
    word_count      INT,
    ai_model_used   NVARCHAR(100),
    is_published    BIT DEFAULT 0,
    published_at    DATETIME,
    created_at      DATETIME DEFAULT GETDATE(),
    last_updated    DATETIME DEFAULT GETDATE()
);

-- ============================================================
-- SCRAPE_LOG: track every scrape attempt (debugging)
-- ============================================================
CREATE TABLE scrape_log (
    log_id      INT IDENTITY(1,1) PRIMARY KEY,
    tool_id     INT REFERENCES tools(tool_id),
    status      NVARCHAR(20),                        -- 'success', 'failed', 'skipped'
    error_msg   NVARCHAR(2000),
    plans_found INT DEFAULT 0,
    changes_detected INT DEFAULT 0,
    duration_ms INT,
    scraped_at  DATETIME DEFAULT GETDATE()
);

-- ============================================================
-- KEYWORDS: SEO keyword targets to generate articles for
-- ============================================================
CREATE TABLE keywords (
    keyword_id     INT IDENTITY(1,1) PRIMARY KEY,
    keyword        NVARCHAR(300) NOT NULL UNIQUE,
    search_volume  INT,                               -- estimated monthly searches
    difficulty     INT,                               -- 1-100
    article_type   NVARCHAR(50),
    tool_ids       NVARCHAR(500),                    -- relevant tools
    article_generated BIT DEFAULT 0,
    article_id     INT,
    priority       INT DEFAULT 5,                    -- 1=highest, 10=lowest
    created_at     DATETIME DEFAULT GETDATE()
);

-- ============================================================
-- SEED DATA: first batch of tools to track
-- ============================================================
INSERT INTO tools (name, slug, website_url, pricing_url, category, description, scrape_method, affiliate_commission) VALUES
('ChatGPT', 'chatgpt', 'https://chat.openai.com', 'https://openai.com/chatgpt/pricing', 'chat', 'AI chat assistant by OpenAI', 'html', ''),
('Claude', 'claude', 'https://claude.ai', 'https://www.anthropic.com/pricing', 'chat', 'AI assistant by Anthropic', 'html', ''),
('Jasper AI', 'jasper', 'https://www.jasper.ai', 'https://www.jasper.ai/pricing', 'writing', 'AI writing assistant for marketing teams', 'html', '25% recurring'),
('Copy.ai', 'copyai', 'https://www.copy.ai', 'https://www.copy.ai/pricing', 'writing', 'AI copywriting tool', 'html', '30% recurring'),
('Writesonic', 'writesonic', 'https://writesonic.com', 'https://writesonic.com/pricing', 'writing', 'AI writing and SEO platform', 'html', '30% recurring'),
('Midjourney', 'midjourney', 'https://www.midjourney.com', 'https://www.midjourney.com/account', 'image', 'AI image generation', 'manual', ''),
('GitHub Copilot', 'github-copilot', 'https://github.com/features/copilot', 'https://github.com/features/copilot#pricing', 'coding', 'AI pair programmer by GitHub', 'html', ''),
('Perplexity AI', 'perplexity', 'https://www.perplexity.ai', 'https://www.perplexity.ai/pro', 'research', 'AI search and research tool', 'html', ''),
('Notion AI', 'notion-ai', 'https://www.notion.so', 'https://www.notion.so/pricing', 'productivity', 'AI features inside Notion workspace', 'html', ''),
('Grammarly', 'grammarly', 'https://www.grammarly.com', 'https://www.grammarly.com/plans', 'writing', 'AI writing and grammar assistant', 'html', '20% per sale');

-- ============================================================
-- SEED DATA: initial keyword targets
-- ============================================================
INSERT INTO keywords (keyword, search_volume, difficulty, article_type, tool_ids, priority) VALUES
('best AI writing tools 2026', 8100, 45, 'roundup', '3,4,5', 1),
('ChatGPT vs Claude pricing', 3200, 30, 'comparison', '1,2', 1),
('cheapest AI tools for students', 2400, 25, 'roundup', '1,2,4,8', 1),
('Jasper AI pricing 2026', 1900, 20, 'review', '3', 2),
('AI tools with free tier', 5600, 40, 'roundup', '1,2,4,5,8,9', 1),
('GitHub Copilot vs alternatives', 2100, 35, 'comparison', '7,2', 2),
('Writesonic vs Copy.ai', 1400, 22, 'comparison', '5,4', 2),
('best AI image generators pricing', 3800, 50, 'roundup', '6', 2),
('AI tools for marketing teams', 4200, 55, 'roundup', '3,4,5,9', 3),
('Grammarly premium worth it 2026', 6700, 38, 'review', '10', 2);

-- ============================================================
-- USEFUL VIEWS
-- ============================================================

-- Latest price for each tool/plan combination
CREATE VIEW vw_current_pricing AS
SELECT
    t.name          AS tool_name,
    t.slug,
    t.category,
    t.affiliate_url,
    p.plan_name,
    p.price_monthly,
    p.price_annual,
    p.annual_saving_pct,
    p.is_free_tier,
    p.features,
    p.scraped_at
FROM tools t
JOIN pricing_plans p ON t.tool_id = p.tool_id
WHERE p.is_current = 1
  AND t.is_active = 1;

-- Recent price changes (last 30 days)
CREATE VIEW vw_recent_changes AS
SELECT
    t.name          AS tool_name,
    t.slug,
    h.plan_name,
    h.old_price_monthly,
    h.new_price_monthly,
    h.change_pct,
    h.change_direction,
    h.detected_at,
    h.article_generated
FROM pricing_history h
JOIN tools t ON t.tool_id = h.tool_id
WHERE h.detected_at >= DATEADD(DAY, -30, GETDATE())
ORDER BY h.detected_at DESC;

GO
