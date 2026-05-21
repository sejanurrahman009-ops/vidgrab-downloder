import os
import time
import asyncio
import yt_dlp
import random
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

# ২০২৬ সালের কার্যকরী কিছু ফ্রি পাবলিক প্রক্সি লিস্ট (Render IP ব্লক বাইপাস করার জন্য)
FREE_PROXIES = [
    "http://45.70.198.90:8080",
    "http://185.121.139.14:80",
    "http://200.105.215.18:8080",
    "http://190.61.44.186:8080",
    "http://45.160.40.1:8080",
]

def build_ydl_opts(req: DownloadRequest, job_id: str, out_dir: str) -> dict:
    outtmpl = os.path.join(out_dir, f"{job_id}_%(title).80s.%(ext)s")

    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cookies_path = os.path.join(backend_dir, "cookies.txt")

    opts: dict = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_make_progress_hook(job_id)],
        "merge_output_format": req.video_format if req.media_type == "video" else None,
        
        # ──────────────────────────────────────────────
        # ১. রিয়েল কুকিজ পাথ লিংকিং
        # ──────────────────────────────────────────────
        "cookiefile": cookies_path if os.path.exists(cookies_path) else None,
        
        # ──────────────────────────────────────────────
        # ২. ফ্রি প্রক্সি রোটেশন যুক্ত করা হলো (Render IP বাইপাস)
        # ──────────────────────────────────────────────
        "proxy": random.choice(FREE_PROXIES),
        
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "android"],
                "player_skip": ["webpage", "configs"],
            }
        },
        "http_headers": {
            "User-Agent": "com.google.ios.youtube/19.12.3 (iPhone16,2; U; CPU iPhone OS 17_4 like Mac OS X; en_US)",
            "Accept-Language": "en-US,en;q=0.9",
        }
    }

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
            # যদি প্রথম প্রক্সি ফেইল করে, প্রক্সি ছাড়া শেষ একটা ট্রাই মারবে ব্যাকআপ হিসেবে
            try:
                opts = build_ydl_opts(req, job_id, DOWNLOAD_DIR)
                if "proxy" in opts:
                    del opts["proxy"]
                def _sync_download_fallback():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(req.url, download=True)
                        return ydl.prepare_filename(info), info
                file_path, info = await loop.run_in_executor(None, _sync_download_fallback)
                # ... বাকি সেম সাকসেস লজিক
                job.update({
                    "status": "completed", "progress": 100, "file_path": file_path,
                    "file_name": os.path.basename(file_path), "title": info.get("title", "media")
                })
            except Exception:
                job.update({"status": "failed", "error": str(exc)})
