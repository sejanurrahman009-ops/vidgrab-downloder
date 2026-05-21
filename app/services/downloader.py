import os
import time
import asyncio
import yt_dlp
from app.schemas.download import DownloadRequest
from app.core.config import jobs, download_semaphore, DOWNLOAD_DIR

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

def build_ydl_opts(req: DownloadRequest, job_id: str, out_dir: str) -> dict:
    outtmpl = os.path.join(out_dir, f"{job_id}_%(title).80s.%(ext)s")

    opts: dict = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_make_progress_hook(job_id)],
        "merge_output_format": req.video_format if req.media_type == "video" else None,
        
        # ──────────────────────────────────────────────
        # OAuth এবং ক্লায়েন্ট অপশন বাইপাস (YouTube এর নতুন সিকিউরিটির জন্য)
        # ──────────────────────────────────────────────
        "compat_opts": ["no-youtube-client-side-player"],
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web", "tv"],
                "skip": ["dash", "hls"]
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
    }

    # Ensure ffmpeg_location is absolute based on the backend directory
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ffmpeg_path = os.path.join(backend_dir, "ffmpeg", "bin")
    if os.path.exists(ffmpeg_path):
        opts["ffmpeg_location"] = ffmpeg_path

    if req.media_type == "audio":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": req.audio_format,
            "preferredquality": req.audio_quality,
        }]
    else:
        if req.format_id and req.format_id not in ("best", "worst"):
            opts["format"] = req.format_id
        else:
            opts["format"] = QUALITY_MAP.get(req.quality, QUALITY_MAP["best"])

    return opts

def _make_progress_hook(job_id: str):
    def hook(d):
        job = jobs.get(job_id)
        if not job:
            return
        if d["status"] == "downloading":
            pct_str = d.get("_percent_str", "0%").strip()
            import re
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            pct_str = ansi_escape.sub('', pct_str).replace('%', '')
            try:
                job["progress"] = float(pct_str)
            except ValueError:
                job["progress"] = 0

            speed = d.get("speed")
            job["speed"] = f"({speed / 1024 / 1024:.2f} MB/s)" if speed else ""
            job["status"] = "downloading"
        elif d["status"] == "finished":
            job["progress"] = 100
            job["status"] = "processing"
    return hook

async def run_download(job_id: str, req: DownloadRequest):
    """Background coroutine: actually download the media."""
    job = jobs[job_id]
    async with download_semaphore:
        try:
            loop = asyncio.get_event_loop()
            opts = build_ydl_opts(req, job_id, DOWNLOAD_DIR)

            def _sync_download():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(req.url, download=True)
                    return ydl.prepare_filename(info), info

            file_path, info = await loop.run_in_executor(None, _sync_download)

            if req.media_type == "audio":
                base = os.path.splitext(file_path)[0]
                file_path = f"{base}.{req.audio_format}"

            if not os.path.exists(file_path):
                candidates = [
                    os.path.join(DOWNLOAD_DIR, f)
                    for f in os.listdir(DOWNLOAD_DIR)
                    if f.startswith(job_id)
                ]
                file_path = candidates[0] if candidates else file_path

            job.update({
                "status": "completed",
                "progress": 100,
                "file_path": file_path,
                "file_name": os.path.basename(file_path),
                "title": info.get("title", "media"),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
                "uploader": info.get("uploader"),
                "completed_at": time.time(),
            })
        except Exception as exc:
            job.update({"status": "failed", "error": str(exc)})
