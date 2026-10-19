"""Investigator: stores incidents and runs the agent on them."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from psycopg_pool import ConnectionPool

from investigator.agent.usage import Prices
from investigator.config import Settings, get_settings
from investigator.ingest.repository import TelemetryRepository
from investigator.ingest.routes import router as ingest_router
from investigator.llm.openai_compatible import OpenAICompatibleClient
from investigator.repository import IncidentRepository, InvestigationRepository
from investigator.repro.runner import Target
from investigator.routes import router
from investigator.service import InvestigationService
from investigator.tools.code_history import Repo
from investigator.tools.database import read_only_pool
from investigator.tools.registry import Resources, ToolRegistry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    tracing = _send_agent_traces(settings)
    pool = ConnectionPool(settings.database_url, open=True)
    telemetry_pool = ConnectionPool(settings.telemetry_database_url, open=True)
    ingest_pool = ConnectionPool(settings.telemetry_ingest_database_url, open=True)
    target_pool = (
        read_only_pool(settings.target_database_url) if settings.target_database_url else None
    )
    model = OpenAICompatibleClient(
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_api_key,
        settings.llm_api_key_header,
    )
    registry = ToolRegistry(
        Resources(
            telemetry_pool=telemetry_pool,
            target_pool=target_pool,
            config_sources=settings.config_sources,
            repo=Repo(
                dir=settings.target_repo_dir,
                paths=tuple(settings.target_repo_paths),
                exclude=tuple(settings.target_repo_exclude),
                baseline=settings.target_repo_baseline,
            ),
        )
    )
    incidents = IncidentRepository(pool)
    investigations = InvestigationRepository(pool)
    # Anything still marked as running was cut off when the service last stopped.
    investigations.fail_interrupted()

    app.state.incidents = incidents
    app.state.investigations = investigations
    app.state.telemetry = TelemetryRepository(ingest_pool)
    target = (
        Target(settings.target_api_url, settings.config_sources, target_pool)
        if settings.target_api_url and target_pool
        else None
    )
    app.state.investigation_service = InvestigationService(
        incidents,
        investigations,
        model,
        settings.llm_model,
        registry,
        target,
        _prices(settings),
        ask_first=settings.reproduction_needs_approval,
    )
    yield
    if tracing:
        tracing.shutdown()
    model.close()
    if target_pool:
        target_pool.close()
    ingest_pool.close()
    telemetry_pool.close()
    pool.close()


def _send_agent_traces(settings: Settings) -> TracerProvider | None:
    """Export a trace of every investigation, if an address for them is set."""
    if not settings.agent_traces_endpoint:
        return None
    provider = TracerProvider(resource=Resource.create({"service.name": "retrace"}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.agent_traces_endpoint))
    )
    trace.set_tracer_provider(provider)
    return provider


def _prices(settings: Settings) -> Prices | None:
    if (
        settings.llm_price_input_per_million is None
        or settings.llm_price_output_per_million is None
    ):
        return None
    return Prices(settings.llm_price_input_per_million, settings.llm_price_output_per_million)


# FastAPI's own request spans are switched off: the traces sent are of the agent's work,
# one per investigation, not of every page refresh.
app = FastAPI(title="investigator", lifespan=lifespan, telemetry={"tracing": False})
app.include_router(router)
app.include_router(ingest_router)
