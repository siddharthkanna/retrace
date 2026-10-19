"""Adding up what an investigation took: model calls, tool calls, tokens, time and cost."""

from typing import NamedTuple

from pydantic import BaseModel

from investigator.llm.types import Message


class Prices(NamedTuple):
    """What the model costs, in US dollars per million tokens."""

    input_per_million: float
    output_per_million: float


class Totals(BaseModel):
    model_calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    model_seconds: float
    # Only known when the model's prices are set.
    cost_usd: float | None = None


def add_up(messages: list[Message], prices: Prices | None) -> Totals:
    usages = [message.usage for message in messages if message.usage is not None]
    input_tokens = sum(usage.input_tokens for usage in usages)
    output_tokens = sum(usage.output_tokens for usage in usages)
    cost = (
        round(
            (input_tokens * prices.input_per_million + output_tokens * prices.output_per_million)
            / 1_000_000,
            4,
        )
        if prices
        else None
    )
    return Totals(
        model_calls=len(usages),
        tool_calls=sum(message.role == "tool" for message in messages),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_seconds=round(sum(usage.seconds for usage in usages), 1),
        cost_usd=cost,
    )
