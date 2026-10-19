"""The recipe an investigator writes to make an incident happen again."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Request(BaseModel):
    """One call to the system's API."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST"]
    path: str = Field(pattern=r"^/", description="The path on the system's API, such as /orders.")
    headers: dict[str, str] = {}
    body: dict[str, Any] | None = Field(
        default=None,
        description=(
            'The JSON body. A value such as "$1.id" is replaced by the field `id` from'
            " the first reply of step 1."
        ),
    )


class Step(BaseModel):
    """Requests sent at the same moment. A single request is a step of one."""

    model_config = ConfigDict(extra="forbid")

    requests: list[Request] = Field(min_length=1, max_length=10)


class Recipe(BaseModel):
    """How to make the incident happen again, and how to tell that it did."""

    model_config = ConfigDict(extra="forbid")

    settings: dict[str, dict[str, Any]] = Field(
        default={},
        description="Settings to change first, by source: the names get_config returns.",
    )
    steps: list[Step] = Field(min_length=1, max_length=10)
    check_sql: str = Field(
        min_length=1,
        description=(
            "One read-only query that returns at least one row if the incident happened"
            " again, and no rows if it did not."
        ),
    )
