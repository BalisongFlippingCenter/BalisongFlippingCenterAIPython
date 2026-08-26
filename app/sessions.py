_sessions: dict[str, list[dict]] = {}


def get_history(session_id: str) -> list[dict]:
    return _sessions.setdefault(session_id, [])


def save_history(session_id: str, messages: list[dict]) -> None:
    _sessions[session_id] = messages
