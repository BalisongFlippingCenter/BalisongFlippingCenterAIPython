from app import sessions


def test_get_history_returns_empty_list_for_new_session():
    assert sessions.get_history("new-session") == []


def test_save_then_get_round_trips_through_json():
    sessions.save_history("s1", [{"role": "user", "content": [{"text": "hi"}]}])
    assert sessions.get_history("s1") == [{"role": "user", "content": [{"text": "hi"}]}]


def test_save_history_overwrites_existing_session():
    sessions.save_history("s1", [{"role": "user", "content": [{"text": "one"}]}])
    sessions.save_history("s1", [{"role": "user", "content": [{"text": "two"}]}])
    assert sessions.get_history("s1") == [{"role": "user", "content": [{"text": "two"}]}]


def test_sessions_are_isolated_by_session_id():
    sessions.save_history("a", [{"role": "user", "content": [{"text": "a-msg"}]}])
    sessions.save_history("b", [{"role": "user", "content": [{"text": "b-msg"}]}])
    assert sessions.get_history("a") == [{"role": "user", "content": [{"text": "a-msg"}]}]
    assert sessions.get_history("b") == [{"role": "user", "content": [{"text": "b-msg"}]}]


def test_save_history_sets_a_ttl(fake_redis):
    sessions.save_history("s1", [{"role": "user", "content": [{"text": "hi"}]}])
    ttl = fake_redis.ttl("session:s1")
    assert 0 < ttl <= sessions.SESSION_TTL_SECONDS
