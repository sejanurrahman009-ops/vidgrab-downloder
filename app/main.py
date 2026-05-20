import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import API_VERSION
from app.services.cleanup import periodic_cleanup
from app.api.routes import health, info, downloads

# ──────────────────────────────────────────────
# Lifespan – background cleaner
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(periodic_cleanup())
    yield
    task.cancel()

# ──────────────────────────────────────────────
# App bootstrap
# ──────────────────────────────────────────────
app = FastAPI(
    title="VibeLoader API",
    description="Industry-grade video/audio downloader — multiple formats, async jobs, progress tracking.",
    version="2.0.0",
    docs_url=f"/api/{API_VERSION}/docs",
    redoc_url=f"/api/{API_VERSION}/redoc",
    openapi_url=f"/api/{API_VERSION}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ──────────────────────────────────────────────
# Routes – UI
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home(request: Request):
    return templates.TemplateResponse(name="index.html", context={"request": request})



# ──────────────────────────────────────────────
# Routes – API v1
# ──────────────────────────────────────────────
BASE = f"/api/{API_VERSION}"

app.include_router(health.router, prefix=BASE, tags=["Health"])
app.include_router(info.router, prefix=BASE, tags=["Info & Formats"])
app.include_router(downloads.router, prefix=f"{BASE}/download", tags=["Downloads"])

