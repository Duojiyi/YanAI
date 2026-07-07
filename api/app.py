from __future__ import annotations

from contextlib import asynccontextmanager
from threading import Event

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api import accounts, ai, prompts, register, system, users
from api.support import resolve_web_asset, start_account_refresh_watcher, start_quota_reservation_watcher
from services.config import config
from services.observability import normalize_request_id, request_id_context

LONG_CACHE_PREFIXES = (
    "/_next/static/",
    "/banana-prompt-quicker/",
    "/images/",
    "/prompt-assets/",
)
LONG_CACHE_CONTROL = "public, max-age=31536000, immutable"


def create_app() -> FastAPI:
    app_version = config.app_version

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop_event = Event()
        account_refresh_thread = start_account_refresh_watcher(stop_event)
        quota_thread = start_quota_reservation_watcher(stop_event)
        config.cleanup_old_images()
        try:
            yield
        finally:
            stop_event.set()
            account_refresh_thread.join(timeout=1)
            quota_thread.join(timeout=1)

    app = FastAPI(title="chatgpt2api", version=app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request, call_next):
        with request_id_context(normalize_request_id(request.headers.get("x-request-id"))) as request_id:
            request.state.request_id = request_id
            response = await call_next(request)
            response.headers["x-request-id"] = request_id
            if any(request.url.path.startswith(prefix) for prefix in LONG_CACHE_PREFIXES):
                response.headers.setdefault("Cache-Control", LONG_CACHE_CONTROL)
            return response

    app.include_router(ai.create_router())
    app.include_router(accounts.create_router())
    app.include_router(prompts.create_router())
    app.include_router(register.create_router())
    app.include_router(users.create_router())
    app.include_router(system.create_router(app_version))
    if config.images_dir.exists():
        app.mount("/images", StaticFiles(directory=str(config.images_dir)), name="images")
    app.mount("/prompt-assets", StaticFiles(directory=str(config.prompt_assets_dir)), name="prompt-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_web(full_path: str):
        asset = resolve_web_asset(full_path)
        if asset is not None:
            return FileResponse(asset)
        if full_path.strip("/").startswith("_next/"):
            raise HTTPException(status_code=404, detail="Not Found")
        fallback = resolve_web_asset("")
        if fallback is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(fallback)

    return app
