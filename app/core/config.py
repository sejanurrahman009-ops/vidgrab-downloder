import os
import asyncio

# ──────────────────────────────────────────────
# Config / Constants
# ──────────────────────────────────────────────
DOWNLOAD_DIR = "temp_downloads"
MAX_FILE_AGE_SECONDS = 900        # ১৫ মিনিট পর অটো-ক্লিন
MAX_CONCURRENT_DOWNLOADS = 5      # একসাথে সর্বোচ্চ ডাউনলোড
API_VERSION = "v1"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Active download semaphore (rate limiting)
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# In-memory job tracker  { job_id: { status, progress, file_path, error, ... } }
jobs: dict[str, dict] = {}
