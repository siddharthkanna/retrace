"""Talks to any model served in the OpenAI chat format, such as a local Ollama."""

import json
import time
from typing import Any

import httpx
from opentelemetry import trace

from investigator.llm.types import Message, ModelError, ToolCall, ToolDefinition, Usage

_TIMEOUT_S = 300.0
_RATE_LIMIT_RETRIES = 5
_DEFAULT_WAIT_S = 5.0
_MAX_WAIT_S = 60.0

_tracer = trace.get_tracer("retrace.investigator")


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        api_key_header: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # Most services take the key as a bearer token; some want it in a header of their own.
        if not api_key:
            headers = {}
        elif api_key_header:
            headers = {api_key_header: api_key}
        else:
            headers = {"Authorization": f"Bearer {api_key}"}
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
        # Named as OpenTelemetry's conventions for AI calls name them.
        with _tracer.start_as_current_span(
            f"chat {self._model}",
            kind=trace.SpanKind.CLIENT,
            attributes={"gen_ai.operation.name": "chat", "gen_ai.request.model": self._model},
        ) as span:
            started = time.monotonic()
            reply, wire_usage = self._ask(body)
            usage = _usage(wire_usage, time.monotonic() - started)
            span.set_attributes(
                {
                    "gen_ai.usage.input_tokens": usage.input_tokens,
                    "gen_ai.usage.output_tokens": usage.output_tokens,
                }
            )
        return reply.model_copy(update={"usage": usage})

    def _ask(self, body: dict[str, Any]) -> tuple[Message, Any]:
        """Send the request and return the reply, with the token counts the service sent."""
        try:
            response = self._post(body)
            response.raise_for_status()
            data = response.json()
            return _message_from_wire(data["choices"][0]["message"]), data.get("usage")
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()[:300]
            raise ModelError(f"The model refused the request: {detail}") from exc
        except httpx.HTTPError as exc:
            raise ModelError(f"The model could not be reached ({type(exc).__name__}).") from exc
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ModelError("The model replied in a form that could not be read.") from exc

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        """Send the request, waiting and retrying while the service says it is too busy."""
        for _ in range(_RATE_LIMIT_RETRIES):
            response = self._send(body)
            if response.status_code != 429:
                break
            wait = float(response.headers.get("retry-after", _DEFAULT_WAIT_S))
            if wait > _MAX_WAIT_S:  # a daily limit, say: waiting it out is not worth it
                break
            time.sleep(wait + 1)
        return response

    def _send(self, body: dict[str, Any]) -> httpx.Response:
        """Send the request, once more if the connection drops before the reply arrives."""
        try:
            return self._http.post("/chat/completions", json=body)
        except httpx.RemoteProtocolError:
            return self._http.post("/chat/completions", json=body)

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


def _usage(wire: Any, seconds: float) -> Usage:
    """The token counts, if the service sent them, and the time the reply took."""
    wire = wire if isinstance(wire, dict) else {}
    return Usage(
        input_tokens=wire.get("prompt_tokens") or 0,
        output_tokens=wire.get("completion_tokens") or 0,
        seconds=round(seconds, 3),
    )


def _message_from_wire(wire: dict[str, Any]) -> Message:
    calls = []
    for call in wire.get("tool_calls") or []:
        arguments = call["function"]["arguments"]
        if isinstance(arguments, str):  # the inputs arrive as JSON written inside a string
            arguments = json.loads(arguments)
        calls.append(ToolCall(id=call["id"], name=call["function"]["name"], arguments=arguments))
    return Message(role="assistant", content=wire.get("content") or "", tool_calls=calls)
