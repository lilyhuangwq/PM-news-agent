# AI News Briefing

A local FastAPI-based news dashboard that fetches AI-related news from RSS feeds, generates AI-powered summaries, and archives it in SQLite.

## Tech Stack

- Frontend: HTML + Tailwind CSS CDN
- Backend: Python + FastAPI
- Scheduler: APScheduler
- Storage: SQLite + SQLAlchemy
- News ingestion: `feedparser` for RSS + NewsAPI fallback
- AI Summaries: DeepSeek (deepseek-chat)
- Deployment: local first; suitable for Railway / Render later

## Project Structure

- `main.py` — FastAPI application and API endpoints
- `fetcher.py` — RSS feed parsing, NewsAPI fallback, deduplication
- `database.py` — SQLAlchemy models, SQLite storage, archive queries
- `scheduler.py` — APScheduler daily refresh and startup refresh logic
- `static/index.html` — single-page dashboard UI
- `requirements.txt` — Python dependencies

## Features

- Daily archive of AI news by section with AI-generated "What" and "So What" summaries
- Sections:
  - AI & Tech Frontier
  - Product & Builder
  - Startup & VC
  - Global Tech
  - Deep Read
- Archive browsing by available dates
- Manual refresh endpoint for testing
- RSS collection and NewsAPI fallback when feeds return too few items
- AI summaries using OpenAI (set OPENAI_API_KEY for enhanced summaries)

## API Endpoints

- `GET /api/news/today` — today's news grouped by section
- `GET /api/news/{date}` — archive news for a specific date (YYYY-MM-DD)
- `GET /api/dates` — list of archive dates with data
- `POST /api/refresh` — manually trigger news fetch
- `GET /` — serve the dashboard UI

## RSS Sources

- AI & Tech Frontier:
  - `https://www.theverge.com/rss/index.xml`
  - `https://techcrunch.com/feed/`
  - `https://importai.substack.com/feed`
  - `https://www.therundown.ai/feed`
  - `https://feeds.feedburner.com/oreilly/radar`
- Product & Builder:
  - `https://www.lennysnewsletter.com/feed`
  - `https://firstround.com/review/feed/`
  - `https://producthunt.com/feed`
  - `https://www.reforge.com/blog/rss.xml`
- Startup & VC:
  - `https://a16z.com/feed/`
  - `https://bothsidesofthetable.com/feed`
  - `https://news.ycombinator.com/rss`
  - `https://pitchbook.com/news/rss`
- Global Tech:
  - `https://technode.com/feed/`
  - `https://kr-asia.com/feed`
  - `https://www.techinasia.com/feed`
  - `https://asia.nikkei.com/rss/feed/nar`
- Deep Read:
  - `https://stratechery.com/feed/`
  - `https://every.to/feed`
  - `https://www.ben-evans.com/benedictevans/rss.xml`
  - `https://www.lennysnewsletter.com/feed`

## Setup

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set API keys (optional):
   ```powershell
   $env:NEWS_API_KEY = "your_newsapi_key_here"
   $env:OPENAI_API_KEY = "your_openai_key_here"  # For AI summaries
   ```
4. Run the app:
   ```bash
   uvicorn main:app --reload
   ```

## Notes

- SQLite is used for local archives and can be replaced with PostgreSQL later.
- The scheduler runs once at startup if today's data is missing, then every day at 07:00 UTC.
- The dashboard is a single-file Tailwind HTML UI.
