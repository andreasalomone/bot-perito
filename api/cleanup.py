# This file serves as the entry point for a Vercel Serverless Function / Cron Job.
# It imports the actual cleanup logic from the core application module.
import logging

from app.core.cleanup import cleanup_tmp

logger = logging.getLogger(__name__)


def handler(event, context):
    """Scheduled cleanup function to delete old files in /tmp."""
    logger.info("Cleanup cron job invoked.")
    cleanup_tmp()
    logger.info("Cleanup cron job finished.")
    return {"status": "success"}


if __name__ == "__main__":
    cleanup_tmp()
