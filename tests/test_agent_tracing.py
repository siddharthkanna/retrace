"""Checks that an investigation is traced with OpenTelemetry's names for AI calls."""

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from investigator.llm.openai_compatible import OpenAICompatibleClient
from investigator.llm.types import Message, ToolCall
from investigator.tools.registry import Resources, ToolRegistry

# The test process sets no tracer of its own, so this one receives every span.
_finished = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_finished))
trace.set_tracer_provider(_provider)


@pytest.fixture(autouse=True)
def fresh_spans():
    _finished.clear()


def test_a_model_call_is_traced_with_its_tokens():
    reply = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }
    model = OpenAICompatibleClient(
        "http://model.test/v1",
        "test-model",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=reply)),
    )

    model.complete([Message(role="user", content="hello")], [])

    [span] = _finished.get_finished_spans()
    assert span.name == "chat test-model"
    assert span.attributes["gen_ai.operation.name"] == "chat"
    assert span.attributes["gen_ai.usage.input_tokens"] == 120
    assert span.attributes["gen_ai.usage.output_tokens"] == 30


def test_a_tool_call_is_traced(telemetry_pool):
    registry = ToolRegistry(Resources(telemetry_pool=telemetry_pool))

    registry.run(
        ToolCall(id="call-1", name="query_logs", arguments={"contains": "nothing-like-this"})
    )

    [span] = _finished.get_finished_spans()
    assert span.name == "execute_tool query_logs"
    assert span.attributes["gen_ai.tool.name"] == "query_logs"
    assert span.attributes["gen_ai.tool.call.id"] == "call-1"
