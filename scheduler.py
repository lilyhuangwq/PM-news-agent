import logging
import threading
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from fetcher import fetch_all_sections
from database import get_available_dates, save_news_batch

logger = logging.getLogger("pm_news_agent.scheduler")
scheduler = BackgroundScheduler(timezone="America/Los_Angeles")


def _build_batch_items(section_items: dict[str, list[dict]], fetch_date: date) -> list[dict]:
    batch: list[dict] = []
    for section, items in section_items.items():
        for item in items:
            batch.append(
                {
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "url": item.get("url", ""),
                    "source": item.get("source_name", ""),
                    "section": section,
                    "fetch_date": fetch_date,
                    "what": item.get("what", "Summary not available"),
                    "so_what": item.get("so_what", "Summary not available"),
                }
            )
    return batch


def refresh_news() -> None:
    fetch_date = date.today()
    timestamp = datetime.now().isoformat()
    try:
        section_items = fetch_all_sections()
        batch = _build_batch_items(section_items, fetch_date)
        save_news_batch(batch)
        logger.info("[%s] News refresh completed, saved %d items for %s.", timestamp, len(batch), fetch_date)
    except Exception as exc:
        logger.exception("[%s] News refresh failed: %s", timestamp, exc)
        raise


def _today_has_data() -> bool:
    today_key = date.today().isoformat()
    return today_key in get_available_dates()


def start_scheduler() -> None:
    import os
    # Vercel serverless has no persistent process — skip APScheduler
    if os.environ.get("VERCEL"):
        return
    if not scheduler.get_job("daily_news_refresh"):
        scheduler.add_job(refresh_news, trigger="cron", hour=6, minute=0, id="daily_news_refresh")
    if not scheduler.running:
        scheduler.start()
    if not _today_has_data():
        logger.info("Today's news data is missing, performing initial refresh in background.")
        threading.Thread(target=refresh_news, daemon=True).start()
