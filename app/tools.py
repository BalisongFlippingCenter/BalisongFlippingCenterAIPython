from typing import Any

from app.backend_client import (
    get_account_by_id,
    get_collection_by_account,
    get_knife_details,
    get_maker_details,
    search_accounts,
    search_knife_catalog,
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
# Mirrors the backend's enums -- free-text guesses like "tutorial" are rejected with a 409.
POST_TYPES = ["GENERIC", "BUY_SELL", "TRADE", "TRICK_TUTORIAL", "COMBO"]
DIFFICULTY_TAGS = ["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]
KNIFE_TYPES = ["LIVE_BLADE", "TRAINER", "BOTH"]
BLADE_STYLES = [
    "TANTO", "BOWIE", "KUKRI", "JAPANESE_TANTO", "SPEAR_POINT", "WEEHAWK", "AMERICAN_TANTO", "HORSE_SHOE",
    "CLIP_POINT", "DROP_POINT", "WHARNCLIFFE", "SHEEPSFOOT", "DAGGER", "OTHER",
]
BLADE_MATERIALS = [
    "ALUMINIUM", "STAINLESS_STEEL", "TITANIUM", "D2", "S35VN", "S32VN", "ALUMINIUM_6061", "HARDENED_STEEL",
    "PLASTIC", "ALUMINIUM_7075", "M390", "ELMAX", "STEEL_154CM", "STEEL_14C28N", "MAGNACUT", "DAMASCUS",
    "AUS_10", "AEB_L", "STEEL_12C27", "STEEL_440C", "CPVC", "ACETAL", "ULTEM", "HDPE", "OTHER",
]
HANDLE_MATERIALS = [
    "TITANIUM", "ALUMINIUM", "STAINLESS_STEEL", "G_10", "G_10_TITANIUM", "G_10_ALUMINIUM", "PLASTIC",
    "HARDENED_STEEL", "ALUMINIUM_6061", "ALUMINIUM_7075", "CARBON_FIBER", "BRASS", "COPPER", "CPVC", "ACETAL",
    "ULTEM", "HDPE", "OTHER",
]
PIVOT_SYSTEMS = ["BEARINGS", "BUSHINGS", "WASHERS", "OTHER"]

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
                        "post_type": {
                            "type": "string",
                            "enum": POST_TYPES,
                            "description": (
                                "TRICK_TUTORIAL for trick tutorials, COMBO for combo breakdowns, BUY_SELL for "
                                "knives for sale or wanted, TRADE for trade offers, GENERIC for everything else"
                            ),
                        },
                        "difficulty_tag": {"type": "string", "enum": DIFFICULTY_TAGS, "description": "Trick difficulty"},
                        "knife_type": {"type": "string", "enum": KNIFE_TYPES, "description": "Balisong knife type"},
                        "knife_blade_style": {"type": "string", "enum": BLADE_STYLES, "description": "Blade style"},
                        "knife_blade_material": {"type": "string", "enum": BLADE_MATERIALS, "description": "Blade material"},
                        "knife_handle_material": {"type": "string", "enum": HANDLE_MATERIALS, "description": "Handle material"},
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
            "description": (
                "Get a user's public balisong knife collection by their account ID. If you only know their "
                "display name, call get_account_profile first and use the accountId from its result."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "account_id": {
                            "type": "string",
                            "description": "Account ID of the collection owner (the accountId field from get_account_profile), never a display name or identifier code",
                        },
                    },
                    "required": ["account_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "search_knife_catalog",
            "description": (
                "Search or filter the Balisong Flipping Center knife reference catalog. Use this for questions "
                "about specific balisong models or makers — specs, pricing, release history — or to find knives "
                "matching given criteria (e.g. \"titanium handle under $300\"). Separate from search_posts, "
                "which searches community marketplace and trick posts, not the reference catalog. Filters "
                "combine with AND; omit any you don't need."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "search": {
                            "type": "string",
                            "description": (
                                "A knife name OR a maker name, never both together -- the search matches one or "
                                "the other, so \"Squid Industries Tsunami\" finds nothing while \"Tsunami\" works. "
                                "Omit to consider the full catalog."
                            ),
                        },
                        "blade_material": {
                            "type": "string",
                            "enum": BLADE_MATERIALS,
                            "description": "Filter to knives with at least one variant in this blade material.",
                        },
                        "handle_material": {
                            "type": "string",
                            "enum": HANDLE_MATERIALS,
                            "description": "Filter to knives with at least one version in this handle material.",
                        },
                        "pivot_system": {
                            "type": "string",
                            "enum": PIVOT_SYSTEMS,
                            "description": "Filter to knives with at least one version using this pivot system.",
                        },
                        "max_price": {
                            "type": "number",
                            "description": "Filter to knives with at least one variant priced at or below this MSRP.",
                        },
                    },
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_knife_details",
            "description": (
                "Get full details for a specific knife from the reference catalog — every version, its "
                "variants, specs, pricing, and where to buy. Requires the knife's slug, from a prior "
                "search_knife_catalog result."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string", "description": "Knife slug, from search_knife_catalog results"},
                    },
                    "required": ["slug"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_maker_details",
            "description": (
                "Get details about a balisong maker/brand from the reference catalog, including their "
                "listed knives. Requires the maker's slug, from a prior search_knife_catalog result's "
                "makerSlug field."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string", "description": "Maker slug, from search_knife_catalog results' makerSlug field"},
                    },
                    "required": ["slug"],
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
    if name == "search_knife_catalog":
        return {
            "results": search_knife_catalog(
                search=tool_input.get("search"),
                blade_material=tool_input.get("blade_material"),
                handle_material=tool_input.get("handle_material"),
                pivot_system=tool_input.get("pivot_system"),
                max_price=tool_input.get("max_price"),
            )
        }
    if name == "get_knife_details":
        return get_knife_details(tool_input["slug"])
    if name == "get_maker_details":
        return get_maker_details(tool_input["slug"])
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
