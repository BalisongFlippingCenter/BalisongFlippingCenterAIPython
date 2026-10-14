from unittest.mock import patch

import httpx
import respx

from app import web_search as web_search_module
from app.web_search import BRAVE_SEARCH_URL, web_search


@patch.object(web_search_module.settings, "brave_search_api_key", "")
def test_returns_an_error_when_no_api_key_is_configured():
    assert web_search("anything") == {"error": "Web search is not configured."}


@respx.mock
@patch.object(web_search_module.settings, "brave_search_api_key", "key")
def test_sends_the_query_and_key_and_trims_results():
    results = [{"title": f"t{i}", "url": f"https://x/{i}", "description": "d", "age": "1 day", "extra": "x"} for i in range(8)]
    route = respx.get(BRAVE_SEARCH_URL).mock(return_value=httpx.Response(200, json={"web": {"results": results}}))

    result = web_search("squid industries kraken")

    request = route.calls.last.request
    assert request.url.params["q"] == "squid industries kraken"
    assert request.headers["X-Subscription-Token"] == "key"
    assert len(result["results"]) == 5
    assert result["results"][0] == {"title": "t0", "url": "https://x/0", "description": "d", "age": "1 day"}


@respx.mock
@patch.object(web_search_module.settings, "brave_search_api_key", "key")
def test_returns_no_results_when_the_response_has_no_web_section():
    respx.get(BRAVE_SEARCH_URL).mock(return_value=httpx.Response(200, json={}))
    assert web_search("q") == {"results": []}


@respx.mock
@patch.object(web_search_module.settings, "brave_search_api_key", "key")
def test_returns_an_error_dict_on_http_status_error():
    respx.get(BRAVE_SEARCH_URL).mock(return_value=httpx.Response(429))
    result = web_search("q")
    assert result["status_code"] == 429
