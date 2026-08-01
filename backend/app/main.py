from fastapi import FastAPI

from app.auth_api import router as auth_router
from app.broker_operations_api import router as broker_operations_router
from app.health import router as health_router
from app.lane_api import router as lane_router
from app.rate_estimation_api import router as rate_estimation_router
from app.recommendation_api import router as recommendation_router
from app.shared_carrier_pool_api import router as shared_carrier_pool_router


def create_app() -> FastAPI:
    application = FastAPI(title="Carrier Pool API", version="0.1.0")
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(lane_router)
    application.include_router(recommendation_router)
    application.include_router(rate_estimation_router)
    application.include_router(broker_operations_router)
    application.include_router(shared_carrier_pool_router)
    return application


app = create_app()
