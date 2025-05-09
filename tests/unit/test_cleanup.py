import pathlib
import shutil
import time

from app.core.cleanup import cleanup_tmp
from app.core.config import settings


def test_cleanup_tmp(monkeypatch):
    # Create dummy items with varying modification times
    class DummyItem:
        def __init__(self, mtime):
            self._mtime = mtime

        def stat(self):
            return type("stat", (), {"st_mtime": self._mtime})()

    old_item = DummyItem(mtime=0)
    new_item = DummyItem(mtime=1000)

    # Monkeypatch time.time to fixed value
    monkeypatch.setattr(time, "time", lambda: 1500)

    # Monkeypatch Path.glob to return our dummy items
    monkeypatch.setattr(
        pathlib.Path,
        "glob",
        lambda self, pattern: [old_item, new_item],
    )

    # Capture rmtree calls
    removed = []
    monkeypatch.setattr(
        shutil,
        "rmtree",
        lambda path, ignore_errors: removed.append(path),
    )

    # Set TTL to 200 seconds
    monkeypatch.setattr(settings, "cleanup_ttl", 200, raising=False)

    # Execute cleanup
    cleanup_tmp(tmp_dir="dummy")

    # Only the old item should have been removed
    assert removed == [old_item]
