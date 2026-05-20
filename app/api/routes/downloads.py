import os
import time
import uuid
import asyncio
import yt_dlp
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from app.schemas.download import DownloadRequest, JobResponse
from app.core.config import jobs, DOWNLOAD_DIR
from app.services.downloader import run_download, build_ydl_opts
from app.services.cleanup import safe_remove

router = APIRouter()

@router.post("/async", response_model=JobResponse)
async def start_async_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    """
    Async job শুরু করো। job_id দিয়ে পরে status চেক করো।
    ডাউনলোড শেষ হলে `/download/file/{job_id}` থেকে ফাইল নাও।
    """
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "created_at": time.time(),
        "url": req.url,
        "media_type": req.media_type,
    }
    background_tasks.add_task(run_download, job_id, req)
    return JobResponse(job_id=job_id, status="queued", message="Download queued successfully.")


@router.post("/sync")
async def sync_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    """
    Synchronous – ডাউনলোড শেষ হলে সরাসরি ফাইল রেসপন্স দেয়।
    ছোট ফাইলের জন্য আদর্শ।
    """
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "progress": 0, "created_at": time.time()}

    # Run synchronously (blocking)
    try:
        opts = build_ydl_opts(req, job_id, DOWNLOAD_DIR)

        def _sync():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(req.url, download=True)
                return ydl.prepare_filename(info), info

        loop = asyncio.get_event_loop()
        file_path, info = await loop.run_in_executor(None, _sync)

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

        file_name = os.path.basename(file_path)
        background_tasks.add_task(safe_remove, file_path)

        return FileResponse(
            path=file_path,
            filename=file_name,
            media_type="application/octet-stream",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/status/{job_id}")
async def job_status(job_id: str):
    """Job এর বর্তমান অবস্থা জানো।"""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        **{k: v for k, v in job.items() if k != "file_path"},
    }


@router.get("/file/{job_id}")
async def download_file(job_id: str, background_tasks: BackgroundTasks):
    """Completed job এর ফাইল ডাউনলোড করো।"""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"Job is {job['status']}, not completed")

    file_path = job.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=410, detail="File no longer available")

    # Add background task to delete the file immediately after the user downloads it
    background_tasks.add_task(safe_remove, file_path)

    return FileResponse(
        path=file_path,
        filename=job.get("file_name", os.path.basename(file_path)),
        media_type="application/octet-stream",
    )


@router.delete("/cancel/{job_id}")
async def cancel_job(job_id: str):
    """Queued job বাতিল করো।"""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in ("queued",):
        raise HTTPException(status_code=409, detail=f"Cannot cancel a job that is {job['status']}")
    jobs.pop(job_id)
    return {"message": "Job cancelled"}
