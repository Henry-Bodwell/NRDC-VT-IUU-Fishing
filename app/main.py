from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.database import init_db
from app.routes import router
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
    yield
    # You can add shutdown logic here if needed
    logger.info("Application shutdown.")


def main():
    logging.basicConfig(filename="fishlog.log", level=logging.INFO)

    # Create the main FastAPI application instance, passing the lifespan manager
    app = FastAPI(lifespan=lifespan)

    app.include_router(router, prefix="/api", tags=["api"])

    @app.get("/", tags=["Root"])
    async def read_root():
        """
        A simple root endpoint to confirm the API is running.
        """
        return {"message": "Welcome to the Fish Project API!"}

    return app


if __name__ == "__main__":
    main()
