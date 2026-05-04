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
        "https://firstround.com/review/feed/",
        "https://www.reforge.com/blog/rss.xml",
        "https://blackboxofpm.com/feed",
        "https://productlessons.xyz/feed",
        "https://www.growth.design/feed",
        "https://casestudy.club/feed",
        "https://www.productled.org/feed",
        "https://openviewpartners.com/feed/",
        "https://www.latent.space/feed",
        "https://www.aitidbits.ai/feed",
        "https://www.exponentialview.co/feed",
        "https://softwarecrisis.dev/feed",
        "https://www.interconnects.ai/feed",
        "https://www.indiehackers.com/feed.rss",
        "https://hackernewsletter.com/issues.rss",
        "https://tldr.tech/api/rss/founders",
    ],
    "Startup & VC": [
        "https://a16z.com/feed/",
        "https://bothsidesofthetable.com/feed",
        "https://news.ycombinator.com/rss",
        "https://pitchbook.com/news/rss",
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
RSS_TIMEOUT = 10
NEWSAPI_TIMEOUT = 10
MAX_ITEMS_PER_SECTION = 5
FALLBACK_MIN_ITEMS = 3

# Section-specific editorial focus for ranking
SECTION_FOCUS = {
    "AI & Tech Frontier": "Prioritize model releases, research breakthroughs, and AI capability milestones.",
    "Product & Builder": "Prioritize PMF case studies, growth data, product decision stories, and builder insights.",
    "Startup & VC": "Prioritize AI-sector funding rounds ($10M+), investor public takes, and market signals.",
    "Global Tech": "Prioritize China/Japan/Korea big tech moves, cross-border expansion, and US-Asia tech dynamics.",
    "Deep Read": "Only select long-form analysis pieces. Prioritize Stratechery, Every.to, a16z, Ben Evans caliber writing.",
}

RANKING_RULES = """Signal over Noise scoring:
+3  Directly impacts AI product decisions or startup direction
+2  Big tech strategic move (launch/acquisition/layoff)
+2  Funding/market signal ($10M+ round, or clear trend)
+1  Data-backed product/growth case study
-1  Opinion/prediction piece without factual basis
-2  Duplicate coverage of same event (pick best source only)
-2  PR piece / sponsored content
-3  Entertainment / non-industry content

MUST INCLUDE if present:
- Major AI model releases or capability breakthroughs
- Big tech strategic moves (acquisitions, pivots, layoffs)
- Funding rounds $10M+ in AI/tech
- Regulatory changes affecting AI products

PRIORITIZE:
- News with concrete data over opinion pieces
- First reports over follow-up coverage
- Builder/founder-relevant insights over general tech news

EXCLUDE:
- Duplicate coverage of same event (pick best source only)
- PR pieces without substance
- Prediction/speculation without factual basis"""


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


def generate_summary(title: str, summary: str) -> tuple[str, str]:
    if not client:
        return summary or title, ""
    prompt = f"""You are a news curator for an AI PM preparing to start an AI company in the US.

Article title: {title}
Article summary: {summary}

Write two sections:

1. "what" — 1 factual sentence, max 20 words. Include specific names, numbers, or data points. No opinions.

2. "so_what" — 1 sentence on why this matters for an AI founder, max 25 words. Be concrete about strategic implications: market timing, competitive dynamics, regulatory risk, distribution, funding climate, or technical moats.

Return ONLY valid JSON: {{"what": "...", "so_what": "..."}}
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
        return what, so_what
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        try:
            start = result.index("{")
            end = result.rindex("}") + 1
            data = json.loads(result[start:end])
            return data.get("what", summary or title), data.get("so_what", "")
        except (ValueError, json.JSONDecodeError):
            print(f"Failed to parse summary JSON: {result[:200]}")
            return summary or title, ""
    except Exception as e:
        print(f"Error generating summary: {e}")
        return summary or title, ""


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

    # If too few articles from today, include yesterday and day-before
    if len(today_items) < FALLBACK_MIN_ITEMS:
        from datetime import date as _date, timedelta
        td = _date.fromisoformat(target_date)
        recent_dates = {target_date, (td - timedelta(days=1)).isoformat(), (td - timedelta(days=2)).isoformat()}
        today_items = [item for item in all_items if item.get("pub_date") in recent_dates]

    # Fallback to NewsAPI if not enough items
    if len(today_items) < FALLBACK_MIN_ITEMS:
        today_items.extend(_fetch_newsapi_fallback(section))
        today_items = _dedupe_items(today_items)

    # AI-rank and select the top items from the filtered pool
    final_items = _rank_and_select(section, today_items)

    # Generate AI summaries only for the final selected items
    for item in final_items:
        what, so_what = generate_summary(item["title"], item["summary"])
        item["what"] = what
        item["so_what"] = so_what

    return final_items


def fetch_all_sections() -> dict[str, list[dict]]:
    return {section: fetch_section_rss_items(section) for section in SECTIONS}


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
