import pathlib
import shutil
import time

from app.core.config import settings


def cleanup_tmp(tmp_dir: str = "/tmp") -> None:
    """Remove files older than cleanup_ttl in tmp_dir."""
    now = time.time()
    for item in pathlib.Path(tmp_dir).glob("*"):
        if now - item.stat().st_mtime > settings.cleanup_ttl:
            shutil.rmtree(item, ignore_errors=True)
