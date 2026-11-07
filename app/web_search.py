import httpx

from app.config import settings

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_RESULTS = 5

_client = httpx.Client(timeout=10.0)


def web_search(query: str) -> dict:
    if not settings.brave_search_api_key:
        return {"error": "Web search is not configured."}
    try:
        response = _client.get(
            BRAVE_SEARCH_URL,
            params={"q": query, "count": MAX_RESULTS},
            headers={"Accept": "application/json", "X-Subscription-Token": settings.brave_search_api_key},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return {"error": str(e), "status_code": e.response.status_code}
    except httpx.RequestError as e:
        return {"error": str(e)}

    results = response.json().get("web", {}).get("results", [])
    return {
        "results": [
            {
                "title": result.get("title"),
                "url": result.get("url"),
                "description": result.get("description"),
                "age": result.get("age"),
            }
            for result in results[:MAX_RESULTS]
        ]
    }
