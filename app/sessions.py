import json

import redis

from app.config import settings

_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

SESSION_TTL_SECONDS = 60 * 60 * 24


def get_history(session_id: str) -> list[dict]:
    raw = _client.get(f"session:{session_id}")
    return json.loads(raw) if raw else []


def save_history(session_id: str, messages: list[dict]) -> None:
    _client.set(f"session:{session_id}", json.dumps(messages), ex=SESSION_TTL_SECONDS)
