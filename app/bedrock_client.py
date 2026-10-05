import json
import logging
import time
from collections.abc import Generator

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings
from app.prompts import SYSTEM_PROMPT_TEMPLATE, build_request_context
from app.sessions import get_history, save_history
from app.tools import execute_tool, get_tool_specs

log = logging.getLogger(__name__)

_client = boto3.client(
    "bedrock-runtime",
    region_name=settings.aws_region,
    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
)

RETRYABLE_ERROR_CODES = {"ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"}
MAX_STREAM_ATTEMPTS = 3


def _converse_stream_with_retry(**kwargs):
    for attempt in range(MAX_STREAM_ATTEMPTS):
        try:
            return _client.converse_stream(**kwargs)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code not in RETRYABLE_ERROR_CODES or attempt == MAX_STREAM_ATTEMPTS - 1:
                raise
            time.sleep(2**attempt)


OMITTED_TOOL_RESULT = {"note": "result omitted from history"}


def _is_turn_start(message: dict) -> bool:
    return message["role"] == "user" and any("text" in block for block in message["content"])


def _trim_history(messages: list[dict], max_turns: int) -> list[dict]:
    turn_starts = [i for i, message in enumerate(messages) if _is_turn_start(message)]
    if len(turn_starts) > max_turns:
        messages = messages[turn_starts[-max_turns]:]
    return messages


# Tool results (e.g. 20 full posts from search_posts) dominate input tokens.
# Once a turn is over, the assistant's own reply already summarizes what the
# tools found, so the raw results from earlier turns can be dropped.
def _compact_old_tool_results(messages: list[dict]) -> list[dict]:
    current_turn_start = max(i for i, message in enumerate(messages) if _is_turn_start(message))
    compacted = []
    for i, message in enumerate(messages):
        if i < current_turn_start and any("toolResult" in block for block in message["content"]):
            message = {
                "role": message["role"],
                "content": [
                    {"toolResult": {**block["toolResult"], "content": [{"json": OMITTED_TOOL_RESULT}]}}
                    if "toolResult" in block
                    else block
                    for block in message["content"]
                ],
            }
        compacted.append(message)
    return compacted


def stream_chat(
    session_id: str,
    message: str,
    access_token: str | None = None,
    current_path: str | None = None,
) -> Generator[str, None, None]:
    messages = get_history(session_id)
    messages.append({"role": "user", "content": [{"text": message}]})
    messages = _compact_old_tool_results(_trim_history(messages, settings.max_history_turns))

    # The persona/rules block never changes between requests, so it's cached
    # separately from the per-turn page path and login state -- splicing them
    # into the middle of the prompt (the old behavior) would invalidate the
    # cache on every single request regardless of the checkpoint below.
    logged_in = access_token is not None
    system = [
        {"text": SYSTEM_PROMPT_TEMPLATE},
        {"cachePoint": {"type": "default"}},
        {"text": build_request_context(current_path, logged_in)},
    ]
    tool_config = {"tools": get_tool_specs(logged_in=logged_in)}
    has_streamed_text = False

    while True:
        needs_separator = has_streamed_text
        try:
            response = _converse_stream_with_retry(
                modelId=settings.bedrock_model_id,
                messages=messages,
                system=system,
                toolConfig=tool_config,
            )
        except ClientError:
            yield "Latch is having trouble reaching the model right now — try again in a moment."
            return

        content_blocks: dict[int, dict] = {}
        stop_reason = None

        for event in response["stream"]:
            if "contentBlockDelta" in event:
                index = event["contentBlockDelta"]["contentBlockIndex"]
                delta = event["contentBlockDelta"]["delta"]
                if "text" in delta:
                    block = content_blocks.setdefault(index, {"type": "text", "text": ""})
                    block["text"] += delta["text"]
                    if needs_separator:
                        yield "\n\n"
                        needs_separator = False
                    has_streamed_text = True
                    yield delta["text"]
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
            elif "metadata" in event:
                usage = event["metadata"].get("usage", {})
                log.info(
                    "bedrock usage: input=%s output=%s cache_read=%s cache_write=%s",
                    usage.get("inputTokens"),
                    usage.get("outputTokens"),
                    usage.get("cacheReadInputTokens"),
                    usage.get("cacheWriteInputTokens"),
                )

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
