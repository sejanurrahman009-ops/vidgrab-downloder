import os
import re
import time
import asyncio
import yt_dlp
from app.schemas.download import DownloadRequest
from app.core.config import jobs, download_semaphore, DOWNLOAD_DIR

# ──────────────────────────────────────────────────────────────────────────────
# Quality presets
# ──────────────────────────────────────────────────────────────────────────────
QUALITY_MAP = {
    "best":  "bestvideo+bestaudio/best",
    "worst": "worstvideo+worstaudio/worst",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p":  "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p":  "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "360p":  "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "240p":  "bestvideo[height<=240]+bestaudio/best[height<=240]",
    "144p":  "bestvideo[height<=144]+bestaudio/best[height<=144]",
}

# ──────────────────────────────────────────────────────────────────────────────
# Platform → cookies file mapping
# ──────────────────────────────────────────────────────────────────────────────
PLATFORM_COOKIES: dict[str, str] = {
    "youtube.com":   "youtube.txt",
    "youtu.be":      "youtube.txt",
    "instagram.com": "instagram.txt",
    "twitter.com":   "twitter.txt",
    "x.com":         "twitter.txt",
    "tiktok.com":    "tiktok.txt",
    "facebook.com":  "facebook.txt",
    "fb.watch":      "facebook.txt",
    "twitch.tv":     "twitch.txt",
    "soundcloud.com":"soundcloud.txt",
}

# ──────────────────────────────────────────────────────────────────────────────
# Realistic browser User-Agent (Chrome 124 on Windows)
# ──────────────────────────────────────────────────────────────────────────────
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _get_backend_dir() -> str:
    """Return the root backend directory (two levels above this file)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolve_ffmpeg(backend_dir: str) -> str | None:
    """Return ffmpeg bin path if it exists, else None."""
    path = os.path.join(backend_dir, "ffmpeg", "bin")
    return path if os.path.exists(path) else None


def _resolve_cookies(url: str, backend_dir: str) -> str | None:
    """
    Match URL against PLATFORM_COOKIES and return the absolute path to the
    cookies file if it exists on disk, otherwise None.
    """
    cookies_dir = os.path.join(backend_dir, "cookies")
    url_lower = url.lower()

    for domain, filename in PLATFORM_COOKIES.items():
        if domain in url_lower:
            full_path = os.path.join(cookies_dir, filename)
            if os.path.exists(full_path):
                return full_path
            # File not yet placed — log but don't crash
            print(
                f"[downloader] Cookies file not found for {domain}: {full_path}\n"
                f"             Download may fail if authentication is required."
            )
            return None

    return None  # Unknown platform — proceed without cookies


def _sanitise_pct(raw: str) -> float:
    """Strip ANSI codes and parse a percentage string to float."""
    cleaned = _ANSI_RE.sub("", raw).replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Progress hook factory
# ──────────────────────────────────────────────────────────────────────────────
def _make_progress_hook(job_id: str):
    def hook(d: dict) -> None:
        job = jobs.get(job_id)
        if not job:
            return

        status = d.get("status")

        if status == "downloading":
            job["progress"] = _sanitise_pct(d.get("_percent_str", "0%"))

            speed = d.get("speed")
            if speed:
                mb = speed / 1_048_576
                job["speed"] = f"({mb:.2f} MB/s)"
            else:
                job["speed"] = ""

            # ETA
            eta = d.get("eta")
            job["eta"] = f"{eta}s" if isinstance(eta, (int, float)) else ""

            # Total size (bytes) — useful for UI progress bars
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            job["total_bytes"] = total

            job["status"] = "downloading"

        elif status == "finished":
            job["progress"] = 100
            job["status"] = "processing"
            job["speed"] = ""
            job["eta"] = ""

        elif status == "error":
            # yt-dlp signals fragment errors here; the main except handles fatal ones
            job["status"] = "failed"
            job["error"] = str(d.get("error", "Unknown download error"))

    return hook


# ──────────────────────────────────────────────────────────────────────────────
# yt-dlp options builder
# ──────────────────────────────────────────────────────────────────────────────
def build_ydl_opts(req: DownloadRequest, job_id: str, out_dir: str) -> dict:
    backend_dir = _get_backend_dir()
    outtmpl = os.path.join(out_dir, f"{job_id}_%(title).80s.%(ext)s")

    opts: dict = {
        # ── Output ──────────────────────────────────────────────────────────
        "outtmpl": outtmpl,
        "noplaylist": True,

        # ── Logging ─────────────────────────────────────────────────────────
        "quiet": True,
        "no_warnings": True,
        "verbose": False,

        # ── Browser impersonation ────────────────────────────────────────────
        "http_headers": {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Sec-Fetch-Mode": "navigate",
        },

        # ── Retry / resilience ───────────────────────────────────────────────
        "retries": 5,                    # retry failed fragment/chunk fetches
        "fragment_retries": 5,           # retry individual DASH/HLS fragments
        "skip_unavailable_fragments": True,
        "keepvideo": False,

        # ── Network ─────────────────────────────────────────────────────────
        "socket_timeout": 30,
        "source_address": "0.0.0.0",     # use default interface

        # ── Progress ────────────────────────────────────────────────────────
        "progress_hooks": [_make_progress_hook(job_id)],

        # ── Merge format ────────────────────────────────────────────────────
        "merge_output_format": (
            req.video_format if req.media_type == "video" else None
        ),
    }

    # ── ffmpeg ───────────────────────────────────────────────────────────────
    ffmpeg_path = _resolve_ffmpeg(backend_dir)
    if ffmpeg_path:
        opts["ffmpeg_location"] = ffmpeg_path

    # ── Cookies ──────────────────────────────────────────────────────────────
    cookies_path = _resolve_cookies(req.url, backend_dir)
    if cookies_path:
        opts["cookiefile"] = cookies_path
        print(f"[downloader] Using cookies: {cookies_path}")

    # ── Format selection ─────────────────────────────────────────────────────
    if req.media_type == "audio":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": req.audio_format,
                "preferredquality": req.audio_quality,
            }
        ]
    else:
        # Use explicit format_id if provided; otherwise map quality label
        if req.format_id and req.format_id not in ("best", "worst"):
            opts["format"] = req.format_id
        else:
            opts["format"] = QUALITY_MAP.get(req.quality, QUALITY_MAP["best"])

    return opts


# ──────────────────────────────────────────────────────────────────────────────
# File-path resolution helpers
# ──────────────────────────────────────────────────────────────────────────────
def _resolve_audio_path(file_path: str, audio_format: str) -> str:
    """For audio downloads, yt-dlp changes the extension after extraction."""
    base = os.path.splitext(file_path)[0]
    return f"{base}.{audio_format}"


def _find_job_file(job_id: str, out_dir: str) -> str | None:
    """Scan output directory for any file that starts with the job_id."""
    candidates = [
        os.path.join(out_dir, f)
        for f in os.listdir(out_dir)
        if f.startswith(job_id)
    ]
    return candidates[0] if candidates else None


# ──────────────────────────────────────────────────────────────────────────────
# Main download coroutine
# ──────────────────────────────────────────────────────────────────────────────
async def run_download(job_id: str, req: DownloadRequest) -> None:
    """
    Background coroutine: download media via yt-dlp.

    Runs the blocking yt-dlp call in a thread-pool executor so the event loop
    stays responsive. Protected by ``download_semaphore`` to cap concurrency.
    """
    job = jobs[job_id]

    async with download_semaphore:
        try:
            loop = asyncio.get_event_loop()
            opts = build_ydl_opts(req, job_id, DOWNLOAD_DIR)

            # ── Blocking download (runs in executor thread) ─────────────────
            def _sync_download() -> tuple[str, dict]:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(req.url, download=True)
                    return ydl.prepare_filename(info), info

            file_path, info = await loop.run_in_executor(None, _sync_download)

            # ── Adjust path for audio extraction ───────────────────────────
            if req.media_type == "audio":
                file_path = _resolve_audio_path(file_path, req.audio_format)

            # ── Fallback: scan directory if prepared path doesn't exist ─────
            if not os.path.exists(file_path):
                fallback = _find_job_file(job_id, DOWNLOAD_DIR)
                if fallback:
                    file_path = fallback
                else:
                    raise FileNotFoundError(
                        f"Downloaded file not found. Expected: {file_path}"
                    )

            # ── Update job as completed ─────────────────────────────────────
            job.update(
                {
                    "status": "completed",
                    "progress": 100,
                    "speed": "",
                    "eta": "",
                    "file_path": file_path,
                    "file_name": os.path.basename(file_path),
                    "file_size": os.path.getsize(file_path),
                    "title": info.get("title", "media"),
                    "duration": info.get("duration"),
                    "thumbnail": info.get("thumbnail"),
                    "uploader": info.get("uploader"),
                    "uploader_url": info.get("uploader_url"),
                    "view_count": info.get("view_count"),
                    "like_count": info.get("like_count"),
                    "upload_date": info.get("upload_date"),
                    "description": (info.get("description") or "")[:500],
                    "completed_at": time.time(),
                }
            )

        except yt_dlp.utils.DownloadError as exc:
            error_msg = str(exc)

            # ── Friendly hints for common auth errors ───────────────────────
            if "Sign in" in error_msg or "login required" in error_msg.lower():
                hint = (
                    " | Fix: Export cookies from your browser and place the "
                    "file in the 'cookies/' folder. "
                    "See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp"
                )
                error_msg += hint

            elif "rate-limit" in error_msg.lower() or "rate limit" in error_msg.lower():
                hint = (
                    " | Fix: You are being rate-limited. "
                    "Try again in a few minutes or add authenticated cookies."
                )
                error_msg += hint

            elif "Private video" in error_msg:
                hint = " | Fix: This video is private. You need cookies from an account with access."
                error_msg += hint

            elif "Requested content is not available" in error_msg:
                hint = (
                    " | Fix: Content unavailable — it may be geo-restricted, "
                    "deleted, or require login. Try adding cookies."
                )
                error_msg += hint

            job.update({"status": "failed", "error": error_msg, "speed": "", "eta": ""})

        except FileNotFoundError as exc:
            job.update({"status": "failed", "error": str(exc), "speed": "", "eta": ""})

        except Exception as exc:
            job.update(
                {
                    "status": "failed",
                    "error": f"Unexpected error: {exc}",
                    "speed": "",
                    "eta": "",
                }
            )
