from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.services.monitoring_scheduler import MonitoringScheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    scheduler = MonitoringScheduler(interval_minutes=15)
    scheduler.start()
    app.state.monitoring_scheduler = scheduler
    try:
        yield
    finally:
        scheduler = getattr(app.state, "monitoring_scheduler", None)
        if scheduler is not None:
            scheduler.shutdown()


app = FastAPI(title="MACONLY Supply Brain", lifespan=lifespan)
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
def root():
    return {"status": "ok", "message": "MACONLY backend running"}
