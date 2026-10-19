"""Checks for adding up what an investigation took."""

from investigator.agent.usage import Prices, add_up
from investigator.llm.types import Message, ToolCall, Usage

CALL = ToolCall(id="c1", name="query_logs", arguments={})
MESSAGES = [
    Message(role="system", content="instructions"),
    Message(role="user", content="incident"),
    Message(
        role="assistant",
        tool_calls=[CALL],
        usage=Usage(input_tokens=1000, output_tokens=50, seconds=2.5),
    ),
    Message(role="tool", tool_call_id="c1", content="[E1] result"),
    Message(
        role="assistant",
        content="done",
        usage=Usage(input_tokens=3000, output_tokens=150, seconds=4),
    ),
]


def test_calls_tokens_and_time_are_added_up():
    totals = add_up(MESSAGES, None)

    assert (totals.model_calls, totals.tool_calls) == (2, 1)
    assert (totals.input_tokens, totals.output_tokens) == (4000, 200)
    assert totals.model_seconds == 6.5
    assert totals.cost_usd is None


def test_the_cost_follows_the_prices():
    totals = add_up(MESSAGES, Prices(input_per_million=1.25, output_per_million=10))

    # 4,000 tokens in at 1.25 per million, and 200 out at 10 per million.
    assert totals.cost_usd == 0.007
