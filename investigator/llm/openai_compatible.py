"""Talks to any model served in the OpenAI chat format, such as a local Ollama."""

import json
from typing import Any

import httpx

from investigator.llm.types import Message, ModelError, ToolCall, ToolDefinition

_TIMEOUT_S = 120.0


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # `transport` is for tests, which swap the network for a fake server.
        self._http = httpx.Client(
            base_url=base_url, headers=headers, timeout=_TIMEOUT_S, transport=transport
        )
        self._model = model

    def complete(self, messages: list[Message], tools: list[ToolDefinition]) -> Message:
        body: dict[str, Any] = {
            "model": self._model,
            "temperature": 0,
            "messages": [_message_to_wire(message) for message in messages],
        }
        if tools:
            body["tools"] = [_tool_to_wire(tool) for tool in tools]
        try:
            response = self._http.post("/chat/completions", json=body)
            response.raise_for_status()
            return _message_from_wire(response.json()["choices"][0]["message"])
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()[:300]
            raise ModelError(f"The model refused the request: {detail}") from exc
        except httpx.HTTPError as exc:
            raise ModelError(f"The model could not be reached ({type(exc).__name__}).") from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError("The model replied in a form that could not be read.") from exc

    def close(self) -> None:
        self._http.close()


def _message_to_wire(message: Message) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id is not None:
        wire["tool_call_id"] = message.tool_call_id
    return wire


def _tool_to_wire(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def _message_from_wire(wire: dict[str, Any]) -> Message:
    calls = []
    for call in wire.get("tool_calls") or []:
        arguments = call["function"]["arguments"]
        if isinstance(arguments, str):  # the inputs arrive as JSON written inside a string
            arguments = json.loads(arguments)
        calls.append(ToolCall(id=call["id"], name=call["function"]["name"], arguments=arguments))
    return Message(role="assistant", content=wire.get("content") or "", tool_calls=calls)
