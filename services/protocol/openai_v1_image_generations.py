from __future__ import annotations

from typing import Any, Iterator

from services.protocol.conversation import (
    ConversationRequest,
    collect_image_outputs,
    stream_image_chunks,
    stream_image_outputs_with_pool,
)


def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    prompt = str(body.get("prompt") or "")
    model = str(body.get("model") or "gpt-image-2")
    n = int(body.get("n") or 1)
    size = body.get("size")
    response_format = str(body.get("response_format") or "url")
    base_url = str(body.get("base_url") or "") or None
    request_id = str(body.get("request_id") or "")
    storage_identity = body.get("_image_storage_identity")
    if not isinstance(storage_identity, dict):
        storage_identity = None
    outputs = stream_image_outputs_with_pool(ConversationRequest(
        prompt=prompt,
        model=model,
        n=n,
        size=size,
        response_format=response_format,
        base_url=base_url,
        request_id=request_id,
        image_storage_identity=storage_identity,
        message_as_error=True,
    ))
    if body.get("stream"):
        return stream_image_chunks(outputs)
    return collect_image_outputs(outputs)
