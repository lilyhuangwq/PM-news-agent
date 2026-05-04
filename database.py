import os
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Generator

from sqlalchemy import Column, Date, Integer, String, create_engine, select
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session

# Use /tmp on Vercel (read-only filesystem), local path otherwise
if os.environ.get("VERCEL"):
    DB_PATH = Path("/tmp/news_agent.db")
else:
    DB_PATH = Path(__file__).resolve().parent / "news_agent.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
Base = declarative_base()

class NewsItem(Base):
    __tablename__ = "news_items"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(512), nullable=False)
    summary = Column(String(1024), nullable=False)
    url = Column(String(1024), nullable=False, index=True)
    source = Column(String(256), nullable=False)
    section = Column(String(128), nullable=False, index=True)
    fetch_date = Column(Date, nullable=False, index=True)
    what = Column(String(512), nullable=False)
    so_what = Column(String(512), nullable=False)


def create_db() -> None:
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
                )
            ).scalars().first()

            if existing:
                existing.title = item["title"]
                existing.summary = item["summary"]
                existing.source = item.get("source", existing.source)
                existing.section = item["section"]
                existing.what = item.get("what", existing.what)
                existing.so_what = item.get("so_what", existing.so_what)
            else:
                session.add(
                    NewsItem(
                        title=item["title"],
                        summary=item["summary"],
                        url=item["url"],
                        source=item.get("source", ""),
                        section=item["section"],
                        fetch_date=item_date,
                        what=item.get("what", "Summary not available"),
                        so_what=item.get("so_what", "Summary not available"),
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
                    "what": item.what,
                    "so_what": item.so_what,
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
