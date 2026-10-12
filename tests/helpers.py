"""Helpers shared by the tests."""

import time
from collections.abc import Callable
from typing import Any

from investigator.agent.loop import SUBMIT
from investigator.llm.types import Message, ToolCall, ToolDefinition


def wait_for(check: Callable[[], Any], timeout_s: float = 5.0) -> Any:
    """Telemetry is written in the background, so poll until it arrives."""
    deadline = time.monotonic() + timeout_s
    while True:
        result = check()
        if result or time.monotonic() > deadline:
            return result
        time.sleep(0.2)


class ScriptedModel:
    """Stands in for the model: replies with prepared messages in order, and notes what
    tools it was offered each time."""

    def __init__(self, *replies: Message | Exception) -> None:
        self._replies = list(replies)
        self.offered: list[list[str]] = []

    def complete(self, messages: list[Message], tools: list[ToolDefinition]) -> Message:
        self.offered.append([tool.name for tool in tools])
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def ask(tool: str, **arguments) -> Message:
    """The model asking for one tool."""
    call = ToolCall(id="call", name=tool, arguments=arguments)
    return Message(role="assistant", tool_calls=[call])


def say(text: str) -> Message:
    """The model replying with text and no tool request."""
    return Message(role="assistant", content=text)


def select(number: int = 1) -> Message:
    """A harmless tool request. Different numbers make different requests."""
    return ask("query_db", sql=f"SELECT {number}")


def submit(*evidence: str, **fields) -> Message:
    """The model submitting a report that cites the given labels."""
    report = {"summary": "It broke.", "root_cause": "A bug.", "suggested_fix": "Fix it.", **fields}
    return ask(SUBMIT, evidence=list(evidence), **report)
