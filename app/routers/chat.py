from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.bedrock_client import stream_chat

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str
    message: str
    access_token: str | None = None
    current_path: str | None = None


@router.post("/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_chat(request.session_id, request.message, request.access_token, request.current_path),
        media_type="text/plain",
    )
