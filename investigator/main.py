"""Investigator: stores incidents and runs the agent on them."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from investigator.config import get_settings
from investigator.llm.openai_compatible import OpenAICompatibleClient
from investigator.repository import IncidentRepository, InvestigationRepository
from investigator.routes import router
from investigator.service import InvestigationService
from investigator.tools.code_history import Repo
from investigator.tools.registry import Resources, ToolRegistry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool = ConnectionPool(settings.database_url, open=True)
    telemetry_pool = ConnectionPool(settings.telemetry_database_url, open=True)
    target_pool = ConnectionPool(settings.target_database_url, open=True)
    model = OpenAICompatibleClient(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
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
    app.state.investigation_service = InvestigationService(
        incidents, investigations, model, settings.llm_model, registry
    )
    yield
    model.close()
    target_pool.close()
    telemetry_pool.close()
    pool.close()


app = FastAPI(title="investigator", lifespan=lifespan)
app.include_router(router)
