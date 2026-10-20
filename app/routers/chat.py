from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.bedrock_client import stream_chat
from app.config import settings
from app.sessions import clear_history

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str
    message: str
    access_token: str | None = None
    current_path: str | None = None
    client: str = "website"


def _require_shared_secret(x_internal_secret: str | None) -> None:
    if settings.ai_service_shared_secret and x_internal_secret != settings.ai_service_shared_secret:
        raise HTTPException(status_code=401, detail="Invalid shared secret")


@router.post("/stream")
def chat_stream(request: ChatRequest, x_internal_secret: str | None = Header(default=None)) -> StreamingResponse:
    _require_shared_secret(x_internal_secret)

    return StreamingResponse(
        stream_chat(request.session_id, request.message, request.access_token, request.current_path, request.client),
        media_type="text/plain",
    )


@router.delete("/session/{session_id}", status_code=204)
def delete_session(session_id: str, x_internal_secret: str | None = Header(default=None)) -> Response:
    _require_shared_secret(x_internal_secret)
    clear_history(session_id)
    return Response(status_code=204)
