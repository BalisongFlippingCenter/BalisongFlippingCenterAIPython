import copy
import json
from unittest.mock import patch

from botocore.exceptions import ClientError

from app import sessions
from app.bedrock_client import stream_chat


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "ConverseStream")


def text_response_stream(text: str, stop_reason: str = "end_turn"):
    return {
        "stream": [
            {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": text}}},
            {"messageStop": {"stopReason": stop_reason}},
        ]
    }


def tool_use_response_stream(tool_use_id: str, name: str, tool_input: dict):
    return {
        "stream": [
            {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {"toolUse": {"toolUseId": tool_use_id, "name": name}},
                }
            },
            {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"toolUse": {"input": json.dumps(tool_input)}},
                }
            },
            {"messageStop": {"stopReason": "tool_use"}},
        ]
    }


@patch("app.bedrock_client._client")
def test_yields_text_and_saves_history_on_a_plain_response(mock_client):
    mock_client.converse_stream.return_value = text_response_stream("Hey, what's up?")

    chunks = list(stream_chat("s1", "hello"))

    assert chunks == ["Hey, what's up?"]
    assert mock_client.converse_stream.call_count == 1
    history = sessions.get_history("s1")
    assert history[0] == {"role": "user", "content": [{"text": "hello"}]}
    assert history[1] == {"role": "assistant", "content": [{"text": "Hey, what's up?"}]}


@patch("app.bedrock_client._client")
def test_uses_existing_session_history_as_the_starting_messages(mock_client):
    sessions.save_history("s1", [{"role": "user", "content": [{"text": "earlier"}]}])
    mock_client.converse_stream.return_value = text_response_stream("continuing")

    list(stream_chat("s1", "follow up"))

    sent_messages = mock_client.converse_stream.call_args.kwargs["messages"]
    assert sent_messages[0] == {"role": "user", "content": [{"text": "earlier"}]}
    assert sent_messages[1] == {"role": "user", "content": [{"text": "follow up"}]}


@patch("app.bedrock_client._client")
def test_system_prompt_has_a_cache_point_between_the_static_persona_and_the_page_context(mock_client):
    mock_client.converse_stream.return_value = text_response_stream("ok")
    list(stream_chat("s1", "where am i", current_path="/community"))

    system = mock_client.converse_stream.call_args.kwargs["system"]
    assert system[1] == {"cachePoint": {"type": "default"}}
    assert system[2] == {"text": "The user is currently viewing this page path: /community"}
    assert "You are Latch" in system[0]["text"]


@patch("app.bedrock_client._client")
def test_grants_report_content_tool_only_when_access_token_present(mock_client):
    mock_client.converse_stream.return_value = text_response_stream("ok")

    list(stream_chat("s1", "hi", access_token=None))
    tools_logged_out = mock_client.converse_stream.call_args.kwargs["toolConfig"]["tools"]
    assert not any(t["toolSpec"]["name"] == "report_content" for t in tools_logged_out)

    mock_client.converse_stream.return_value = text_response_stream("ok")
    list(stream_chat("s2", "hi", access_token="tok"))
    tools_logged_in = mock_client.converse_stream.call_args.kwargs["toolConfig"]["tools"]
    assert any(t["toolSpec"]["name"] == "report_content" for t in tools_logged_in)


@patch("app.bedrock_client.execute_tool")
@patch("app.bedrock_client._client")
def test_executes_tool_use_and_makes_a_second_model_call(mock_client, mock_execute_tool):
    mock_execute_tool.return_value = {"content": [{"id": "1"}]}
    mock_client.converse_stream.side_effect = [
        tool_use_response_stream("tool-1", "search_posts", {"search": "rollout"}),
        text_response_stream("Found one!"),
    ]

    chunks = list(stream_chat("s1", "find me a rollout post", access_token="tok"))

    assert chunks == ["Found one!"]
    assert mock_client.converse_stream.call_count == 2
    mock_execute_tool.assert_called_once_with("search_posts", {"search": "rollout"}, "tok")


@patch("app.bedrock_client.execute_tool")
@patch("app.bedrock_client._client")
def test_tool_result_is_appended_as_a_user_message_before_the_second_call(mock_client, mock_execute_tool):
    mock_execute_tool.return_value = {"content": []}
    responses = [
        tool_use_response_stream("tool-1", "search_posts", {}),
        text_response_stream("done"),
    ]
    messages_snapshots = []

    def record_and_respond(**kwargs):
        messages_snapshots.append(copy.deepcopy(kwargs["messages"]))
        return responses.pop(0)

    mock_client.converse_stream.side_effect = record_and_respond

    list(stream_chat("s1", "search something"))

    tool_result_message = messages_snapshots[1][-1]
    assert tool_result_message["role"] == "user"
    assert tool_result_message["content"][0]["toolResult"]["toolUseId"] == "tool-1"
    assert tool_result_message["content"][0]["toolResult"]["content"] == [{"json": {"content": []}}]


@patch("app.bedrock_client._client")
def test_does_not_save_history_until_a_final_non_tool_response(mock_client):
    mock_client.converse_stream.return_value = text_response_stream("done")
    list(stream_chat("s1", "hi"))
    assert sessions.get_history("s1")[-1] == {"role": "assistant", "content": [{"text": "done"}]}


@patch("app.bedrock_client.time.sleep")
@patch("app.bedrock_client._client")
def test_retries_a_throttling_error_then_succeeds(mock_client, mock_sleep):
    mock_client.converse_stream.side_effect = [
        client_error("ThrottlingException"),
        text_response_stream("ok"),
    ]

    chunks = list(stream_chat("s1", "hi"))

    assert chunks == ["ok"]
    assert mock_client.converse_stream.call_count == 2
    mock_sleep.assert_called_once_with(1)


@patch("app.bedrock_client.time.sleep")
@patch("app.bedrock_client._client")
def test_gives_up_after_max_attempts_and_yields_a_fallback_message(mock_client, mock_sleep):
    mock_client.converse_stream.side_effect = client_error("ThrottlingException")

    chunks = list(stream_chat("s1", "hi"))

    assert chunks == ["Latch is having trouble reaching the model right now — try again in a moment."]
    assert mock_client.converse_stream.call_count == 3
    assert mock_sleep.call_count == 2


@patch("app.bedrock_client.time.sleep")
@patch("app.bedrock_client._client")
def test_does_not_retry_a_non_retryable_client_error(mock_client, mock_sleep):
    mock_client.converse_stream.side_effect = client_error("ValidationException")

    chunks = list(stream_chat("s1", "hi"))

    assert chunks == ["Latch is having trouble reaching the model right now — try again in a moment."]
    assert mock_client.converse_stream.call_count == 1
    mock_sleep.assert_not_called()


@patch("app.bedrock_client.time.sleep")
@patch("app.bedrock_client._client")
def test_does_not_save_history_when_the_model_call_fails(mock_client, mock_sleep):
    mock_client.converse_stream.side_effect = client_error("ValidationException")
    list(stream_chat("s1", "hi"))
    assert sessions.get_history("s1") == []
