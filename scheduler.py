import logging
import threading
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from fetcher import fetch_all_sections, translate_batch
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
                    "pub_date": item.get("pub_date"),
                    "impact": item.get("impact", "mid"),
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

        # Pre-translate all articles to Chinese
        try:
            _pre_translate_batch(batch)
            save_news_batch(batch)  # Update DB with zh fields
            logger.info("[%s] Pre-translation completed for %d items.", timestamp, len(batch))
        except Exception as exc:
            logger.exception("[%s] Pre-translation failed (articles saved without zh): %s", timestamp, exc)
    except Exception as exc:
        logger.exception("[%s] News refresh failed: %s", timestamp, exc)
        raise


def _pre_translate_batch(batch: list[dict]) -> None:
    """Translate title, what, so_what for all items and add zh fields."""
    titles = [item.get("title", "") for item in batch]
    whats = [item.get("what", "") for item in batch]
    so_whats = [item.get("so_what", "") for item in batch]

    all_texts = titles + whats + so_whats
    translated = translate_batch(all_texts)

    n = len(batch)
    for i, item in enumerate(batch):
        item["title_zh"] = translated[i]
        item["what_zh"] = translated[n + i]
        item["so_what_zh"] = translated[n * 2 + i]


def _today_has_data() -> bool:
    today_key = date.today().isoformat()
    return today_key in get_available_dates()


def start_scheduler() -> None:
    import os
    # Vercel serverless has no persistent process — skip APScheduler
    if os.environ.get("VERCEL"):
        return
    if not scheduler.get_job("daily_news_refresh"):
        scheduler.add_job(refresh_news, trigger="cron", hour=7, minute=0, id="daily_news_refresh")
    if not scheduler.running:
        scheduler.start()
    if not _today_has_data():
        logger.info("Today's news data is missing, performing initial refresh in background.")
        threading.Thread(target=refresh_news, daemon=True).start()
