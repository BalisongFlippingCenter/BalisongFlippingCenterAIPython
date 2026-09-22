import json

import httpx
import respx

from app import backend_client
from app.config import settings

BASE = settings.backend_base_url


@respx.mock
def test_search_posts_sends_only_the_provided_params():
    route = respx.get(f"{BASE}/posts/any").mock(return_value=httpx.Response(200, json={"content": []}))
    result = backend_client.search_posts(search="rollout", page=1)

    assert result == {"content": []}
    request = route.calls.last.request
    assert dict(request.url.params) == {"search": "rollout", "page": "1", "size": "20"}


@respx.mock
def test_search_posts_omits_none_params_entirely():
    route = respx.get(f"{BASE}/posts/any").mock(return_value=httpx.Response(200, json={"content": []}))
    backend_client.search_posts()

    request = route.calls.last.request
    assert dict(request.url.params) == {"page": "0", "size": "20"}


@respx.mock
def test_search_knife_catalog_hits_the_catalog_endpoint():
    respx.get(f"{BASE}/catalog/any/knives", params={"search": "benchmade"}).mock(
        return_value=httpx.Response(200, json=[{"slug": "benchmade-51"}])
    )
    result = backend_client.search_knife_catalog(search="benchmade")
    assert result == [{"slug": "benchmade-51"}]


@respx.mock
def test_search_knife_catalog_sends_filter_params_with_backend_casing():
    route = respx.get(f"{BASE}/catalog/any/knives").mock(return_value=httpx.Response(200, json=[]))
    backend_client.search_knife_catalog(
        blade_material="TITANIUM", handle_material="TITANIUM", pivot_system="BUSHING", max_price=300
    )
    request_params = dict(route.calls.last.request.url.params)
    assert request_params == {
        "bladeMaterial": "TITANIUM",
        "handleMaterial": "TITANIUM",
        "pivotSystem": "BUSHING",
        "maxPrice": "300",
    }


@respx.mock
def test_get_knife_details_uses_the_slug_in_the_path():
    respx.get(f"{BASE}/catalog/any/knives/benchmade-51").mock(
        return_value=httpx.Response(200, json={"slug": "benchmade-51", "displayName": "51"})
    )
    result = backend_client.get_knife_details("benchmade-51")
    assert result == {"slug": "benchmade-51", "displayName": "51"}


@respx.mock
def test_get_maker_details_uses_the_slug_in_the_path():
    respx.get(f"{BASE}/catalog/any/makers/benchmade").mock(
        return_value=httpx.Response(200, json={"slug": "benchmade"})
    )
    result = backend_client.get_maker_details("benchmade")
    assert result == {"slug": "benchmade"}


@respx.mock
def test_search_accounts_sends_query_param():
    respx.get(f"{BASE}/accounts/any/search", params={"q": "flipperguy"}).mock(
        return_value=httpx.Response(200, json=[{"id": "1"}])
    )
    result = backend_client.search_accounts("flipperguy")
    assert result == [{"id": "1"}]


@respx.mock
def test_get_account_by_id_uses_id_in_the_path():
    respx.get(f"{BASE}/accounts/any/42").mock(return_value=httpx.Response(200, json={"id": "42"}))
    result = backend_client.get_account_by_id("42")
    assert result == {"id": "42"}


@respx.mock
def test_get_collection_by_account_uses_id_in_the_path():
    respx.get(f"{BASE}/collection/any/account/42").mock(return_value=httpx.Response(200, json={"id": "col-1"}))
    result = backend_client.get_collection_by_account("42")
    assert result == {"id": "col-1"}


@respx.mock
def test_submit_report_posts_json_body_with_auth_header():
    route = respx.post(f"{BASE}/reports").mock(return_value=httpx.Response(200, json={"id": "report-1"}))
    result = backend_client.submit_report(
        access_token="Bearer tok",
        target_type="POST",
        target_id=7,
        reason="SPAM",
        additional_note="looks fake",
    )

    assert result == {"id": "report-1"}
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tok"
    assert json.loads(request.content) == {
        "targetType": "POST",
        "targetId": 7,
        "reason": "SPAM",
        "additionalNote": "looks fake",
    }


@respx.mock
def test_get_returns_error_dict_on_http_status_error():
    respx.get(f"{BASE}/catalog/any/knives/missing-slug").mock(return_value=httpx.Response(404))
    result = backend_client.get_knife_details("missing-slug")
    assert result["status_code"] == 404
    assert "error" in result


@respx.mock
def test_get_returns_error_dict_on_connection_error():
    respx.get(f"{BASE}/catalog/any/knives/unreachable").mock(side_effect=httpx.ConnectError("boom"))
    result = backend_client.get_knife_details("unreachable")
    assert "error" in result
    assert "status_code" not in result


@respx.mock
def test_post_returns_error_dict_on_http_status_error():
    respx.post(f"{BASE}/reports").mock(return_value=httpx.Response(401, json={"message": "unauthorized"}))
    result = backend_client.submit_report(
        access_token="bad-token", target_type="POST", target_id=1, reason="SPAM", additional_note=None
    )
    assert result["status_code"] == 401
