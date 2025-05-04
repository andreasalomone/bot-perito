import pathlib, shutil, time, threading
from app.core.config import settings

def start_tmp_sweeper(tmp_dir: str = "/tmp") -> None:
    def sweep():
        while True:
            now = time.time()
            for item in pathlib.Path(tmp_dir).glob("*"):
                if now - item.stat().st_mtime > settings.cleanup_ttl:
                    shutil.rmtree(item, ignore_errors=True)
            time.sleep(60)
    threading.Thread(target=sweep, daemon=True).start()