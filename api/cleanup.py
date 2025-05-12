# This file serves as the entry point for a Vercel Serverless Function / Cron Job.
# It imports the actual cleanup logic from the core application module.
from app.core.cleanup import cleanup_tmp


def handler(event, context):
    """
    Scheduled cleanup function to delete old files in /tmp.
    """
    cleanup_tmp()
    return {"status": "success"}


if __name__ == "__main__":
    cleanup_tmp()
