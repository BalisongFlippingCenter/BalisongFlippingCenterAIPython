from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


@patch("app.routers.chat.stream_chat")
def test_chat_stream_returns_the_generated_text(mock_stream_chat):
    mock_stream_chat.return_value = iter(["Hello ", "there!"])

    response = client.post(
        "/chat/stream",
        json={"session_id": "s1", "message": "hi"},
    )

    assert response.status_code == 200
    assert response.text == "Hello there!"
    assert response.headers["content-type"].startswith("text/plain")


@patch("app.routers.chat.stream_chat")
def test_chat_stream_forwards_all_fields_to_stream_chat(mock_stream_chat):
    mock_stream_chat.return_value = iter(["ok"])

    client.post(
        "/chat/stream",
        json={
            "session_id": "s1",
            "message": "hi",
            "access_token": "tok",
            "current_path": "/community",
        },
    )

    mock_stream_chat.assert_called_once_with("s1", "hi", "tok", "/community")


@patch("app.routers.chat.stream_chat")
def test_chat_stream_defaults_optional_fields_to_none(mock_stream_chat):
    mock_stream_chat.return_value = iter(["ok"])

    client.post("/chat/stream", json={"session_id": "s1", "message": "hi"})

    mock_stream_chat.assert_called_once_with("s1", "hi", None, None)


def test_chat_stream_requires_session_id_and_message():
    response = client.post("/chat/stream", json={"message": "hi"})
    assert response.status_code == 422

    response = client.post("/chat/stream", json={"session_id": "s1"})
    assert response.status_code == 422


@patch("app.routers.chat.stream_chat")
def test_chat_stream_rejects_missing_shared_secret_when_one_is_configured(mock_stream_chat, monkeypatch):
    monkeypatch.setattr(settings, "ai_service_shared_secret", "internal-secret")
    response = client.post("/chat/stream", json={"session_id": "s1", "message": "hi"})
    assert response.status_code == 401
    mock_stream_chat.assert_not_called()


@patch("app.routers.chat.stream_chat")
def test_chat_stream_rejects_wrong_shared_secret(mock_stream_chat, monkeypatch):
    monkeypatch.setattr(settings, "ai_service_shared_secret", "internal-secret")
    response = client.post(
        "/chat/stream",
        json={"session_id": "s1", "message": "hi"},
        headers={"x-internal-secret": "wrong"},
    )
    assert response.status_code == 401
    mock_stream_chat.assert_not_called()


@patch("app.routers.chat.stream_chat")
def test_chat_stream_accepts_the_correct_shared_secret(mock_stream_chat, monkeypatch):
    monkeypatch.setattr(settings, "ai_service_shared_secret", "internal-secret")
    mock_stream_chat.return_value = iter(["ok"])
    response = client.post(
        "/chat/stream",
        json={"session_id": "s1", "message": "hi"},
        headers={"x-internal-secret": "internal-secret"},
    )
    assert response.status_code == 200
    mock_stream_chat.assert_called_once()
