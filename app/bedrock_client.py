import json
from collections.abc import Generator

import boto3

from app.config import settings
from app.prompts import build_system_prompt
from app.sessions import get_history, save_history
from app.tools import execute_tool, get_tool_specs

_client = boto3.client("bedrock-runtime", region_name=settings.aws_region)


def stream_chat(
    session_id: str,
    message: str,
    access_token: str | None = None,
    current_path: str | None = None,
) -> Generator[str, None, None]:
    messages = get_history(session_id)
    messages.append({"role": "user", "content": [{"text": message}]})

    system_prompt = build_system_prompt(current_path)
    tool_config = {"tools": get_tool_specs(logged_in=access_token is not None)}

    while True:
        response = _client.converse_stream(
            modelId=settings.bedrock_model_id,
            messages=messages,
            system=[{"text": system_prompt}],
            toolConfig=tool_config,
        )

        content_blocks: dict[int, dict] = {}
        stop_reason = None

        for event in response["stream"]:
            if "contentBlockDelta" in event:
                index = event["contentBlockDelta"]["contentBlockIndex"]
                delta = event["contentBlockDelta"]["delta"]
                if "text" in delta:
                    block = content_blocks.setdefault(index, {"type": "text", "text": ""})
                    block["text"] += delta["text"]
                elif "toolUse" in delta:
                    block = content_blocks[index]
                    block["input_json"] += delta["toolUse"]["input"]
            elif "contentBlockStart" in event:
                start = event["contentBlockStart"]["start"]
                index = event["contentBlockStart"]["contentBlockIndex"]
                if "toolUse" in start:
                    content_blocks[index] = {
                        "type": "toolUse",
                        "toolUseId": start["toolUse"]["toolUseId"],
                        "name": start["toolUse"]["name"],
                        "input_json": "",
                    }
            elif "messageStop" in event:
                stop_reason = event["messageStop"]["stopReason"]

        assistant_content = []
        tool_uses = []
        for index in sorted(content_blocks):
            block = content_blocks[index]
            if block["type"] == "text":
                assistant_content.append({"text": block["text"]})
            else:
                tool_input = json.loads(block["input_json"]) if block["input_json"] else {}
                assistant_content.append(
                    {
                        "toolUse": {
                            "toolUseId": block["toolUseId"],
                            "name": block["name"],
                            "input": tool_input,
                        }
                    }
                )
                tool_uses.append((block["toolUseId"], block["name"], tool_input))

        messages.append({"role": "assistant", "content": assistant_content})

        if stop_reason != "tool_use":
            for block in assistant_content:
                if "text" in block:
                    yield block["text"]
            save_history(session_id, messages)
            break

        tool_result_content = [
            {
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [{"json": execute_tool(name, tool_input, access_token)}],
                }
            }
            for tool_use_id, name, tool_input in tool_uses
        ]
        messages.append({"role": "user", "content": tool_result_content})
