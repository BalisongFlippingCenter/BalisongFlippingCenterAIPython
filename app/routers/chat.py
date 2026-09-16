from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.bedrock_client import stream_chat
from app.config import settings

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str
    message: str
    access_token: str | None = None
    current_path: str | None = None


@router.post("/stream")
def chat_stream(request: ChatRequest, x_internal_secret: str | None = Header(default=None)) -> StreamingResponse:
    if settings.ai_service_shared_secret and x_internal_secret != settings.ai_service_shared_secret:
        raise HTTPException(status_code=401, detail="Invalid shared secret")

    return StreamingResponse(
        stream_chat(request.session_id, request.message, request.access_token, request.current_path),
        media_type="text/plain",
    )
