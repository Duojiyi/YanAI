from __future__ import annotations

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from api.support import require_admin, require_identity
from services.prompt_service import prompt_library_service


class PromptLibraryRequest(BaseModel):
    title: str = ""
    description: str = ""
    preview: str = ""
    reference_image_urls: list[str] = Field(default_factory=list)
    prompt: str = ""
    author: str = ""
    link: str = ""
    mode: str = "generate"
    image_size: str = ""
    image_count: str = ""
    icon: str = ""
    quick_access: bool = False
    sort_order: int | None = None
    category: str = ""
    sub_category: str = ""


def _prompt_response() -> dict[str, object]:
    items = prompt_library_service.list_prompts()
    return {
        "items": items,
        "prompts": items,
        "prompt_count": len(items),
    }


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/prompts")
    async def list_prompts(authorization: str | None = Header(default=None)):
        require_identity(authorization)
        return _prompt_response()

    @router.get("/api/admin/prompts")
    async def admin_list_prompts(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _prompt_response()

    @router.post("/api/admin/prompts")
    async def admin_create_prompt(body: PromptLibraryRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item = prompt_library_service.create_prompt(body.model_dump(mode="python"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, **_prompt_response()}

    @router.post("/api/admin/prompt-assets")
    @router.post("/api/admin/prompts/assets")
    async def admin_upload_prompt_asset(
            file: UploadFile = File(...),
            authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        data = await file.read()
        try:
            url = prompt_library_service.save_asset(
                data,
                filename=file.filename or "image.png",
                content_type=file.content_type or "",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail={"error": f"failed to save image asset: {exc}"}) from exc
        return {"url": url}

    @router.post("/api/admin/prompts/{prompt_id}")
    async def admin_update_prompt(
            prompt_id: str,
            body: PromptLibraryRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            item = prompt_library_service.update_prompt(prompt_id, body.model_dump(exclude_unset=True, mode="python"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "prompt not found"})
        return {"item": item, **_prompt_response()}

    @router.delete("/api/admin/prompts/{prompt_id}")
    async def admin_delete_prompt(prompt_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not prompt_library_service.delete_prompt(prompt_id):
            raise HTTPException(status_code=404, detail={"error": "prompt not found"})
        return _prompt_response()

    return router
