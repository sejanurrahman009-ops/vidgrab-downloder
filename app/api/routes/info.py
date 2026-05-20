import asyncio
import yt_dlp
from fastapi import APIRouter, HTTPException
from app.services.downloader import QUALITY_MAP

router = APIRouter()

@router.post("/info")
async def get_media_info(payload: dict):
    """
    ভিডিওর মেটাডেটা ও ফরম্যাট লিস্ট রিটার্ন করে (ডাউনলোড ছাড়াই)।

    Body: `{ "url": "https://..." }`
    """
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=422, detail="'url' field required")

    def _extract():
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _extract)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    formats = []
    for f in info.get("formats", []):
        formats.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution") or f"{f.get('width', '?')}x{f.get('height', '?')}",
            "fps": f.get("fps"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "tbr": f.get("tbr"),
            "abr": f.get("abr"),
            "vbr": f.get("vbr"),
            "note": f.get("format_note"),
        })

    return {
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "thumbnail": info.get("thumbnail"),
        "description": (info.get("description") or "")[:500],
        "webpage_url": info.get("webpage_url"),
        "formats": formats,
    }


@router.get("/formats")
async def list_supported_formats():
    """Supported ফরম্যাট ও quality অপশন লিস্ট।"""
    return {
        "video_formats": ["mp4", "mkv", "webm", "avi", "flv", "mov"],
        "audio_formats": ["mp3", "aac", "opus", "m4a", "wav", "flac", "ogg"],
        "quality_presets": list(QUALITY_MAP.keys()),
        "audio_quality_kbps": ["320", "256", "192", "128", "64"],
    }
