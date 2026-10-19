"""The second phase: the model tries to make the incident happen again."""

import httpx
from pydantic import ValidationError

from investigator.agent.prompt import REPRODUCE, RUN_REPRO_DESCRIPTION, fence
from investigator.agent.report import Attempt, Investigation, Reproduction
from investigator.llm.types import Message, ModelClient, ModelError, ToolCall, ToolDefinition
from investigator.repro.recipe import Recipe
from investigator.repro.runner import ReproResult, Target, run_recipe
from investigator.tools.registry import (
    ToolRegistry,
    ToolRequestError,
    describe_problems,
    simplify_schema,
    tool_span,
)

# A recipe that could not be carried out is corrected, not counted.
MAX_ATTEMPTS = 3
MAX_STEPS = 12
RUN_REPRO = "run_repro"
LOOKUP_TOOLS = ("describe_db", "query_db")
# Where a system built with a common web framework publishes the description of its API.
API_DESCRIPTION_PATH = "/openapi.json"
MAX_DESCRIPTION_CHARS = 8000


def reproduce(
    investigation: Investigation,
    model: ModelClient,
    registry: ToolRegistry,
    target: Target,
    ask_first: bool = False,
) -> Investigation:
    """Continue a resolved investigation: ask for a recipe, carry it out, record how it went.

    With ask_first, it stops before carrying out each recipe, with the outcome
    awaiting_approval. Calling it again on that result means the recipe was approved.
    """
    run_repro = ToolDefinition(
        name=RUN_REPRO,
        description=RUN_REPRO_DESCRIPTION,
        input_schema=simplify_schema(Recipe.model_json_schema()),
    )
    lookups = [tool for tool in registry.definitions() if tool.name in LOOKUP_TOOLS]
    previous = investigation.reproduction
    # Resuming after an approval: the model's last reply holds the approved request, and
    # the calls before it in that reply are already answered.
    approved = previous is not None
    if approved:
        messages = list(investigation.messages)
        attempts = list(previous.attempts)
        position = max(i for i, message in enumerate(messages) if message.role == "assistant")
        reply = messages[position]
        answered = len(messages) - position - 1
    else:
        request = f"{REPRODUCE}{_api_description(target)}"
        messages = [*investigation.messages, Message(role="user", content=request)]
        attempts = []
        reply = None
        answered = 0

    def finished(outcome: str, pending: dict | None = None) -> Investigation:
        reproduction = Reproduction(outcome=outcome, attempts=attempts, pending=pending)
        return investigation.model_copy(update={"messages": messages, "reproduction": reproduction})

    steps = 0
    while True:
        if reply is None:
            if steps == MAX_STEPS:
                break
            steps += 1
            try:
                reply = model.complete(messages, [*lookups, run_repro])
            except ModelError:
                break
            messages.append(reply)
        for call in reply.tool_calls[answered:]:
            if call.name != RUN_REPRO:
                messages.append(_answer(call, _look_up(call, registry)))
                continue
            # A recipe that cannot be carried out touches nothing, so it needs no approval.
            if ask_first and not approved and _is_valid(call):
                return finished("awaiting_approval", pending=call.arguments)
            approved = False
            result = _attempt(call, target)
            attempts.append(Attempt(recipe=call.arguments, result=result))
            messages.append(_answer(call, fence(result.model_dump_json())))
            if result.outcome == "reproduced":
                return finished("reproduced")
        carried_out = sum(a.result.outcome != "invalid_recipe" for a in attempts)
        if carried_out >= MAX_ATTEMPTS or not reply.tool_calls:
            break
        reply = None
        answered = 0
    return finished("not_reproduced")


def _api_description(target: Target) -> str:
    """The system's own description of its API, if it publishes one, so recipes need no guessing."""
    try:
        response = httpx.get(f"{target.api_url}{API_DESCRIPTION_PATH}", timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError:
        return ""
    # ponytail: the raw description, cut to size; summarise it if a system's is too big.
    description = fence(response.text[:MAX_DESCRIPTION_CHARS])
    return f"\n\nThe system describes its API like this:\n{description}"


def _attempt(call: ToolCall, target: Target) -> ReproResult:
    with tool_span(call):
        try:
            recipe = Recipe.model_validate(call.arguments)
        except ValidationError as exc:
            return ReproResult(outcome="invalid_recipe", detail=describe_problems(exc))
        return run_recipe(recipe, target)


def _is_valid(call: ToolCall) -> bool:
    try:
        Recipe.model_validate(call.arguments)
    except ValidationError:
        return False
    return True


def _look_up(call: ToolCall, registry: ToolRegistry) -> str:
    if call.name not in LOOKUP_TOOLS:
        return f"Only {', '.join(LOOKUP_TOOLS)} and {RUN_REPRO} can be used now."
    try:
        return fence(registry.run(call))
    except ToolRequestError as exc:
        return str(exc)


def _answer(call: ToolCall, content: str) -> Message:
    return Message(role="tool", tool_call_id=call.id, content=content)
