from fastapi import APIRouter
from app.core.config import jobs

router = APIRouter()

@router.get("/health")
async def health():
    """সার্ভার লাইভ কিনা চেক করো।"""
    # Note: app.version is usually accessed via request.app.version, but we'll hardcode or remove
    return {
        "status": "ok",
        "version": "2.0.0",
        "active_jobs": len([j for j in jobs.values() if j["status"] in ("queued", "downloading", "processing")]),
    }
