"""The provider-neutral shapes the agent loop uses to talk to a model."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel


class ModelError(Exception):
    """The model could not be reached, refused the request, or replied in an unusable form."""


class ToolDefinition(BaseModel):
    """A tool as it is described to the model."""

    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    """The model asking for one tool to be run."""

    id: str
    name: str
    arguments: dict[str, Any]


class Usage(BaseModel):
    """What one model reply took: tokens read, tokens written, and time."""

    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0


class Message(BaseModel):
    """One entry in the conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    # On an assistant message: the tools it is asking for, if any.
    tool_calls: list[ToolCall] = []
    # On a tool message: which request this result answers.
    tool_call_id: str | None = None
    # On an assistant message: what producing it took.
    usage: Usage | None = None


class ModelClient(Protocol):
    """Anything that can read the conversation so far and return the model's next message."""

    def complete(self, messages: list[Message], tools: list[ToolDefinition]) -> Message: ...
