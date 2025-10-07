import os
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.logging import setup_logging
from app.database import init_db
from app.routes import router
from app.tasks.cleanup import cleanup_old_tasks, periodic_cleanup
import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup events.
    Connects to the database before the app starts receiving requests.
    """
    await init_db()
    logger.info("Application startup complete. Database connected.")

    # Run initial cleanup of old tasks
    logger.info("Running initial task cleanup")
    await cleanup_old_tasks()

    # Start periodic cleanup in background
    cleanup_task = asyncio.create_task(periodic_cleanup(interval_hours=6))
    logger.info("Started periodic task cleanup (every 6 hours)")

    yield

    # Shutdown: cancel the cleanup task
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        logger.info("Periodic cleanup task cancelled")

    logger.info("Application shutdown.")


# Configure logging
setup_logging()
frontendPort = os.getenv("FRONTEND_PORT", "4000")
origins = [
    "http://localhost",
    "http://localhost:5000",
    f"http://localhost:{frontendPort}",
    "https://localhost",
    "https://localhost:5000",
    f"https://localhost:{frontendPort}",
]

# Create the FastAPI app instance at module level
app = FastAPI(lifespan=lifespan)
app.include_router(router, prefix="/api", tags=["api"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Root"])
async def read_root():
    """
    A simple root endpoint to confirm the API is running.
    """
    return {"message": "Welcome to the Fish Project API!"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
