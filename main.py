from contextlib import asynccontextmanager
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import create_db, get_available_dates, get_news_by_date, save_feedback, record_click, get_preference_report
from scheduler import refresh_news, start_scheduler

BASE_DIR = Path(__file__).resolve().parent

_PDT = timezone(timedelta(hours=-7))

def _today_pdt() -> date:
    return datetime.now(_PDT).date()

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db()
    start_scheduler()
    yield

app = FastAPI(title="PM News Agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(str(BASE_DIR / "static" / "index.html"), headers={"Cache-Control": "no-cache"})

_NEWS_CACHE_HEADERS = {"Cache-Control": "public, s-maxage=600, max-age=300, stale-while-revalidate=60"}


@app.get("/api/news/today")
async def api_news_today():
    from fastapi.responses import JSONResponse
    data = get_news_by_date(_today_pdt())
    if data:
        return JSONResponse(content=data, headers=_NEWS_CACHE_HEADERS)
    # Before today's refresh, fall back to most recent available date
    dates = get_available_dates()
    if dates:
        latest = date.fromisoformat(dates[0])
        return JSONResponse(content=get_news_by_date(latest), headers=_NEWS_CACHE_HEADERS)
    # No data at all (e.g. fresh Vercel cold start) — fetch now
    try:
        refresh_news()
        data = get_news_by_date(_today_pdt())
        if data:
            return data
    except Exception:
        pass
    return {}

@app.get("/api/news/{news_date}")
async def api_news_by_date(news_date: str):
    try:
        requested = date.fromisoformat(news_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Date must be in YYYY-MM-DD format")
    return get_news_by_date(requested)

@app.get("/api/dates")
async def api_dates():
    return get_available_dates()

@app.post("/api/refresh")
async def api_refresh():
    refresh_news()
    return {"status": "refresh triggered"}

@app.get("/api/cron")
async def api_cron():
    """Vercel Cron Job endpoint — triggers daily news refresh."""
    refresh_news()
    return {"status": "cron refresh completed"}


@app.post("/api/feedback")
async def api_feedback(body: dict):
    url = body.get("url", "")
    title = body.get("title", "")
    source = body.get("source", "")
    section = body.get("section", "")
    vote = body.get("vote", "")
    if vote not in ("up", "down"):
        raise HTTPException(status_code=400, detail="vote must be 'up' or 'down'")
    save_feedback(url=url, title=title, source=source, section=section, vote=vote)
    return {"status": "ok"}


@app.post("/api/click")
async def api_click(body: dict):
    url = body.get("url", "")
    if url:
        record_click(url)
    return {"status": "ok"}


@app.get("/api/preferences")
async def api_preferences():
    return get_preference_report()
