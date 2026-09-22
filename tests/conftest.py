import fakeredis
import pytest

from app import sessions


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(sessions, "_client", client)
    yield client
    client.flushall()
