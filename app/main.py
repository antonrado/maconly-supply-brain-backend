from fastapi import FastAPI

from app.api.v1.router import api_router
from app.services.monitoring_scheduler import MonitoringScheduler


app = FastAPI(title="MACONLY Supply Brain")
app.include_router(api_router, prefix="/api/v1")


@app.on_event("startup")
def _startup_event() -> None:
    scheduler = MonitoringScheduler(interval_minutes=15)
    scheduler.start()
    app.state.monitoring_scheduler = scheduler


@app.on_event("shutdown")
def _shutdown_event() -> None:
    scheduler = getattr(app.state, "monitoring_scheduler", None)
    if scheduler is not None:
        scheduler.shutdown()


@app.get("/")
def root():
    return {"status": "ok", "message": "MACONLY backend running"}
