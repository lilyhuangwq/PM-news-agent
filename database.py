import os
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Generator

from sqlalchemy import Column, Date, Integer, String, Text, DateTime, create_engine, select, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session

# Use DATABASE_URL env var (Supabase Postgres) if set, otherwise local SQLite
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
else:
    DB_PATH = Path(__file__).resolve().parent / "news_agent.db"
    DATABASE_URL = f"sqlite:///{DB_PATH}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

Base = declarative_base()

class NewsItem(Base):
    __tablename__ = "news_items"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    url = Column(Text, nullable=False, index=True)
    source = Column(String(256), nullable=False)
    section = Column(String(128), nullable=False, index=True)
    fetch_date = Column(Date, nullable=False, index=True)
    pub_date = Column(String(10), nullable=True)
    impact = Column(String(10), nullable=True)
    what = Column(Text, nullable=False)
    so_what = Column(Text, nullable=False)
    title_zh = Column(Text, nullable=True)
    what_zh = Column(Text, nullable=True)
    so_what_zh = Column(Text, nullable=True)


class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True, index=True)
    url = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    source = Column(String(256), nullable=False)
    section = Column(String(128), nullable=False)
    vote = Column(String(10), nullable=False)  # 'up' or 'down'
    clicked = Column(Integer, default=0)  # 1 if user clicked the link
    created_at = Column(DateTime, nullable=False)


def create_db() -> None:
    if not os.environ.get("DATABASE_URL"):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


def _normalize_date(value) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(str(value)).date()


def save_news_batch(items: list[dict]) -> None:
    with get_session() as session:
        for item in items:
            item_date = _normalize_date(item["fetch_date"])
            existing = session.execute(
                select(NewsItem).where(
                    NewsItem.url == item["url"],
                    NewsItem.fetch_date == item_date,
                    NewsItem.section == item["section"],
                )
            ).scalars().first()

            if existing:
                existing.title = item["title"]
                existing.summary = item["summary"]
                existing.source = item.get("source", existing.source)
                existing.section = item["section"]
                existing.pub_date = item.get("pub_date", existing.pub_date)
                existing.impact = item.get("impact", existing.impact)
                existing.what = item.get("what", existing.what)
                existing.so_what = item.get("so_what", existing.so_what)
                if item.get("title_zh"):
                    existing.title_zh = item["title_zh"]
                if item.get("what_zh"):
                    existing.what_zh = item["what_zh"]
                if item.get("so_what_zh"):
                    existing.so_what_zh = item["so_what_zh"]
            else:
                session.add(
                    NewsItem(
                        title=item["title"],
                        summary=item["summary"],
                        url=item["url"],
                        source=item.get("source", ""),
                        section=item["section"],
                        fetch_date=item_date,
                        pub_date=item.get("pub_date"),
                        impact=item.get("impact", "mid"),
                        what=item.get("what", "Summary not available"),
                        so_what=item.get("so_what", "Summary not available"),
                        title_zh=item.get("title_zh"),
                        what_zh=item.get("what_zh"),
                        so_what_zh=item.get("so_what_zh"),
                    )
                )
        session.commit()


def get_news_by_date(fetch_date) -> dict[str, list[dict]]:
    requested_date = _normalize_date(fetch_date)
    with get_session() as session:
        query = select(NewsItem).where(NewsItem.fetch_date == requested_date).order_by(NewsItem.section, NewsItem.title)
        results = session.execute(query).scalars().all()

        grouped: dict[str, list[dict]] = {}
        for item in results:
            grouped.setdefault(item.section, []).append(
                {
                    "title": item.title,
                    "summary": item.summary,
                    "url": item.url,
                    "source": item.source,
                    "section": item.section,
                    "fetch_date": item.fetch_date.isoformat(),
                    "pub_date": item.pub_date or item.fetch_date.isoformat(),
                    "impact": item.impact or "mid",
                    "what": item.what,
                    "so_what": item.so_what,
                    "title_zh": item.title_zh or "",
                    "what_zh": item.what_zh or "",
                    "so_what_zh": item.so_what_zh or "",
                }
            )
        return grouped


def get_available_dates() -> list[str]:
    with get_session() as session:
        query = select(NewsItem.fetch_date).distinct().order_by(NewsItem.fetch_date.desc())
        results = session.execute(query).scalars().all()
        return [d.isoformat() for d in results]


def get_news(section: str | None = None) -> list[dict]:
    with get_session() as session:
        query = select(NewsItem)
        if section:
            query = query.where(NewsItem.section == section)
        query = query.order_by(NewsItem.section, NewsItem.fetch_date.desc())
        results = session.execute(query).scalars().all()
        return [
            {
                "title": item.title,
                "summary": item.summary,
                "url": item.url,
                "source": item.source,
                "section": item.section,
                "fetch_date": item.fetch_date.isoformat(),
                "what": item.what,
                "so_what": item.so_what,
            }
            for item in results
        ]


_SOURCE_NAMES = {
    "techcrunch.com": "TechCrunch", "theverge.com": "The Verge",
    "arstechnica.com": "Ars Technica", "importai.substack.com": "Import AI",
    "openai.com": "OpenAI", "sierra.ai": "Sierra", "bbc.co.uk": "BBC",
    "arxiv.org": "arXiv", "interconnects.ai": "Interconnects",
    "stratechery.com": "Stratechery", "economist.com": "The Economist",
    "addyosmani.com": "Addy Osmani", "github.com": "GitHub",
    "pv-magazine.com": "PV Magazine",
}


def _normalize_source(source: str) -> str:
    return _SOURCE_NAMES.get(source.lower().strip(), source)


def save_feedback(url: str, title: str, source: str, section: str, vote: str) -> None:
    source = _normalize_source(source)
    with get_session() as session:
        session.add(Feedback(
            url=url, title=title, source=source, section=section,
            vote=vote, created_at=datetime.utcnow()
        ))
        session.commit()


def record_click(url: str) -> None:
    with get_session() as session:
        fb = session.execute(
            select(Feedback).where(Feedback.url == url).order_by(Feedback.created_at.desc())
        ).scalars().first()
        if fb:
            fb.clicked = 1
            session.commit()
        else:
            session.add(Feedback(
                url=url, title="", source="", section="",
                vote="click", clicked=1, created_at=datetime.utcnow()
            ))
            session.commit()


def get_preference_report() -> dict:
    with get_session() as session:
        # Top liked sources
        liked_sources = session.execute(
            select(Feedback.source, func.count(Feedback.id).label("cnt"))
            .where(Feedback.vote == "up", Feedback.source != "")
            .group_by(Feedback.source)
            .order_by(func.count(Feedback.id).desc())
            .limit(5)
        ).all()

        # Extract disliked topic keywords from 👎'd article titles
        disliked_titles = session.execute(
            select(Feedback.title).where(Feedback.vote == "down", Feedback.title != "")
        ).scalars().all()

        disliked_topics = _extract_topic_keywords(disliked_titles)

        # Click rate
        total = session.execute(select(func.count(Feedback.id)).where(Feedback.vote.in_(["up", "down"]))).scalar() or 0
        clicked = session.execute(select(func.count(Feedback.id)).where(Feedback.clicked == 1)).scalar() or 0

        # Recent feedback counts
        up_count = session.execute(select(func.count(Feedback.id)).where(Feedback.vote == "up")).scalar() or 0
        down_count = session.execute(select(func.count(Feedback.id)).where(Feedback.vote == "down")).scalar() or 0

        return {
            "top_liked_sources": [{"source": r[0], "count": r[1]} for r in liked_sources],
            "disliked_topics": disliked_topics,
            "total_rated": total,
            "total_clicked": clicked,
            "click_rate": f"{(clicked/total*100):.0f}%" if total > 0 else "0%",
            "thumbs_up": up_count,
            "thumbs_down": down_count,
        }


_STOP_WORDS = {
    # articles, prepositions, conjunctions, pronouns
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "its", "it", "and", "or", "but", "not",
    "be", "has", "have", "had", "do", "does", "did", "will", "would", "could",
    "should", "can", "may", "might", "that", "this", "these", "those", "they",
    "them", "their", "there", "here", "where", "when", "which", "who", "whom",
    "you", "your", "we", "our", "he", "she", "his", "her", "my", "me",
    # common verbs / adjectives too generic to be topical
    "new", "how", "why", "what", "all", "up", "out", "about", "just", "more",
    "most", "than", "into", "over", "after", "before", "as", "no", "so", "if",
    "get", "got", "been", "being", "make", "makes", "made", "first", "big",
    "says", "said", "one", "also", "now", "still", "even", "back", "way",
    "going", "goes", "come", "comes", "coming", "take", "takes", "taking",
    "look", "looks", "looking", "give", "gives", "use", "uses", "using",
    "show", "shows", "find", "found", "want", "wants", "need", "needs",
    "try", "tries", "keep", "keeps", "let", "start", "stop", "run", "runs",
    "set", "put", "turn", "turns", "help", "helps", "change", "changes",
    "move", "moves", "play", "work", "works", "call", "calls", "long",
    "own", "old", "right", "left", "high", "low", "end", "part", "last",
    "next", "much", "each", "every", "both", "few", "many", "some", "any",
    "other", "only", "very", "well", "too", "yet", "then", "down", "off",
    "away", "again", "once", "ever", "never", "always", "often", "really",
    "already", "around", "between", "through", "under", "along", "without",
    "during", "toward", "towards", "upon", "across", "against", "among",
    # generic news/headline words
    "report", "reports", "according", "per", "via", "like", "near",
    "early", "late", "top", "best", "full", "open", "close", "free",
    "small", "large", "good", "bad", "great", "real", "true", "false",
    "possible", "likely", "able", "going", "year", "years", "day", "days",
    "week", "weeks", "month", "months", "time", "world", "today",
    "people", "million", "billion", "percent", "number", "second", "third",
    "company", "companies", "market", "business", "users", "data",
    "color", "replace", "replaces", "replacing", "add", "adds", "adding",
    "bring", "brings", "lead", "leads", "offer", "offers", "plan", "plans",
    "face", "faces", "hit", "hits", "win", "wins", "lose", "lost",
    "rise", "rises", "fall", "falls", "drop", "drops", "grow", "grows",
    "build", "builds", "launch", "launches", "release", "releases",
    "deal", "deals", "push", "pull", "test", "tests", "join", "joins",
    "buy", "buys", "sell", "sells", "pay", "pays", "cut", "cuts",
    "rule", "rules", "hold", "holds", "meet", "meets", "raise", "raises",
    "could", "may", "might", "will", "just", "also", "become", "becomes",
    "want", "feature", "features", "update", "updates", "support",
    "ahead", "amid", "despite", "while", "until", "since", "whether",
}


def _extract_topic_keywords(titles: list[str]) -> list[dict]:
    """Extract meaningful topic keywords from disliked article titles."""
    import re
    from collections import Counter
    if not titles:
        return []
    word_freq: Counter = Counter()
    # Also track bigrams for better context
    bigram_freq: Counter = Counter()
    for title in titles:
        words = [w.lower() for w in re.findall(r"[a-zA-Z']+", title) if len(w) > 3]
        meaningful = [w for w in words if w not in _STOP_WORDS]
        for w in meaningful:
            word_freq[w] += 1
        for i in range(len(meaningful) - 1):
            bigram_freq[f"{meaningful[i]} {meaningful[i+1]}"] += 1

    # Combine: prefer bigrams that appear 2+ times, then top single words
    results = []
    seen_words = set()
    for bigram, count in bigram_freq.most_common(5):
        if count >= 2:
            results.append({"topic": bigram, "count": count})
            seen_words.update(bigram.split())
    for word, count in word_freq.most_common(10):
        if word not in seen_words and count >= 1:
            results.append({"topic": word, "count": count})
            if len(results) >= 8:
                break
    return results
