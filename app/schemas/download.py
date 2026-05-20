from typing import Optional
from pydantic import BaseModel, field_validator

class DownloadRequest(BaseModel):
    url: str
    format_id: Optional[str] = "best"          # yt-dlp format string
    media_type: Optional[str] = "video"         # "video" | "audio"
    audio_format: Optional[str] = "mp3"         # mp3 | aac | opus | m4a | wav | flac
    video_format: Optional[str] = "mp4"         # mp4 | mkv | webm | avi
    quality: Optional[str] = "best"             # best | 1080p | 720p | 480p | 360p | worst
    audio_quality: Optional[str] = "192"        # kbps: 320 | 256 | 192 | 128 | 64

    @field_validator("media_type")
    @classmethod
    def validate_media_type(cls, v):
        if v not in ("video", "audio"):
            raise ValueError("media_type must be 'video' or 'audio'")
        return v

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, v):
        allowed = {"best", "worst", "1080p", "720p", "480p", "360p", "240p", "144p"}
        if v not in allowed:
            raise ValueError(f"quality must be one of {allowed}")
        return v


class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str
