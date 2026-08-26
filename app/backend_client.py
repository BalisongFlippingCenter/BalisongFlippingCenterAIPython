import httpx

from app.config import settings

_client = httpx.Client(base_url=settings.backend_base_url, timeout=10.0)


def _get(path: str, params: dict | None = None) -> dict:
    try:
        response = _client.get(path, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        return {"error": str(e), "status_code": e.response.status_code}
    except httpx.RequestError as e:
        return {"error": str(e)}


def _post(path: str, json_body: dict, access_token: str) -> dict:
    try:
        response = _client.post(path, json=json_body, headers={"Authorization": access_token})
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        return {"error": str(e), "status_code": e.response.status_code}
    except httpx.RequestError as e:
        return {"error": str(e)}


def search_posts(
    search: str | None = None,
    post_type: str | None = None,
    difficulty_tag: str | None = None,
    knife_type: str | None = None,
    knife_blade_style: str | None = None,
    knife_blade_material: str | None = None,
    knife_handle_material: str | None = None,
    page: int = 0,
    size: int = 20,
) -> dict:
    params = {
        "search": search,
        "postType": post_type,
        "difficultyTag": difficulty_tag,
        "knifeType": knife_type,
        "knifeBladeStyle": knife_blade_style,
        "knifeBladeMaterial": knife_blade_material,
        "knifeHandleMaterial": knife_handle_material,
        "page": page,
        "size": size,
    }
    params = {k: v for k, v in params.items() if v is not None}
    return _get("/posts/any", params)


def search_accounts(query: str) -> dict:
    return _get("/accounts/any/search", {"q": query})


def get_account_by_id(account_id: str) -> dict:
    return _get(f"/accounts/any/{account_id}")


def get_collection_by_account(account_id: str) -> dict:
    return _get(f"/collection/any/account/{account_id}")


def submit_report(
    access_token: str,
    target_type: str,
    target_id: int,
    reason: str,
    additional_note: str | None,
) -> dict:
    return _post(
        "/reports",
        {
            "targetType": target_type,
            "targetId": target_id,
            "reason": reason,
            "additionalNote": additional_note,
        },
        access_token,
    )
