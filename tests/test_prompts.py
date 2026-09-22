from app.prompts import build_page_context


def test_includes_current_path_when_provided():
    assert build_page_context("/community") == "The user is currently viewing this page path: /community"


def test_falls_back_to_unknown_page_when_path_is_none():
    assert build_page_context(None) == "The user's current page is unknown."
