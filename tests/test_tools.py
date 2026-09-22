from unittest.mock import patch

from app.tools import execute_tool, get_tool_specs


def tool_names(specs):
    return [spec["toolSpec"]["name"] for spec in specs]


def test_get_tool_specs_excludes_report_content_when_logged_out():
    specs = get_tool_specs(logged_in=False)
    assert "report_content" not in tool_names(specs)


def test_get_tool_specs_includes_report_content_when_logged_in():
    specs = get_tool_specs(logged_in=True)
    assert "report_content" in tool_names(specs)


def test_get_tool_specs_always_includes_the_base_tools():
    for logged_in in (True, False):
        names = tool_names(get_tool_specs(logged_in=logged_in))
        assert "search_posts" in names
        assert "search_knife_catalog" in names
        assert "get_knife_details" in names
        assert "get_maker_details" in names
        assert "get_collection" in names
        assert "get_account_profile" in names


@patch("app.tools.search_posts")
def test_execute_tool_search_posts_forwards_input_with_defaults(mock_search_posts):
    mock_search_posts.return_value = {"content": []}
    result = execute_tool("search_posts", {"search": "rollout"})

    mock_search_posts.assert_called_once_with(
        search="rollout",
        post_type=None,
        difficulty_tag=None,
        knife_type=None,
        knife_blade_style=None,
        knife_blade_material=None,
        knife_handle_material=None,
        page=0,
        size=20,
    )
    assert result == {"content": []}


@patch("app.tools.get_account_by_id")
def test_execute_tool_get_account_profile_uses_account_id_when_given(mock_get_by_id):
    mock_get_by_id.return_value = {"id": "42"}
    result = execute_tool("get_account_profile", {"account_id": "42", "query": "ignored"})
    mock_get_by_id.assert_called_once_with("42")
    assert result == {"id": "42"}


@patch("app.tools.search_accounts")
def test_execute_tool_get_account_profile_falls_back_to_query_search(mock_search_accounts):
    mock_search_accounts.return_value = [{"id": "1"}]
    result = execute_tool("get_account_profile", {"query": "flipperguy"})
    mock_search_accounts.assert_called_once_with("flipperguy")
    assert result == {"results": [{"id": "1"}]}


@patch("app.tools.get_collection_by_account")
def test_execute_tool_get_collection(mock_get_collection):
    mock_get_collection.return_value = {"id": "col-1"}
    result = execute_tool("get_collection", {"account_id": "42"})
    mock_get_collection.assert_called_once_with("42")
    assert result == {"id": "col-1"}


@patch("app.tools.search_knife_catalog")
def test_execute_tool_search_knife_catalog_wraps_in_results(mock_search_catalog):
    mock_search_catalog.return_value = [{"slug": "51"}]
    result = execute_tool("search_knife_catalog", {"search": "benchmade"})
    mock_search_catalog.assert_called_once_with(
        search="benchmade", blade_material=None, handle_material=None, pivot_system=None, max_price=None
    )
    assert result == {"results": [{"slug": "51"}]}


@patch("app.tools.search_knife_catalog")
def test_execute_tool_search_knife_catalog_forwards_filter_params(mock_search_catalog):
    mock_search_catalog.return_value = [{"slug": "superfly"}]
    result = execute_tool(
        "search_knife_catalog",
        {"blade_material": "TITANIUM", "handle_material": "TITANIUM", "pivot_system": "BUSHING", "max_price": 300},
    )
    mock_search_catalog.assert_called_once_with(
        search=None, blade_material="TITANIUM", handle_material="TITANIUM", pivot_system="BUSHING", max_price=300
    )
    assert result == {"results": [{"slug": "superfly"}]}


@patch("app.tools.get_knife_details")
def test_execute_tool_get_knife_details(mock_get_knife_details):
    mock_get_knife_details.return_value = {"slug": "51"}
    result = execute_tool("get_knife_details", {"slug": "51"})
    mock_get_knife_details.assert_called_once_with("51")
    assert result == {"slug": "51"}


@patch("app.tools.get_maker_details")
def test_execute_tool_get_maker_details(mock_get_maker_details):
    mock_get_maker_details.return_value = {"slug": "benchmade"}
    result = execute_tool("get_maker_details", {"slug": "benchmade"})
    mock_get_maker_details.assert_called_once_with("benchmade")
    assert result == {"slug": "benchmade"}


@patch("app.tools.submit_report")
def test_execute_tool_report_content_requires_access_token(mock_submit_report):
    result = execute_tool(
        "report_content",
        {"target_type": "POST", "target_id": 1, "reason": "SPAM"},
        access_token=None,
    )
    mock_submit_report.assert_not_called()
    assert result == {"error": "No logged-in user for this session; cannot submit a report."}


@patch("app.tools.submit_report")
def test_execute_tool_report_content_submits_with_access_token(mock_submit_report):
    mock_submit_report.return_value = {"id": "report-1"}
    result = execute_tool(
        "report_content",
        {"target_type": "POST", "target_id": 1, "reason": "SPAM", "additional_note": "fake"},
        access_token="Bearer tok",
    )
    mock_submit_report.assert_called_once_with(
        access_token="Bearer tok",
        target_type="POST",
        target_id=1,
        reason="SPAM",
        additional_note="fake",
    )
    assert result == {"id": "report-1"}


def test_execute_tool_unknown_tool_returns_error():
    result = execute_tool("not_a_real_tool", {})
    assert result == {"error": "Unknown tool: not_a_real_tool"}
