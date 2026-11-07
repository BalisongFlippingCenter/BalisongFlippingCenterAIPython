from datetime import date

from app.prompts import build_date_context, build_request_context


def test_includes_current_path_and_logged_in_state():
    assert build_request_context("/community", logged_in=True) == (
        "The user is currently viewing this page path: /community\nThe user is logged in."
    )


def test_falls_back_to_unknown_page_and_states_logged_out():
    assert build_request_context(None, logged_in=False) == (
        "The user's current page is unknown.\nThe user is NOT logged in."
    )


def test_build_date_context_spells_out_the_full_date():
    assert build_date_context(date(2026, 10, 4)) == "Today's date is Sunday, October 4, 2026."
