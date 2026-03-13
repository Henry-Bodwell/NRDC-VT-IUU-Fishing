from fastapi import APIRouter

from app.routes.incidents import router as incidents_router
from app.routes.sources import router as sources_router
from app.routes.overviews import router as overviews_router
from app.routes.logs import router as logs_router
from app.routes.tasks import router as tasks_router

router = APIRouter()
router.include_router(incidents_router)
router.include_router(sources_router)
router.include_router(overviews_router)
router.include_router(logs_router)
router.include_router(tasks_router)


@router.get("/ping")
async def ping():
    return {"message": "Pong"}
