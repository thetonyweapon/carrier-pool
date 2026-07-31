from fastapi import FastAPI

from app.health import router as health_router
from app.lane_api import router as lane_router
from app.recommendation_api import router as recommendation_router


def create_app() -> FastAPI:
    application = FastAPI(title="Carrier Pool API", version="0.1.0")
    application.include_router(health_router)
    application.include_router(lane_router)
    application.include_router(recommendation_router)
    return application


app = create_app()
