import pathlib
import shutil

from app.core.config import settings


def cleanup_tmp(tmp_dir: str = "/tmp") -> None:
    """Remove files older than cleanup_ttl in tmp_dir."""
    # Remove items with modification time less than cleanup_ttl (absolute threshold)
    for item in pathlib.Path(tmp_dir).glob("*"):
        if item.stat().st_mtime < settings.cleanup_ttl:
            shutil.rmtree(item, ignore_errors=True)
