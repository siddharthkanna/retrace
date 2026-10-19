"""Starting an investigation and carrying it out."""

import logging

from opentelemetry import trace

from investigator.agent.loop import investigate
from investigator.agent.report import Investigation
from investigator.agent.reproduce import reproduce
from investigator.agent.usage import Prices, add_up
from investigator.llm.types import ModelClient
from investigator.models import InvestigationRecord
from investigator.repository import IncidentRepository, InvestigationRepository
from investigator.repro.runner import Target
from investigator.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("retrace.investigator")


class IncidentNotFoundError(Exception):
    """No incident exists with the given ID."""


class NothingAwaitingApprovalError(Exception):
    """The investigation has no recipe waiting for approval."""


class InvestigationService:
    def __init__(
        self,
        incidents: IncidentRepository,
        investigations: InvestigationRepository,
        model: ModelClient,
        model_name: str,
        registry: ToolRegistry,
        target: Target | None = None,
        prices: Prices | None = None,
        ask_first: bool = True,
    ) -> None:
        self._incidents = incidents
        self._investigations = investigations
        self._model = model
        self._model_name = model_name
        self._registry = registry
        # Where recipes are carried out. With none, investigations end at the report.
        self._target = target
        self._prices = prices
        # Whether a person must approve each recipe before it is carried out.
        self._ask_first = ask_first

    def start(self, incident_id: int) -> InvestigationRecord:
        """Record a new investigation for an incident, ready to be run.

        Raises IncidentNotFoundError, or InvestigationAlreadyRunningError if one is in progress.
        """
        if self._incidents.get(incident_id) is None:
            raise IncidentNotFoundError(incident_id)
        return self._investigations.start(incident_id, self._model_name)

    def run(self, record: InvestigationRecord) -> None:
        """Carry out a started investigation and store its outcome. Runs in the background."""
        incident = self._incidents.get(record.incident_id)
        try:
            with self._span(record):
                result = investigate(
                    incident.description, incident.created_at, self._model, self._registry
                )
                if result.status == "resolved" and self._target is not None:
                    result = self._reproduce(result)
            result = result.model_copy(update={"usage": add_up(result.messages, self._prices)})
        except Exception:
            # Whatever goes wrong, the investigation must be closed, or its incident
            # would stay "investigating" for ever.
            logger.exception("investigation %s crashed", record.id)
            result = Investigation(
                status="failed",
                failure_reason="The investigation stopped because of an internal error.",
                evidence=[],
                messages=[],
            )
        self._investigations.finish(record.id, result)

    def approve(self, investigation_id: int) -> InvestigationRecord:
        """Let the waiting recipe be carried out. Raises NothingAwaitingApprovalError."""
        record = self._investigations.approve(investigation_id)
        if record is None:
            raise NothingAwaitingApprovalError(investigation_id)
        return record

    def decline(self, investigation_id: int) -> InvestigationRecord:
        """End the reproduction without carrying out the waiting recipe."""
        record = self._investigations.decline(investigation_id)
        if record is None:
            raise NothingAwaitingApprovalError(investigation_id)
        return record

    def resume(self, record: InvestigationRecord) -> None:
        """Carry out an approved recipe and continue the reproduction. Runs in the background."""
        investigation = Investigation.model_validate(record.model_dump())
        try:
            with self._span(record):
                result = self._reproduce(investigation)
        except Exception:
            logger.exception("reproduction for investigation %s crashed", record.id)
            # ponytail: shown as not reproduced; the log has the reason.
            reproduction = investigation.reproduction.model_copy(
                update={"outcome": "not_reproduced", "pending": None}
            )
            result = investigation.model_copy(update={"reproduction": reproduction})
        result = result.model_copy(update={"usage": add_up(result.messages, self._prices)})
        self._investigations.finish(record.id, result)

    def _reproduce(self, investigation: Investigation) -> Investigation:
        return reproduce(
            investigation, self._model, self._registry, self._target, ask_first=self._ask_first
        )

    def _span(self, record: InvestigationRecord):
        return _tracer.start_as_current_span(
            "invoke_agent retrace",
            attributes={
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": "retrace",
                "gen_ai.request.model": self._model_name,
                "retrace.incident.id": record.incident_id,
                "retrace.investigation.id": record.id,
            },
        )
