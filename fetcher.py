import json
import os
from datetime import datetime
from urllib.parse import urlparse

import feedparser
import openai
import requests

client = openai.OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY", "sk-32dbfe5d56e240c3a53e4bbecc44843a"),
    base_url="https://api.deepseek.com",
)

SECTIONS = [
    "AI & Tech Frontier",
    "Product & Builder",
    "Startup & VC",
    "Global Tech",
    "Deep Read",
]

RSS_FEEDS = {
    "AI & Tech Frontier": [
        "https://www.theverge.com/rss/index.xml",
        "https://techcrunch.com/feed/",
        "https://importai.substack.com/feed",
        "https://www.therundown.ai/feed",
        "https://feeds.feedburner.com/oreilly/radar",
    ],
    "Product & Builder": [
        "https://www.lennysnewsletter.com/feed",
        "https://www.latent.space/feed",
        "https://www.aitidbits.ai/feed",
        "https://www.exponentialview.co/feed",
        "https://www.interconnects.ai/feed",
        "https://tldr.tech/api/rss/founders",
        "https://newsletter.pragmaticengineer.com/feed",
        "https://blog.superhuman.com/rss/",
        "https://www.intercom.com/blog/feed/",
        "https://www.svpg.com/feed/",
        "https://www.departmentofproduct.com/feed/",
    ],
    "Startup & VC": [
        "https://a16z.com/feed/",
        "https://bothsidesofthetable.com/feed",
        "https://news.ycombinator.com/rss",
        "https://pitchbook.com/news/rss",
        "https://www.producthunt.com/feed",
        "https://hnrss.org/frontpage",
    ],
    "Global Tech": [
        "https://technode.com/feed/",
        "https://kr-asia.com/feed",
        "https://www.techinasia.com/feed",
        "https://asia.nikkei.com/rss/feed/nar",
    ],
    "Deep Read": [
        "https://stratechery.com/feed/",
        "https://every.to/feed",
        "https://www.ben-evans.com/benedictevans/rss.xml",
        "https://www.lennysnewsletter.com/feed",
    ],
}

NEWSAPI_URL = "https://newsapi.org/v2/everything"
DEFAULT_NEWS_API_KEY = "7fa95189dff94e56896a65fa423a2d68"
RSS_TIMEOUT = 5
NEWSAPI_TIMEOUT = 10
MAX_ITEMS_PER_SECTION = 5
FALLBACK_MIN_ITEMS = 3

# Per-section item counts — Deep Read gets exactly 1 long-form piece
ITEMS_PER_SECTION = {
    "AI & Tech Frontier": 5,
    "Product & Builder": 5,
    "Startup & VC": 5,
    "Global Tech": 5,
    "Deep Read": 1,
}

# Section-specific editorial focus for ranking
SECTION_FOCUS = {
    "AI & Tech Frontier": """INCLUDE: AI model releases, capability breakthroughs, AI research papers with real-world impact, major AI infrastructure updates, big tech AI strategy moves (Google, OpenAI, Anthropic, Meta, Microsoft).
EXCLUDE: general tech news unrelated to AI, opinion pieces without factual basis, crypto/blockchain unless directly AI-related.""",
    "Product & Builder": """INCLUDE: major product launches, significant product updates or feature releases, product pivots, PMF stories with data, consumer app milestones (user growth, revenue), B2B SaaS major releases.
EXCLUDE: minor bug fixes, incremental updates, marketing campaigns, general business news, anything without a concrete product change.""",
    "Startup & VC": """INCLUDE: funding rounds (Series A and above, or notable pre-seed/seed in AI), acquisitions, mergers, IPOs, notable investor memos or theses, startup shutdowns with lessons, VC fund announcements.
EXCLUDE: general business news, stock market updates, crypto fundraising, real estate, anything not directly about startup financing or M&A activity.""",
    "Global Tech": """INCLUDE: major strategy moves from global tech giants (Google, Apple, Microsoft, Meta, Amazon, ByteDance, Tencent, Samsung, SoftBank), international market expansion, global regulatory changes affecting tech (EU AI Act, US export controls), cross-border acquisitions, global platform updates with significant user impact, emerging tech markets outside US.
EXCLUDE: US-only domestic tech news (covered in AI section), general business news without tech angle, manufacturing and supply chain unless directly product-related, politics without direct tech impact.""",
    "Deep Read": """INCLUDE: ONE long-form analysis (5+ min read), strategic frameworks for builders or founders, founder/investor essays with original insight, market thesis pieces from credible sources (Stratechery, Every.to, a16z, First Round Review). Include at least 2-3 insights.
EXCLUDE: news articles, anything under 3 min read, listicles, how-to tutorials, anything without original strategic thinking.""",
}

RANKING_RULES = """GLOBAL RULES (apply to all sections):
- Never select duplicate coverage of the same event — pick the most original source, not aggregators
- Prioritize articles published on the selected date
- News with concrete data over opinion pieces
- First reports over follow-up coverage
- Builder/founder-relevant insights over general tech news

Signal over Noise scoring:
+3  Directly impacts AI product decisions or startup direction
+2  Big tech strategic move (launch/acquisition/layoff)
+2  Funding/market signal (Series A+ round, or clear trend)
+1  Data-backed product/growth case study
-1  Opinion/prediction piece without factual basis
-2  Duplicate coverage of same event
-2  PR piece / sponsored content
-3  Entertainment / non-industry content"""


def _normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed._replace(fragment="").geturl()
    except Exception:
        return url


def _source_name_from_url(url: str) -> str:
    try:
        host = urlparse(url).hostname
        return host.replace("www.", "") if host else ""
    except Exception:
        return ""


def _short_summary(text: str) -> str:
    if not text:
        return ""
    summary = " ".join(text.split())
    return summary if len(summary) <= 240 else summary[:237].rstrip() + "..."


def _parse_rss_feed(url: str) -> list[dict]:
    try:
        response = requests.get(url, timeout=RSS_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        if getattr(feed, "bozo", False) and getattr(feed, "bozo_exception", None):
            return []

        items = []
        for entry in getattr(feed, "entries", []):
            link = entry.get("link") or entry.get("id") or ""
            if not link:
                continue
            title = (entry.get("title") or "").strip()
            summary = _short_summary(entry.get("summary", entry.get("description", "")))
            # Extract actual publication date
            pub_date = None
            for date_field in ("published_parsed", "updated_parsed"):
                parsed = entry.get(date_field)
                if parsed:
                    try:
                        from time import mktime
                        pub_date = datetime.fromtimestamp(mktime(parsed)).strftime("%Y-%m-%d")
                        break
                    except Exception:
                        pass
            if not pub_date:
                for date_field in ("published", "updated"):
                    raw = entry.get(date_field)
                    if raw:
                        try:
                            from email.utils import parsedate_to_datetime
                            pub_date = parsedate_to_datetime(raw).strftime("%Y-%m-%d")
                            break
                        except Exception:
                            try:
                                pub_date = datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
                                break
                            except Exception:
                                pass
            items.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": link,
                    "source_name": (entry.get("source", {}).get("title") or _source_name_from_url(link)),
                    "pub_date": pub_date,
                }
            )
        return items
    except requests.RequestException:
        return []
    except Exception:
        return []


def _newsapi_query(section: str) -> str:
    if section == "AI & Tech Frontier":
        return "artificial intelligence OR technology OR AI frontier"
    if section == "Product & Builder":
        return "product management OR startup building OR product development"
    if section == "Startup & VC":
        return "startups OR venture capital OR entrepreneurship"
    if section == "Global Tech":
        return "global technology OR Asia tech OR international tech"
    if section == "Deep Read":
        return "tech analysis OR deep tech insights OR industry trends"
    return "technology"


def generate_summary(title: str, summary: str) -> tuple[str, str, str]:
    if not client:
        return summary or title, "", "mid"
    prompt = f"""You are a news curator for an AI PM preparing to start an AI company in the US.

Article title: {title}
Article summary: {summary}

Write three fields:

1. "what" — 2-3 factual sentences summarizing the key news. Include specific names, numbers, data points, and key details. Be informative and precise. No opinions.

2. "so_what" — 2-3 sentences on why this matters for an AI founder. Be concrete about strategic implications: market timing, competitive dynamics, regulatory risk, distribution, funding climate, or technical moats. Connect the dots for the reader.

3. "impact" — Rate as "high", "mid", or "low" using this scoring:
   HIGH (+3): Major AI model release, big tech acquisition/pivot, $50M+ funding, regulatory shift
   HIGH (+2): Big tech strategic move, $10M+ funding round, clear market trend signal
   MID (+1): Data-backed product/growth case study, useful builder insight
   LOW (-1 or below): Opinion/prediction without data, minor update, tangential news

Return ONLY valid JSON: {{"what": "...", "so_what": "...", "impact": "high|mid|low"}}
No markdown, no code fences."""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if result.startswith("```"):
            result = result.split("\n", 1)[-1]
            result = result.rsplit("```", 1)[0].strip()
        data = json.loads(result)
        what = data.get("what") or summary or title
        so_what = data.get("so_what") or ""
        impact = data.get("impact", "mid").lower()
        if impact not in ("high", "mid", "low"):
            impact = "mid"
        return what, so_what, impact
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        try:
            start = result.index("{")
            end = result.rindex("}") + 1
            data = json.loads(result[start:end])
            impact = data.get("impact", "mid").lower()
            if impact not in ("high", "mid", "low"):
                impact = "mid"
            return data.get("what", summary or title), data.get("so_what", ""), impact
        except (ValueError, json.JSONDecodeError):
            print(f"Failed to parse summary JSON: {result[:200]}")
            return summary or title, "", "mid"
    except Exception as e:
        print(f"Error generating summary: {e}")
        return summary or title, "", "mid"


def _fetch_newsapi_fallback(section: str) -> list[dict]:
    api_key = os.getenv("NEWS_API_KEY", DEFAULT_NEWS_API_KEY)
    query = _newsapi_query(section)
    if not api_key or not query:
        return []

    try:
        response = requests.get(
            NEWSAPI_URL,
            params={
                "q": query,
                "pageSize": 10,
                "language": "en",
                "sortBy": "publishedAt",
                "apiKey": api_key,
            },
            timeout=NEWSAPI_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "ok":
            return []

        items = []
        for article in payload.get("articles", []):
            url = article.get("url")
            if not url:
                continue
            title = (article.get("title") or "").strip()
            summary = _short_summary(article.get("description") or article.get("content", ""))
            items.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "source_name": (article.get("source", {}).get("name") or _source_name_from_url(url)),
                }
            )
        return items
    except requests.RequestException:
        return []
    except ValueError:
        return []


def _dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    filtered = []
    for item in items:
        url = _normalize_url(item.get("url", ""))
        if not url or url in seen:
            continue
        seen.add(url)
        filtered.append(item)
    return filtered


def _title_words(title: str) -> set[str]:
    """Extract significant words from a title for similarity comparison."""
    stop = {"the","a","an","is","are","was","were","in","on","at","to","for","of","and","or","with","its","by","from","as","has","have","had","will","be","been","this","that","it"}
    words = set()
    for w in title.lower().split():
        w = w.strip(".,!?:;\"'—–-()[]")
        if len(w) > 2 and w not in stop:
            words.add(w)
    return words


def _dedupe_same_event(items: list[dict]) -> list[dict]:
    """Remove articles covering the same event (high title word overlap)."""
    result = []
    for item in items:
        words = _title_words(item.get("title", ""))
        is_dupe = False
        for kept in result:
            kept_words = _title_words(kept.get("title", ""))
            if not words or not kept_words:
                continue
            overlap = len(words & kept_words)
            smaller = min(len(words), len(kept_words))
            if smaller > 0 and overlap / smaller >= 0.5:
                is_dupe = True
                break
        if not is_dupe:
            result.append(item)
    return result


def _rank_and_select(section: str, items: list[dict], n: int = MAX_ITEMS_PER_SECTION) -> list[dict]:
    """Use DeepSeek to pick the top N most newsworthy articles from a candidate pool, ensuring source diversity."""
    if not client or len(items) <= n:
        return items[:n]

    # Step 1: Group candidates by source
    from collections import OrderedDict
    by_source = OrderedDict()
    for idx, item in enumerate(items):
        src = item.get("source_name", "unknown")
        by_source.setdefault(src, []).append(idx)

    # Step 2: Pre-select one candidate per source (round-robin) to guarantee diversity
    guaranteed = []
    for src, indices in by_source.items():
        if len(guaranteed) < n:
            guaranteed.append(indices[0])
    # Fill remaining slots from all items not yet selected
    remaining_slots = n - len(guaranteed)

    if remaining_slots <= 0:
        # More sources than slots — ask AI to pick which sources matter most
        candidates = []
        for idx in guaranteed:
            item = items[idx]
            candidates.append(f"{idx}. [{item.get('source_name','')}] {item['title']}\n   {item.get('summary','')[:120]}")

        section_focus = SECTION_FOCUS.get(section, "")
        prompt = f"""You are a news curator for an AI PM preparing to start an AI company in the US.
Curating the "{section}" section. {section_focus}

{RANKING_RULES}

Pick the {n} highest-signal articles from these candidates:

{chr(10).join(candidates)}

Return ONLY a JSON object like {{"selected": [0, 3, 7, 12, 4]}} with the indices of your picks, ranked by importance.
No explanation, no markdown."""

        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content.strip())
            indices = data.get("selected", list(data.values())[0]) if isinstance(data, dict) else data
            indices = [i for i in indices if isinstance(i, int) and i in guaranteed]
            if len(indices) >= n:
                return [items[i] for i in indices[:n]]
        except Exception as e:
            print(f"Ranking failed for {section}: {e}")

        return [items[i] for i in guaranteed[:n]]

    # Step 3: For remaining slots, ask AI to pick the best from ALL other candidates
    other_pool = [idx for idx in range(len(items)) if idx not in guaranteed]
    all_for_ranking = guaranteed + other_pool

    candidates = []
    for idx in all_for_ranking:
        item = items[idx]
        tag = "[GUARANTEED] " if idx in guaranteed else ""
        candidates.append(f"{idx}. {tag}[{item.get('source_name','')}] {item['title']}\n   {item.get('summary','')[:120]}")

    section_focus = SECTION_FOCUS.get(section, "")
    prompt = f"""You are a news curator for an AI PM preparing to start an AI company in the US.
Curating the "{section}" section. {section_focus}

{RANKING_RULES}

You must include the {len(guaranteed)} GUARANTEED articles (one per source for diversity).
Pick {remaining_slots} more articles from the remaining candidates to fill {n} total slots.

Candidates:
{chr(10).join(candidates)}

Return ONLY a JSON object like {{"selected": [0, 3, 7, 12, 4]}} — exactly {n} indices total (guaranteed + your picks), ranked by importance.
No explanation, no markdown."""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content.strip())
        indices = data.get("selected", list(data.values())[0]) if isinstance(data, dict) else data
        indices = [i for i in indices if isinstance(i, int) and 0 <= i < len(items)]
        # Ensure guaranteed items are included
        for g in guaranteed:
            if g not in indices:
                indices.insert(0, g)
        # Dedupe while preserving order
        seen = set()
        unique = []
        for i in indices:
            if i not in seen:
                seen.add(i)
                unique.append(i)
        if len(unique) >= n:
            return [items[i] for i in unique[:n]]
    except Exception as e:
        print(f"Ranking failed for {section}, using diverse fallback: {e}")

    # Fallback: guaranteed + first from remaining pool
    fallback = guaranteed + other_pool
    return [items[i] for i in fallback[:n]]


def _source_diverse_pick(items: list[dict], n: int) -> list[dict]:
    """Pick n items round-robin across different sources."""
    from collections import OrderedDict
    by_source = OrderedDict()
    for item in items:
        src = item.get("source_name", "unknown")
        by_source.setdefault(src, []).append(item)

    selected = []
    source_lists = list(by_source.values())
    idx = 0
    while len(selected) < n and source_lists:
        bucket = source_lists[idx % len(source_lists)]
        if bucket:
            selected.append(bucket.pop(0))
            if not bucket:
                source_lists.remove(bucket)
        idx += 1
    return selected


def fetch_section_rss_items(section: str, target_date: str | None = None) -> list[dict]:
    # Fetch from ALL RSS feeds for this section
    all_items = []
    for url in RSS_FEEDS.get(section, []):
        all_items.extend(_parse_rss_feed(url))

    all_items = _dedupe_items(all_items)

    # Filter to only articles published on the target date
    if target_date is None:
        from datetime import date as _date
        target_date = _date.today().isoformat()
    today_items = [item for item in all_items if item.get("pub_date") == target_date]

    # If too few articles from today, include recent days (up to 7 for weekly newsletters)
    if len(today_items) < MAX_ITEMS_PER_SECTION:
        from datetime import date as _date, timedelta
        td = _date.fromisoformat(target_date)
        recent_dates = {(td - timedelta(days=i)).isoformat() for i in range(8)}
        today_items = [item for item in all_items if item.get("pub_date") in recent_dates]

    # Last resort: use all available items regardless of date
    if len(today_items) < MAX_ITEMS_PER_SECTION:
        today_items = all_items

    # Fallback to NewsAPI if not enough items
    if len(today_items) < FALLBACK_MIN_ITEMS:
        today_items.extend(_fetch_newsapi_fallback(section))
        today_items = _dedupe_items(today_items)

    # AI-rank and select the top items from the filtered pool
    final_items = _rank_and_select(section, today_items)

    # Ensure we always return exactly MAX_ITEMS_PER_SECTION items
    if len(final_items) < MAX_ITEMS_PER_SECTION:
        used_urls = {item["url"] for item in final_items}
        # Pad from today_items first, then all_items
        for pool in (today_items, all_items):
            for item in pool:
                if item["url"] not in used_urls:
                    final_items.append(item)
                    used_urls.add(item["url"])
                if len(final_items) >= MAX_ITEMS_PER_SECTION:
                    break
            if len(final_items) >= MAX_ITEMS_PER_SECTION:
                break

    # Generate AI summaries only for the final selected items
    for item in final_items:
        what, so_what, impact = generate_summary(item["title"], item["summary"])
        item["what"] = what
        item["so_what"] = so_what
        item["impact"] = impact

    return final_items


def _classify_articles(items: list[dict]) -> dict[str, list[dict]]:
    """Use AI to classify articles into the best-fit section."""
    if not client or not items:
        # Fallback: round-robin into sections
        result = {s: [] for s in SECTIONS}
        for i, item in enumerate(items):
            result[SECTIONS[i % len(SECTIONS)]].append(item)
        return result

    section_descriptions = "\n".join(f"- {s}: {SECTION_FOCUS[s]}" for s in SECTIONS)
    candidates = []
    for i, item in enumerate(items):
        candidates.append(f"{i}. [{item.get('source_name','')}] {item['title']}\n   {item.get('summary','')[:120]}")

    prompt = f"""You are a senior news editor classifying articles into sections for an AI PM newsletter.

SECTION RULES:
{section_descriptions}

{RANKING_RULES}

ITEM COUNTS PER SECTION:
- AI & Tech Frontier: 5 articles
- Product & Builder: 5 articles
- Startup & VC: 5 articles
- Global Tech: 5 articles
- Deep Read: 1 article (ONE long-form analysis only)

CRITICAL RULES:
- Each article can appear in ONLY ONE section — NO duplicates across sections
- An article about the same event/topic can only appear once, even if worded differently
- Follow the INCLUDE/EXCLUDE rules strictly for each section
- Never select duplicate coverage of the same event — pick the most original source
- For Deep Read: pick exactly 1 article that is a long-form analysis (5+ min read), NOT a news article

COMMON MISCLASSIFICATIONS TO AVOID:
- AI research, model distillation, AI safety debates → "AI & Tech Frontier", NOT "Startup & VC"
- US court cases about AI companies (OpenAI, Google) → "AI & Tech Frontier", NOT "Global Tech"
- General AI industry news → "AI & Tech Frontier", NOT "Product & Builder"
- "Global Tech" is for NON-US international tech news only (Asia, Europe, cross-border)
- "Startup & VC" is ONLY for funding rounds (Series A+), M&A, IPOs, investor memos — NOT product launches, NOT AI trends, NOT app growth stories, NOT criminal cases, NOT data privacy scandals, NOT earnings reports
- A new app/platform launching → "Product & Builder", NOT "Startup & VC" (unless the article is specifically about its funding round)
- AI model benchmarks, AI-driven growth trends → "AI & Tech Frontier", NOT "Startup & VC"
- "Product & Builder" requires a CONCRETE product launch, update, or pivot — NOT opinion pieces, NOT "I'm worried about X", NOT commentary without a specific product change
- Opinion pieces, developer commentary, or concern posts without a concrete product change → DO NOT put in "Product & Builder"
- Criminal cases, espionage, lawsuits, data privacy violations → NOT "Startup & VC" (put in relevant section or skip)
- US company CEO interviews about AI strategy → "AI & Tech Frontier", NOT "Global Tech"
- Earnings reports → NOT "Deep Read". Deep Read must be a long-form strategic essay/analysis (5+ min), NOT earnings recaps, NOT news summaries
- If no good long-form analysis exists in the pool, pick the MOST analytical/strategic piece available

Articles:
{chr(10).join(candidates)}

Return ONLY a JSON object mapping section names to arrays of article indices.
Deep Read MUST have exactly 1 index. Other sections should have 5 indices each.
No article index can appear in more than one section.
{{{{
  "AI & Tech Frontier": [0, 3, 7, 12, 4],
  "Product & Builder": [1, 5, 8, 15, 20],
  "Startup & VC": [2, 6, 9, 14, 18],
  "Global Tech": [10, 11, 13, 16, 19],
  "Deep Read": [17]
}}}}
No explanation, no markdown."""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content.strip())
        result = {s: [] for s in SECTIONS}
        used = set()
        for section in SECTIONS:
            indices = data.get(section, [])
            section_limit = ITEMS_PER_SECTION.get(section, MAX_ITEMS_PER_SECTION)
            for idx in indices:
                if isinstance(idx, int) and 0 <= idx < len(items) and idx not in used:
                    if len(result[section]) < section_limit:
                        result[section].append(items[idx])
                        used.add(idx)

        # Pad any section that got fewer than its target (except Deep Read)
        unused = [i for i in range(len(items)) if i not in used]
        for section in SECTIONS:
            section_limit = ITEMS_PER_SECTION.get(section, MAX_ITEMS_PER_SECTION)
            while len(result[section]) < section_limit and unused:
                result[section].append(items[unused.pop(0)])

        return result
    except Exception as e:
        print(f"Classification failed, using per-section fallback: {e}")
        # Fallback: round-robin
        result = {s: [] for s in SECTIONS}
        for i, item in enumerate(items):
            result[SECTIONS[i % len(SECTIONS)]].append(item)
        return result


TRANSLATE_PROMPT = """你是一位资深科技媒体编辑和AI翻译专家，负责将英文科技简报翻译成地道的中文。你的翻译质量应该媲美人工翻译，绝不能有AI机翻的痕迹。

要求：
- 用自然流畅的中文表达，像36氪、晚点LatePost的资深编辑写的一样
- 严禁生硬的机翻感，不要逐字翻译，要理解语境后重新用中文表达
- 句式要符合中文习惯，避免英文语序（如被动句、从句嵌套）
- 专业术语保留英文或用业内通用译法（如 AI、PM、SaaS、GPT）
- 语气简洁有力，像在跟同行聊天，有洞察力
- 每段翻译之间用 --- 分隔，保持原文顺序
- 翻译后自查：如果读起来像机器翻译的，重新翻译

以下是需要翻译的内容：

"""


def translate_batch(texts: list[str]) -> list[str]:
    """Translate a list of English texts to Chinese using DeepSeek."""
    if not client or not texts:
        return texts
    non_empty = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
    if not non_empty:
        return texts
    try:
        combined = "\n---\n".join(t for _, t in non_empty)
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": TRANSLATE_PROMPT + combined}],
        )
        parts = response.choices[0].message.content.strip().split("---")
        translations = [p.strip() for p in parts]
        result = list(texts)
        for j, (orig_idx, _) in enumerate(non_empty):
            result[orig_idx] = translations[j] if j < len(translations) else texts[orig_idx]
        return result
    except Exception as e:
        print(f"Translation failed: {e}")
        return texts


def fetch_all_sections() -> dict[str, list[dict]]:
    from datetime import date as _date, timedelta

    # Step 1: Merge ALL RSS feeds from all sections into one pool
    all_urls = set()
    for urls in RSS_FEEDS.values():
        all_urls.update(urls)

    all_items = []
    for url in all_urls:
        all_items.extend(_parse_rss_feed(url))
    all_items = _dedupe_items(all_items)

    # Step 2: Filter by date (today, then 7-day window, then all)
    target_date = _date.today().isoformat()
    today_items = [item for item in all_items if item.get("pub_date") == target_date]

    target_count = sum(ITEMS_PER_SECTION.values())  # 21 articles total

    if len(today_items) < target_count:
        td = _date.fromisoformat(target_date)
        recent_dates = {(td - timedelta(days=i)).isoformat() for i in range(8)}
        today_items = [item for item in all_items if item.get("pub_date") in recent_dates]

    if len(today_items) < target_count:
        today_items = all_items

    # Step 3: Pre-rank the full pool to get top candidates
    pool = _dedupe_same_event(today_items)[:80]  # Dedup same-event, cap to avoid huge prompts

    # Step 4: AI classifies articles into sections
    classified = _classify_articles(pool)

    # Step 5: AI rank within each section and generate summaries
    result = {}
    global_used_urls = set()  # Cross-section dedup
    for section in SECTIONS:
        section_limit = ITEMS_PER_SECTION.get(section, MAX_ITEMS_PER_SECTION)
        section_pool = classified.get(section, [])

        # Remove articles already used in another section
        section_pool = [item for item in section_pool if _normalize_url(item["url"]) not in global_used_urls]

        # Remove same-event duplicates within section
        section_pool = _dedupe_same_event(section_pool)

        # Rank within section
        ranked = _rank_and_select(section, section_pool, n=section_limit)

        # Pad if needed
        if len(ranked) < section_limit:
            used_urls = {_normalize_url(item["url"]) for item in ranked}
            for item in section_pool:
                if _normalize_url(item["url"]) not in used_urls:
                    ranked.append(item)
                    used_urls.add(_normalize_url(item["url"]))
                if len(ranked) >= section_limit:
                    break

        # Track globally used URLs
        for item in ranked[:section_limit]:
            global_used_urls.add(_normalize_url(item["url"]))

        # Generate summaries
        for item in ranked[:section_limit]:
            what, so_what, impact = generate_summary(item["title"], item["summary"])
            item["what"] = what
            item["so_what"] = so_what
            item["impact"] = impact

        result[section] = ranked[:section_limit]

    # Step 6: Redistribute impact levels: top 25% high, 25-75% mid, bottom 25% low
    all_items = []
    for section, items in result.items():
        for item in items:
            all_items.append(item)

    if all_items:
        # Sort by AI-assigned impact score (high=3, mid=2, low=1) to establish relative ordering
        score_map = {"high": 3, "mid": 2, "low": 1}
        all_items.sort(key=lambda x: score_map.get(x.get("impact", "mid"), 2), reverse=True)

        n = len(all_items)
        high_cutoff = max(1, round(n * 0.25))
        low_cutoff = max(1, round(n * 0.25))

        for i, item in enumerate(all_items):
            if i < high_cutoff:
                item["impact"] = "high"
            elif i >= n - low_cutoff:
                item["impact"] = "low"
            else:
                item["impact"] = "mid"

    return result


def fetch_all_news() -> list[dict]:
    all_items = []
    for section, items in fetch_all_sections().items():
        date_fetched = datetime.utcnow().isoformat() + "Z"
        for item in items:
            all_items.append(
                {
                    "title": item["title"],
                    "summary": item["summary"],
                    "source_url": item["url"],
                    "section": section,
                    "date_fetched": date_fetched,
                    "what": item["what"],
                    "so_what": item["so_what"],
                }
            )
    return all_items
