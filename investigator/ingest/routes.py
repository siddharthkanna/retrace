"""HTTP endpoints that receive logs and traces in the OpenTelemetry format (OTLP over HTTP).

A system sends its telemetry here by setting OTEL_EXPORTER_OTLP_ENDPOINT to this service.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from investigator.ingest.otlp import JSON, OtlpError, read_logs, read_spans
from investigator.ingest.repository import TelemetryRepository

router = APIRouter()


def get_telemetry(request: Request) -> TelemetryRepository:
    return request.app.state.telemetry


TelemetryDep = Annotated[TelemetryRepository, Depends(get_telemetry)]


@router.post("/v1/traces")
async def receive_traces(request: Request, telemetry: TelemetryDep) -> Response:
    await run_in_threadpool(telemetry.add_spans, await _read(request, read_spans))
    return _accepted(request)


@router.post("/v1/logs")
async def receive_logs(request: Request, telemetry: TelemetryDep) -> Response:
    await run_in_threadpool(telemetry.add_logs, await _read(request, read_logs))
    return _accepted(request)


async def _read[Row](request: Request, read: Callable[[bytes, str, str | None], list[Row]]):
    try:
        return read(
            await request.body(),
            request.headers.get("content-type", ""),
            request.headers.get("content-encoding"),
        )
    except OtlpError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _accepted(request: Request) -> Response:
    """An empty success reply, in the format the request was sent in."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith(JSON):
        return Response(content="{}", media_type=JSON)
    return Response(content=b"", media_type="application/x-protobuf")
