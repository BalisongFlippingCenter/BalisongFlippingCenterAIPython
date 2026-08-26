from fastapi import FastAPI

from app.routers import chat

app = FastAPI(title="BFC AI Service")
app.include_router(chat.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
