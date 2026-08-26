from typing import Any

from app.backend_client import (
    get_account_by_id,
    get_collection_by_account,
    search_accounts,
    search_posts,
    submit_report,
)

TARGET_TYPES = ["POST", "COMMENT", "PROFILE", "CONVERSATION", "MESSAGE"]
REPORT_REASONS = [
    "SPAM",
    "ILLEGAL_LISTING",
    "UNSAFE_CONTENT",
    "INAPPROPRIATE_CONTENT",
    "HARASSMENT",
    "MISINFORMATION",
    "OTHER",
    "INAPPROPRIATE_IMAGE",
    "INAPPROPRIATE_NAME",
    "INAPPROPRIATE_BIO",
]

BASE_TOOL_SPECS = [
    {
        "toolSpec": {
            "name": "search_posts",
            "description": (
                "Search Balisong Flipping Center posts (tricks, tutorials, showcases) "
                "by free text, knife attributes, or trick difficulty."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "search": {"type": "string", "description": "Free-text search term"},
                        "post_type": {"type": "string", "description": "Type of post"},
                        "difficulty_tag": {"type": "string", "description": "Trick difficulty tag"},
                        "knife_type": {"type": "string", "description": "Balisong knife type"},
                        "knife_blade_style": {"type": "string", "description": "Blade style"},
                        "knife_blade_material": {"type": "string", "description": "Blade material"},
                        "knife_handle_material": {"type": "string", "description": "Handle material"},
                        "page": {"type": "integer", "description": "Page number, 0-indexed. Default 0."},
                        "size": {"type": "integer", "description": "Results per page. Default 20."},
                    },
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_account_profile",
            "description": (
                "Look up a Balisong Flipping Center user's public profile. "
                "Provide account_id if already known, otherwise search by display name."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Display name or partial name to search for"},
                        "account_id": {"type": "string", "description": "Exact account ID, if already known"},
                    },
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_collection",
            "description": "Get a user's public balisong knife collection by their account ID.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "Account ID of the collection owner"},
                    },
                    "required": ["account_id"],
                }
            },
        }
    },
]

REPORT_TOOL_SPEC = {
    "toolSpec": {
        "name": "report_content",
        "description": (
            "Submit a report to flag a post, comment, profile, conversation, or message for moderator "
            "review, on behalf of the logged-in user. Only call this once you're confident which specific "
            "item is being reported."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "target_type": {"type": "string", "enum": TARGET_TYPES, "description": "Kind of content being reported"},
                    "target_id": {"type": "integer", "description": "Numeric ID of the item being reported"},
                    "reason": {"type": "string", "enum": REPORT_REASONS, "description": "Reason for the report"},
                    "additional_note": {"type": "string", "description": "Optional extra context from the user"},
                },
                "required": ["target_type", "target_id", "reason"],
            }
        },
    }
}


def get_tool_specs(logged_in: bool) -> list[dict]:
    if logged_in:
        return BASE_TOOL_SPECS + [REPORT_TOOL_SPEC]
    return BASE_TOOL_SPECS


def execute_tool(name: str, tool_input: dict[str, Any], access_token: str | None = None) -> dict[str, Any]:
    if name == "search_posts":
        return search_posts(
            search=tool_input.get("search"),
            post_type=tool_input.get("post_type"),
            difficulty_tag=tool_input.get("difficulty_tag"),
            knife_type=tool_input.get("knife_type"),
            knife_blade_style=tool_input.get("knife_blade_style"),
            knife_blade_material=tool_input.get("knife_blade_material"),
            knife_handle_material=tool_input.get("knife_handle_material"),
            page=tool_input.get("page", 0),
            size=tool_input.get("size", 20),
        )
    if name == "get_account_profile":
        account_id = tool_input.get("account_id")
        if account_id:
            return get_account_by_id(account_id)
        return {"results": search_accounts(tool_input.get("query", ""))}
    if name == "get_collection":
        return get_collection_by_account(tool_input["account_id"])
    if name == "report_content":
        if not access_token:
            return {"error": "No logged-in user for this session; cannot submit a report."}
        return submit_report(
            access_token=access_token,
            target_type=tool_input["target_type"],
            target_id=tool_input["target_id"],
            reason=tool_input["reason"],
            additional_note=tool_input.get("additional_note"),
        )
    return {"error": f"Unknown tool: {name}"}
