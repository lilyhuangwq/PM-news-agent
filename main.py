from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import create_db, get_available_dates, get_news_by_date
from fetcher import client as deepseek_client
from scheduler import refresh_news, start_scheduler

BASE_DIR = Path(__file__).resolve().parent

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

@app.get("/api/news/today")
async def api_news_today():
    from fastapi.responses import JSONResponse
    data = get_news_by_date(date.today())
    if data:
        return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=300, s-maxage=600"})
    # Before today's refresh, fall back to most recent available date
    dates = get_available_dates()
    if dates:
        latest = date.fromisoformat(dates[0])
        return JSONResponse(content=get_news_by_date(latest), headers={"Cache-Control": "public, max-age=300, s-maxage=600"})
    # No data at all (e.g. fresh Vercel cold start) — fetch now
    try:
        refresh_news()
        data = get_news_by_date(date.today())
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


class TranslateRequest(BaseModel):
    texts: list[str]


@app.post("/api/translate")
async def api_translate(req: TranslateRequest):
    if not deepseek_client or not req.texts:
        return {"translations": req.texts}
    try:
        combined = "\n---\n".join(req.texts)
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": f"""你是一位资深科技媒体编辑和AI翻译专家，负责将英文科技简报翻译成地道的中文。你的翻译质量应该媲美人工翻译，绝不能有AI机翻的痕迹。

要求：
- 用自然流畅的中文表达，像36氪、晚点LatePost的资深编辑写的一样
- 严禁生硬的机翻感，不要逐字翻译，要理解语境后重新用中文表达
- 句式要符合中文习惯，避免英文语序（如被动句、从句嵌套）
- 专业术语保留英文或用业内通用译法（如 AI、PM、SaaS、GPT）
- 语气简洁有力，像在跟同行聊天，有洞察力
- 每段翻译之间用 --- 分隔，保持原文顺序
- 翻译后自查：如果读起来像机器翻译的，重新翻译

以下是需要翻译的内容：

{combined}"""}],
        )
        parts = response.choices[0].message.content.strip().split("---")
        translations = [p.strip() for p in parts]
        # Pad if DeepSeek returned fewer items
        while len(translations) < len(req.texts):
            translations.append(req.texts[len(translations)])
        return {"translations": translations[:len(req.texts)]}
    except Exception:
        return {"translations": req.texts}
