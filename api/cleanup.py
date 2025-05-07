from app.core.cleanup import cleanup_tmp


def handler(event, context):
    """
    Scheduled cleanup function to delete old files in /tmp.
    """
    cleanup_tmp()
    return {"status": "success"}


if __name__ == "__main__":
    cleanup_tmp()
