"""HTTP endpoints for incidents and their investigations."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status

from investigator.enums import Source
from investigator.repository import (
    IncidentRepository,
    InvestigationAlreadyRunningError,
    InvestigationRepository,
)
from investigator.schemas import IncidentCreate, IncidentResponse, InvestigationResponse
from investigator.service import (
    IncidentNotFoundError,
    InvestigationService,
    NothingAwaitingApprovalError,
)

router = APIRouter()


def get_incidents(request: Request) -> IncidentRepository:
    return request.app.state.incidents


def get_service(request: Request) -> InvestigationService:
    return request.app.state.investigation_service


def get_investigations(request: Request) -> InvestigationRepository:
    return request.app.state.investigations


IncidentsDep = Annotated[IncidentRepository, Depends(get_incidents)]
ServiceDep = Annotated[InvestigationService, Depends(get_service)]
InvestigationsDep = Annotated[InvestigationRepository, Depends(get_investigations)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/incidents", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
def create_incident(req: IncidentCreate, incidents: IncidentsDep) -> IncidentResponse:
    incident = incidents.create(req.description, req.severity, Source.REPORTED)
    return IncidentResponse.model_validate(incident)


@router.get("/incidents", response_model=list[IncidentResponse])
def list_incidents(
    incidents: IncidentsDep, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[IncidentResponse]:
    return [IncidentResponse.model_validate(i) for i in incidents.list(limit)]


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
def get_incident(incident_id: int, incidents: IncidentsDep) -> IncidentResponse:
    incident = incidents.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return IncidentResponse.model_validate(incident)


@router.post(
    "/incidents/{incident_id}/investigate",
    response_model=InvestigationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_investigation(
    incident_id: int, background: BackgroundTasks, service: ServiceDep
) -> InvestigationResponse:
    try:
        record = service.start(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found") from exc
    except InvestigationAlreadyRunningError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this incident is already being investigated"
        ) from exc
    background.add_task(service.run, record)
    return InvestigationResponse.model_validate(record)


@router.get("/incidents/{incident_id}/investigations", response_model=list[InvestigationResponse])
def list_investigations(
    incident_id: int, investigations: InvestigationsDep
) -> list[InvestigationResponse]:
    return [InvestigationResponse.model_validate(r) for r in investigations.list_for(incident_id)]


_NOTHING_WAITING = "this investigation has no recipe waiting for approval"


@router.post(
    "/investigations/{investigation_id}/approve",
    response_model=InvestigationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def approve_recipe(
    investigation_id: int, background: BackgroundTasks, service: ServiceDep
) -> InvestigationResponse:
    """Let the agent carry out the recipe it proposed."""
    try:
        record = service.approve(investigation_id)
    except NothingAwaitingApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOTHING_WAITING) from exc
    background.add_task(service.resume, record)
    return InvestigationResponse.model_validate(record)


@router.post("/investigations/{investigation_id}/decline", response_model=InvestigationResponse)
def decline_recipe(investigation_id: int, service: ServiceDep) -> InvestigationResponse:
    """End the reproduction without carrying out the recipe."""
    try:
        record = service.decline(investigation_id)
    except NothingAwaitingApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _NOTHING_WAITING) from exc
    return InvestigationResponse.model_validate(record)
