"""Checks for starting, running and storing investigations."""

import os
from uuid import uuid4

import httpx
import pytest

from investigator.agent.reproduce import RUN_REPRO
from investigator.enums import Severity, Source
from investigator.llm.types import ModelError
from investigator.repository import (
    IncidentRepository,
    InvestigationAlreadyRunningError,
    InvestigationRepository,
)
from investigator.repro.runner import Target
from investigator.service import (
    IncidentNotFoundError,
    InvestigationService,
    NothingAwaitingApprovalError,
)
from investigator.tools.code_history import Repo
from investigator.tools.registry import Resources, ToolRegistry
from tests.helpers import ScriptedModel, ask, say, select, submit

INVESTIGATOR = os.environ["INVESTIGATOR_URL"]


@pytest.fixture(scope="module")
def incidents(investigator_pool) -> IncidentRepository:
    return IncidentRepository(investigator_pool)


@pytest.fixture(scope="module")
def investigations(investigator_pool) -> InvestigationRepository:
    return InvestigationRepository(investigator_pool)


@pytest.fixture(scope="module")
def registry(telemetry_pool, target_pool) -> ToolRegistry:
    resources = Resources(
        telemetry_pool=telemetry_pool, target_pool=target_pool, config_sources={}, repo=Repo()
    )
    return ToolRegistry(resources)


@pytest.fixture
def incident_id(incidents) -> int:
    """A fresh incident for each test."""
    return incidents.create("Something broke.", Severity.LOW, Source.REPORTED).id


@pytest.fixture
def service_with(incidents, investigations, registry):
    """Builds a service whose model replies as scripted."""

    def build(*replies) -> InvestigationService:
        return InvestigationService(
            incidents, investigations, ScriptedModel(*replies), "scripted", registry
        )

    return build


def test_starting_records_a_running_investigation(service_with, incidents, incident_id):
    record = service_with().start(incident_id)

    assert record.status == "running"
    assert record.model == "scripted"
    assert incidents.get(incident_id).status == "investigating"


def test_starting_for_an_unknown_incident_is_refused(service_with):
    with pytest.raises(IncidentNotFoundError):
        service_with().start(999_999_999)


def test_starting_while_one_is_running_is_refused(service_with, incident_id):
    service = service_with()
    service.start(incident_id)

    with pytest.raises(InvestigationAlreadyRunningError):
        service.start(incident_id)


def test_running_stores_a_resolved_outcome(service_with, incidents, investigations, incident_id):
    service = service_with(select(), submit("E1"))

    service.run(service.start(incident_id))

    (stored,) = investigations.list_for(incident_id)
    assert stored.status == "resolved"
    assert stored.report.root_cause == "A bug."
    assert [item.label for item in stored.evidence] == ["E1"]
    assert stored.messages[1].content.endswith("Something broke.")
    assert stored.finished_at is not None
    assert incidents.get(incident_id).status == "resolved"


def test_without_a_target_the_investigation_ends_at_the_report(
    service_with, investigations, incident_id
):
    service = service_with(select(), submit("E1"))

    service.run(service.start(incident_id))

    assert investigations.list_for(incident_id)[0].reproduction is None


def _charge_recipe() -> tuple[dict, str]:
    """A recipe that creates one new payment, and that payment's order ID."""
    order_id = f"order-{uuid4().hex[:8]}"
    charge = {
        "method": "POST",
        "path": "/charge",
        "headers": {"Idempotency-Key": str(uuid4())},
        "body": {"order_id": order_id, "amount_cents": 3000},
    }
    recipe = {
        "steps": [{"requests": [charge]}],
        "check_sql": f"SELECT 1 FROM payments WHERE order_id = '{order_id}'",
    }
    return recipe, order_id


@pytest.fixture
def reproducing(incidents, investigations, registry, target_pool):
    """Builds a service with a target, whose model proposes the given recipe after its report."""
    target = Target(os.environ["PAYMENT_API_URL"], {}, target_pool)

    def build(recipe: dict, ask_first: bool = True) -> InvestigationService:
        model = ScriptedModel(select(), submit("E1"), ask(RUN_REPRO, **recipe))
        return InvestigationService(
            incidents, investigations, model, "scripted", registry, target, ask_first=ask_first
        )

    return build


def _was_charged(target_pool, order_id: str) -> bool:
    with target_pool.connection() as conn:
        found = conn.execute("SELECT 1 FROM payments WHERE order_id = %s", (order_id,))
        return found.fetchone() is not None


def test_a_recipe_waits_for_approval_and_is_carried_out_once_approved(
    reproducing, investigations, target_pool, incident_id
):
    recipe, order_id = _charge_recipe()
    service = reproducing(recipe)

    service.run(service.start(incident_id))

    (waiting,) = investigations.list_for(incident_id)
    assert waiting.report.root_cause == "A bug."
    assert waiting.reproduction.outcome == "awaiting_approval"
    assert waiting.reproduction.pending == recipe
    assert not _was_charged(target_pool, order_id)

    service.resume(service.approve(waiting.id))

    (stored,) = investigations.list_for(incident_id)
    assert stored.reproduction.outcome == "reproduced"
    assert _was_charged(target_pool, order_id)
    (returned,) = httpx.get(f"{INVESTIGATOR}/incidents/{incident_id}/investigations").json()
    assert returned["reproduction"]["attempts"][0]["result"]["outcome"] == "reproduced"


def test_with_approval_switched_off_a_recipe_is_carried_out_at_once(
    reproducing, investigations, incident_id
):
    recipe, _ = _charge_recipe()
    service = reproducing(recipe, ask_first=False)

    service.run(service.start(incident_id))

    assert investigations.list_for(incident_id)[0].reproduction.outcome == "reproduced"


def test_a_declined_recipe_is_never_carried_out_and_cannot_be_approved_later(
    reproducing, investigations, target_pool, incident_id
):
    recipe, order_id = _charge_recipe()
    service = reproducing(recipe)
    service.run(service.start(incident_id))
    (waiting,) = investigations.list_for(incident_id)

    declined = httpx.post(f"{INVESTIGATOR}/investigations/{waiting.id}/decline")
    approved = httpx.post(f"{INVESTIGATOR}/investigations/{waiting.id}/approve")

    assert declined.status_code == 200
    assert declined.json()["reproduction"]["outcome"] == "declined"
    assert approved.status_code == 409
    assert not _was_charged(target_pool, order_id)


def test_a_recipe_can_only_be_approved_once(reproducing, investigations, incident_id):
    recipe, _ = _charge_recipe()
    service = reproducing(recipe)
    service.run(service.start(incident_id))
    (waiting,) = investigations.list_for(incident_id)

    service.approve(waiting.id)

    with pytest.raises(NothingAwaitingApprovalError):
        service.approve(waiting.id)


def test_a_failed_investigation_is_stored_with_its_reason(
    service_with, incidents, investigations, incident_id
):
    service = service_with(ModelError("The model could not be reached (ConnectError)."))

    service.run(service.start(incident_id))

    (stored,) = investigations.list_for(incident_id)
    assert stored.status == "failed"
    assert stored.failure_reason == "The model could not be reached (ConnectError)."
    assert stored.report is None
    assert incidents.get(incident_id).status == "failed"


def test_an_unexpected_crash_still_closes_the_investigation(
    service_with, incidents, investigations, incident_id
):
    service = service_with(RuntimeError("nobody planned for this"))

    service.run(service.start(incident_id))

    (stored,) = investigations.list_for(incident_id)
    assert stored.status == "failed"
    assert stored.failure_reason == "The investigation stopped because of an internal error."
    assert incidents.get(incident_id).status == "failed"


def test_an_incident_can_be_investigated_again_and_both_runs_are_kept(
    service_with, incidents, investigations, incident_id
):
    first = service_with(select(), submit("E1"))
    first.run(first.start(incident_id))
    second = service_with(*[say("Hmm.")] * 4)
    second.run(second.start(incident_id))

    assert [str(run.status) for run in investigations.list_for(incident_id)] == [
        "failed",
        "resolved",
    ]
    assert incidents.get(incident_id).status == "failed"


def test_investigations_left_running_are_closed_on_restart(
    service_with, incidents, investigations, incident_id
):
    service_with().start(incident_id)

    assert investigations.fail_interrupted() >= 1

    (stored,) = investigations.list_for(incident_id)
    assert stored.status == "failed"
    assert stored.failure_reason == "The service restarted during the investigation."
    assert incidents.get(incident_id).status == "failed"


def test_investigating_an_unknown_incident_returns_404():
    response = httpx.post(f"{INVESTIGATOR}/incidents/999999999/investigate")

    assert response.status_code == 404


def test_an_incident_with_no_investigations_lists_none(incident_id):
    response = httpx.get(f"{INVESTIGATOR}/incidents/{incident_id}/investigations")

    assert response.status_code == 200
    assert response.json() == []


def test_the_api_returns_a_finished_investigation(service_with, incident_id):
    service = service_with(select(), submit("E1"))
    service.run(service.start(incident_id))

    (returned,) = httpx.get(f"{INVESTIGATOR}/incidents/{incident_id}/investigations").json()

    assert returned["status"] == "resolved"
    assert returned["model"] == "scripted"
    assert returned["report"]["evidence"] == ["E1"]
    assert returned["evidence"][0]["tool"] == "query_db"
