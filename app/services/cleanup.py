import os
import time
import asyncio
from app.core.config import DOWNLOAD_DIR, MAX_FILE_AGE_SECONDS, jobs

async def periodic_cleanup():
    """প্রতি ১০ মিনিটে পুরোনো ফাইল ও jobs মুছে ফেলে।"""
    while True:
        await asyncio.sleep(600)
        now = time.time()
        for fname in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, fname)
            if os.path.isfile(fpath) and (now - os.path.getmtime(fpath)) > MAX_FILE_AGE_SECONDS:
                safe_remove(fpath)

        stale = [jid for jid, j in list(jobs.items())
                 if now - j.get("created_at", now) > MAX_FILE_AGE_SECONDS]
        for jid in stale:
            jobs.pop(jid, None)

def safe_remove(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as exc:
        print(f"[cleanup] Could not remove {filepath}: {exc}")
