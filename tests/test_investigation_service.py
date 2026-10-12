"""Checks for starting, running and storing investigations."""

import os

import httpx
import pytest

from investigator.enums import Severity, Source
from investigator.llm.types import ModelError
from investigator.repository import (
    IncidentRepository,
    InvestigationAlreadyRunningError,
    InvestigationRepository,
)
from investigator.service import IncidentNotFoundError, InvestigationService
from investigator.tools.code_history import Repo
from investigator.tools.registry import Resources, ToolRegistry
from tests.helpers import ScriptedModel, say, select, submit

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
