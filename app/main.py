from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app import stats
from app.db import close_pool, get_pool, init_pool, insert_batch
from app.schemas import AnonymizedRecord, IngestResponse


MAX_BATCH = 1000
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(
    title="axor-telemetry",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    raise HTTPException(status_code=429, detail="rate limit exceeded")


@app.get("/healthz")
async def healthz() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


@app.post("/v1/records", response_model=IngestResponse)
@limiter.limit("60/minute")
async def ingest(request: Request, batch: list[AnonymizedRecord]) -> IngestResponse:
    if len(batch) == 0:
        return IngestResponse(accepted=0)
    if len(batch) > MAX_BATCH:
        raise HTTPException(status_code=413, detail=f"batch exceeds {MAX_BATCH} records")

    ip = request.client.host if request.client else "unknown"
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]

    rows = [
        (r.axor_version, r.schema_version, r.model_dump_json(exclude={"axor_version", "schema_version"}))
        for r in batch
    ]
    pool = await get_pool()
    await insert_batch(pool, ip_hash, rows)
    return IngestResponse(accepted=len(batch))


@app.get("/stats", response_class=HTMLResponse)
async def public_stats() -> HTMLResponse:
    pool = await get_pool()
    html = await stats.render(pool)
    return HTMLResponse(content=html)
