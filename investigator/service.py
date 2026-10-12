"""Starting an investigation and carrying it out."""

import logging

from investigator.agent.loop import investigate
from investigator.agent.report import Investigation
from investigator.llm.types import ModelClient
from investigator.models import InvestigationRecord
from investigator.repository import IncidentRepository, InvestigationRepository
from investigator.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class IncidentNotFoundError(Exception):
    """No incident exists with the given ID."""


class InvestigationService:
    def __init__(
        self,
        incidents: IncidentRepository,
        investigations: InvestigationRepository,
        model: ModelClient,
        model_name: str,
        registry: ToolRegistry,
    ) -> None:
        self._incidents = incidents
        self._investigations = investigations
        self._model = model
        self._model_name = model_name
        self._registry = registry

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
            result = investigate(
                incident.description, incident.created_at, self._model, self._registry
            )
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
