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
def test_yields_each_text_delta_as_it_arrives(mock_client):
    mock_client.converse_stream.return_value = {
        "stream": [
            {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Hey, "}}},
            {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "what's up?"}}},
            {"messageStop": {"stopReason": "end_turn"}},
        ]
    }

    chunks = list(stream_chat("s1", "hello"))

    assert chunks == ["Hey, ", "what's up?"]
    assert sessions.get_history("s1")[1] == {"role": "assistant", "content": [{"text": "Hey, what's up?"}]}


@patch("app.bedrock_client.execute_tool")
@patch("app.bedrock_client._client")
def test_streams_text_before_a_tool_call_and_separates_it_from_the_next_round(mock_client, mock_execute_tool):
    mock_execute_tool.return_value = {"content": []}
    preamble_then_tool = {
        "stream": [
            {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Let me look."}}},
            {
                "contentBlockStart": {
                    "contentBlockIndex": 1,
                    "start": {"toolUse": {"toolUseId": "tool-1", "name": "search_posts"}},
                }
            },
            {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": "{}"}}}},
            {"messageStop": {"stopReason": "tool_use"}},
        ]
    }
    mock_client.converse_stream.side_effect = [preamble_then_tool, text_response_stream("Found it.")]

    chunks = list(stream_chat("s1", "find something"))

    assert chunks == ["Let me look.", "\n\n", "Found it."]


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
    assert system[2] == {"text": "The user is currently viewing this page path: /community\nThe user is NOT logged in."}
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


def tool_turn(question: str, tool_use_id: str, result: dict, answer: str) -> list[dict]:
    return [
        {"role": "user", "content": [{"text": question}]},
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": tool_use_id, "name": "search_posts", "input": {}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": tool_use_id, "content": [{"json": result}]}}]},
        {"role": "assistant", "content": [{"text": answer}]},
    ]


def plain_turn(question: str, answer: str) -> list[dict]:
    return [
        {"role": "user", "content": [{"text": question}]},
        {"role": "assistant", "content": [{"text": answer}]},
    ]


@patch("app.bedrock_client.settings.max_history_turns", 2)
@patch("app.bedrock_client._client")
def test_drops_turns_older_than_max_history_turns(mock_client):
    sessions.save_history("s1", plain_turn("q1", "a1") + plain_turn("q2", "a2") + plain_turn("q3", "a3"))
    mock_client.converse_stream.return_value = text_response_stream("a4")

    list(stream_chat("s1", "q4"))

    sent_messages = mock_client.converse_stream.call_args.kwargs["messages"]
    assert sent_messages[:3] == plain_turn("q3", "a3") + [{"role": "user", "content": [{"text": "q4"}]}]


@patch("app.bedrock_client.settings.max_history_turns", 2)
@patch("app.bedrock_client._client")
def test_trimming_never_starts_between_a_tool_call_and_its_result(mock_client):
    sessions.save_history("s1", tool_turn("q1", "t1", {"n": 1}, "a1") + tool_turn("q2", "t2", {"n": 2}, "a2"))
    mock_client.converse_stream.return_value = text_response_stream("a3")

    list(stream_chat("s1", "q3"))

    sent_messages = mock_client.converse_stream.call_args.kwargs["messages"]
    assert sent_messages[0] == {"role": "user", "content": [{"text": "q2"}]}
    assert sent_messages[1]["content"][0]["toolUse"]["toolUseId"] == "t2"
    assert sent_messages[2]["content"][0]["toolResult"]["toolUseId"] == "t2"


@patch("app.bedrock_client.settings.max_history_turns", 2)
@patch("app.bedrock_client._client")
def test_saves_the_trimmed_history(mock_client):
    sessions.save_history("s1", plain_turn("q1", "a1") + plain_turn("q2", "a2"))
    mock_client.converse_stream.return_value = text_response_stream("a3")

    list(stream_chat("s1", "q3"))

    assert sessions.get_history("s1") == plain_turn("q2", "a2") + plain_turn("q3", "a3")


@patch("app.bedrock_client._client")
def test_replaces_tool_results_from_earlier_turns_with_a_placeholder(mock_client):
    sessions.save_history("s1", tool_turn("q1", "t1", {"posts": ["big", "payload"]}, "a1"))
    mock_client.converse_stream.return_value = text_response_stream("a2")

    list(stream_chat("s1", "q2"))

    sent_messages = mock_client.converse_stream.call_args.kwargs["messages"]
    assert sent_messages[2]["content"][0]["toolResult"] == {
        "toolUseId": "t1",
        "content": [{"json": {"note": "result omitted from history"}}],
    }
    assert sent_messages[3] == {"role": "assistant", "content": [{"text": "a1"}]}


@patch("app.bedrock_client.execute_tool")
@patch("app.bedrock_client._client")
def test_keeps_full_tool_results_within_the_current_turn(mock_client, mock_execute_tool):
    mock_execute_tool.return_value = {"posts": ["full", "result"]}
    responses = [tool_use_response_stream("t1", "search_posts", {}), text_response_stream("done")]
    messages_snapshots = []

    def record_and_respond(**kwargs):
        messages_snapshots.append(copy.deepcopy(kwargs["messages"]))
        return responses.pop(0)

    mock_client.converse_stream.side_effect = record_and_respond

    list(stream_chat("s1", "search"))

    assert messages_snapshots[1][-1]["content"][0]["toolResult"]["content"] == [{"json": {"posts": ["full", "result"]}}]
