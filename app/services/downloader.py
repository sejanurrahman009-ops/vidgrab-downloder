import os
import time
import asyncio
import yt_dlp
from app.schemas.download import DownloadRequest
from app.core.config import jobs, download_semaphore, DOWNLOAD_DIR

# Quality mapping for video downloads
QUALITY_MAP = {
    "best":  "bestvideo+bestaudio/best",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p":  "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p":  "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "360p":  "bestvideo[height<=360]+bestaudio/best[height<=360]",
}

def build_ydl_opts(req: DownloadRequest, job_id: str, out_dir: str) -> dict:
    # Output template for downloaded files
    outtmpl = os.path.join(out_dir, f"{job_id}_%(title).80s.%(ext)s")
    
    opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_make_progress_hook(job_id)],
        # Bot detection avoidance settings
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios"],
                "player_skip": ["webpage"],
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        }
    }

    if req.media_type == "audio":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        opts["format"] = QUALITY_MAP.get(req.quality, QUALITY_MAP["best"])

    return opts

def _make_progress_hook(job_id: str):
    def hook(d):
        job = jobs.get(job_id)
        if job and d["status"] == "downloading":
            job["status"] = "downloading"
    return hook

async def run_download(job_id: str, req: DownloadRequest):
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
            
            job.update({
                "status": "completed", 
                "file_path": file_path, 
                "title": info.get("title", "Unknown Title"),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail")
            })
        except Exception as exc:
            error_str = str(exc)
            # YouTube bot detection error handling
            if "Sign in to confirm" in error_str or "bot" in error_str.lower():
                job.update({
                    "status": "failed", 
                    "error": "YouTube is currently unsupported due to API restrictions. Try Facebook, Instagram, or TikTok!"
                })
            else:
                job.update({"status": "failed", "error": f"Error: {error_str}"})
