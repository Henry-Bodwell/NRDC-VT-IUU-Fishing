"""
Background task cleanup utilities.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from app.models.task import TaskStatus

logger = logging.getLogger(__name__)


async def cleanup_old_tasks():
    """
    Delete tasks that are completed or failed and older than 24 hours.
    This runs as a background cleanup job.
    """
    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=24)

        # Find old completed/failed tasks
        old_tasks = await TaskStatus.find(
            {
                "status": {"$in": ["completed", "failed"]},
                "updated_at": {"$lt": cutoff_time},
            }
        ).to_list()

        deleted_count = 0
        for task in old_tasks:
            await task.delete()
            deleted_count += 1

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old task(s)")

    except Exception as e:
        logger.error(f"Error during task cleanup: {e}")


async def periodic_cleanup(interval_hours: int = 6):
    """
    Run cleanup_old_tasks periodically at the specified interval.

    Args:
        interval_hours: How often to run cleanup (default: every 6 hours)
    """
    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)  # Convert hours to seconds
            logger.info("Running periodic task cleanup")
            await cleanup_old_tasks()
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}")
