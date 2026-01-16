"""Background scheduler for automated digest delivery."""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.config import get_settings
from src.core.database import async_session_maker
from src.services.digest import DigestService

logger = logging.getLogger(__name__)
settings = get_settings()

scheduler = AsyncIOScheduler()


async def process_scheduled_digests() -> None:
    """
    Process all scheduled digests.

    This job runs every hour and checks which users are due for a digest.
    """
    logger.info("Starting scheduled digest processing")

    async with async_session_maker() as db:
        digest_service = DigestService()
        try:
            count = await digest_service.process_pending_digests(db)
            logger.info(f"Processed {count} scheduled digests")
        except Exception as e:
            logger.error(f"Error processing scheduled digests: {e}")
        finally:
            await digest_service.close()


def start_scheduler() -> None:
    """Start the background scheduler."""
    # Run digest processing every hour at minute 0
    scheduler.add_job(
        process_scheduled_digests,
        trigger=CronTrigger(minute=0),  # Every hour
        id="process_digests",
        name="Process scheduled digests",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler() -> None:
    """Stop the background scheduler."""
    scheduler.shutdown()
    logger.info("Scheduler stopped")


# CLI entry point for running scheduler standalone
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def run_once() -> None:
        """Run digest processing once (for testing or manual trigger)."""
        await process_scheduled_digests()

    asyncio.run(run_once())
