import os
import asyncio
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from app.logging import setup_logging
from app.database import init_db
from app.routes import router
from app.routes_auth import router as auth_router
from app.tasks.cleanup import cleanup_old_tasks, periodic_cleanup
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.rate_limit import create_limiter
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
    "http://iuudb.cs.vt.edu",
    "https://iuudb.cs.vt.edu",
    f"http://iuudb.cs.vt.edu:{frontendPort}",
    f"https://iuudb.cs.vt.edu:{frontendPort}",
]

# Configure rate limiter with IP whitelist support
limiter = create_limiter()

# Create the FastAPI app instance at module level
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(router, prefix="/api", tags=["api"])
app.include_router(auth_router, prefix="/api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler to ensure all unhandled exceptions return JSON responses.
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred while processing the request.",
            "details": str(exc),
        },
    )


@app.get("/", tags=["Root"])
@limiter.limit("100/minute")
async def read_root(request: Request):
    """
    A simple root endpoint to confirm the API is running.
    """
    return {"message": "Welcome to the Fish Project API!"}


# Apply rate limits to specific routes using decorators
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """
    Apply route-specific rate limits based on endpoint type
    """
    from app.rate_limit import RATE_LIMITS

    path = request.url.path
    method = request.method

    # Define rate limits for different endpoints
    rate_limit = None

    if path.startswith("/api/incidents") and method == "POST":
        rate_limit = RATE_LIMITS["expensive"]  # 30/hour
    elif path.startswith("/api/") and method in ["PUT", "DELETE"]:
        rate_limit = RATE_LIMITS["write"]  # 100/hour
    elif path.startswith("/api/logs"):
        rate_limit = RATE_LIMITS["logs"]  # 60/minute
    elif path.startswith("/api/") and method == "GET":
        rate_limit = RATE_LIMITS["read"]  # 300/minute

    # Apply rate limit if defined
    if rate_limit:
        try:
            await limiter.check(rate_limit)(request)
        except Exception:
            # Rate limit exceeded - will be handled by exception handler
            pass

    response = await call_next(request)
    return response


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
