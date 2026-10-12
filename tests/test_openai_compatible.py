"""Checks for the model adapter, using a fake server in place of a real model."""

import json

import httpx
import pytest

from investigator.llm.openai_compatible import ModelError, OpenAICompatibleClient
from investigator.llm.types import Message, ToolCall, ToolDefinition

TOOL = ToolDefinition(
    name="query_logs",
    description="Search the logs.",
    input_schema={"type": "object", "properties": {"contains": {"type": "string"}}},
)
HELLO = [Message(role="user", content="hello")]


class FakeServer:
    """Stands in for the model: records what it was sent, and replies as it was told to."""

    def __init__(self, reply: dict | None = None, status: int = 200, body: object = None) -> None:
        self.requests: list[httpx.Request] = []
        self._status = status
        self._body = body or {
            "choices": [{"message": reply or {"role": "assistant", "content": "ok"}}]
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status, json=self._body)

    @property
    def sent(self) -> dict:
        return json.loads(self.requests[-1].content)


def _client(server, api_key: str | None = None) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        "http://model.test/v1", "test-model", api_key, transport=httpx.MockTransport(server)
    )


def _tool_request(arguments: str) -> dict:
    """A reply from the model that asks for query_logs with the given inputs, as text."""
    function = {"name": "query_logs", "arguments": arguments}
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "call-9", "type": "function", "function": function}],
    }


def test_request_carries_the_model_messages_and_tools():
    server = FakeServer()

    _client(server).complete(HELLO, [TOOL])

    assert server.requests[-1].url == "http://model.test/v1/chat/completions"
    assert server.sent["model"] == "test-model"
    assert server.sent["messages"] == [{"role": "user", "content": "hello"}]
    assert server.sent["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "query_logs",
                "description": "Search the logs.",
                "parameters": TOOL.input_schema,
            },
        }
    ]


def test_tools_are_left_out_when_there_are_none():
    server = FakeServer()

    _client(server).complete(HELLO, [])

    assert "tools" not in server.sent


def test_tool_requests_and_results_are_written_in_the_providers_format():
    server = FakeServer()
    conversation = [
        Message(
            role="assistant",
            tool_calls=[ToolCall(id="call-1", name="query_logs", arguments={"contains": "x"})],
        ),
        Message(role="tool", content="2 lines", tool_call_id="call-1"),
    ]

    _client(server).complete(conversation, [TOOL])

    request, result = server.sent["messages"]
    assert request["tool_calls"] == [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "query_logs", "arguments": '{"contains": "x"}'},
        }
    ]
    assert result == {"role": "tool", "content": "2 lines", "tool_call_id": "call-1"}


def test_a_reply_with_a_tool_request_becomes_a_tool_call():
    server = FakeServer(reply=_tool_request('{"contains": "order-1"}'))

    reply = _client(server).complete(HELLO, [TOOL])

    assert reply.role == "assistant"
    assert reply.content == ""
    assert reply.tool_calls == [
        ToolCall(id="call-9", name="query_logs", arguments={"contains": "order-1"})
    ]


def test_a_plain_reply_has_no_tool_calls():
    server = FakeServer(reply={"role": "assistant", "content": "The cause is X."})

    reply = _client(server).complete(HELLO, [TOOL])

    assert reply.content == "The cause is X."
    assert reply.tool_calls == []


def test_the_api_key_is_sent_only_when_given():
    with_key, without_key = FakeServer(), FakeServer()

    _client(with_key, api_key="secret").complete(HELLO, [])
    _client(without_key).complete(HELLO, [])

    assert with_key.requests[-1].headers["Authorization"] == "Bearer secret"
    assert "Authorization" not in without_key.requests[-1].headers


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("no route to host")


@pytest.mark.parametrize(
    ("server", "message"),
    [
        (FakeServer(status=404, body={"error": {"message": "model not found"}}), "model not found"),
        (_unreachable, "could not be reached"),
        (FakeServer(body={"unexpected": "shape"}), "could not be read"),
        (FakeServer(reply=_tool_request("{not json")), "could not be read"),
    ],
    ids=["error reply", "unreachable", "unexpected shape", "inputs not valid JSON"],
)
def test_failures_become_a_model_error(server, message):
    with pytest.raises(ModelError, match=message):
        _client(server).complete(HELLO, [TOOL])
