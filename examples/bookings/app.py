"""A small room-booking API. It knows nothing about Retrace: it only uses OpenTelemetry."""

import logging
import os
import time
from datetime import date

import psycopg
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel

# Standard OpenTelemetry setup. Where it sends to comes from the OTEL_ environment variables.
tracing = TracerProvider()
tracing.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(tracing)
log_export = LoggerProvider()
log_export.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
logging.getLogger().addHandler(LoggingHandler(logger_provider=log_export))
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger("bookings")

DATABASE_URL = os.environ["DATABASE_URL"]

app = FastAPI(title="bookings-api")
FastAPIInstrumentor.instrument_app(app)


class Settings(BaseModel):
    # How long an availability answer may be reused. 0 means every booking asks the database.
    availability_cache_seconds: float = 0


class BookingRequest(BaseModel):
    room: str
    day: date
    guest: str


settings = Settings()
# (room, day) -> (whether it was free, when that was looked up)
_availability: dict[tuple[str, date], tuple[bool, float]] = {}


@app.get("/settings")
def get_settings() -> Settings:
    return settings


@app.put("/settings")
def set_settings(new: Settings) -> Settings:
    global settings
    if new != settings:
        logger.info(
            "settings updated",
            extra={"previous": settings.model_dump_json(), "current": new.model_dump_json()},
        )
    settings = new
    return settings


@app.post("/bookings", status_code=201)
def book(request: BookingRequest) -> dict:
    # ponytail: one connection per request; use a pool if this ever carries real traffic.
    with psycopg.connect(DATABASE_URL) as conn:
        if not _is_free(conn, request.room, request.day):
            logger.info("booking refused, room taken", extra=request.model_dump(mode="json"))
            raise HTTPException(status_code=409, detail="That room is taken on that day.")
        booking_id = conn.execute(
            "INSERT INTO bookings (room, day, guest) VALUES (%s, %s, %s) RETURNING id",
            (request.room, request.day, request.guest),
        ).fetchone()[0]
    logger.info(
        "booking confirmed", extra={"booking_id": booking_id, **request.model_dump(mode="json")}
    )
    return {"id": booking_id, **request.model_dump(mode="json")}


def _is_free(conn: psycopg.Connection, room: str, day: date) -> bool:
    cached = _availability.get((room, day))
    if cached and time.monotonic() - cached[1] < settings.availability_cache_seconds:
        logger.info(
            "availability answered from cache",
            extra={"room": room, "day": str(day), "free": cached[0]},
        )
        return cached[0]
    taken = conn.execute(
        "SELECT count(*) FROM bookings WHERE room = %s AND day = %s", (room, day)
    ).fetchone()[0]
    _availability[(room, day)] = (taken == 0, time.monotonic())
    return taken == 0
