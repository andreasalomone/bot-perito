import logging
import pathlib
import shutil
import time

from app.core.config import settings

logger = logging.getLogger(__name__)


def cleanup_tmp(tmp_dir: str = "/tmp") -> None:
    """Remove files older than cleanup_ttl in tmp_dir."""
    for item in pathlib.Path(tmp_dir).glob("*"):
        try:
            if time.time() - item.stat().st_mtime > settings.cleanup_ttl:
                logger.info(f"Attempting to remove old item: {item}")
                if item.is_dir():
                    shutil.rmtree(item)
                    logger.info(f"Successfully removed directory: {item}")
                else:
                    item.unlink()
                    logger.info(f"Successfully removed file/symlink: {item}")
        except FileNotFoundError:
            logger.warning(f"Item not found during cleanup (possibly already deleted): {item}")
        except OSError as e:
            logger.error(f"Error removing item {item}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error removing item {item}: {e}", exc_info=True)
