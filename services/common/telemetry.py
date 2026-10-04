"""One call that turns on tracing and logging for a service."""

import atexit
import logging
import queue
from logging.handlers import QueueHandler, QueueListener

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from services.common.log_handlers import JsonFormatter, PostgresLogHandler, TraceContextFilter
from services.common.span_exporter import PostgresSpanExporter

# Spans are written in batches; a short delay keeps evidence fresh for the investigator.
_EXPORT_DELAY_MS = 500


def setup_telemetry(
    app: FastAPI, service_name: str, database_url: str, excluded_urls: str | None = None
) -> None:
    _setup_tracing(app, service_name, database_url, excluded_urls)
    _setup_logging(service_name, database_url)


def _setup_tracing(
    app: FastAPI, service_name: str, database_url: str, excluded_urls: str | None
) -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(
            PostgresSpanExporter(database_url), schedule_delay_millis=_EXPORT_DELAY_MS
        )
    )
    trace.set_tracer_provider(provider)
    # Incoming requests become spans; outgoing httpx calls carry the trace ID along.
    FastAPIInstrumentor.instrument_app(
        app, excluded_urls=excluded_urls, exclude_spans=["send", "receive"]
    )
    HTTPXClientInstrumentor().instrument()


def _setup_logging(service_name: str, database_url: str) -> None:
    # Records are stamped with the trace ID on the request thread, then written
    # by a background thread so a slow log write never slows a request.
    log_queue: queue.Queue = queue.Queue()
    queue_handler = QueueHandler(log_queue)
    queue_handler.addFilter(TraceContextFilter())

    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(JsonFormatter(service_name))

    listener = QueueListener(
        log_queue, stdout_handler, PostgresLogHandler(database_url, service_name)
    )
    listener.start()
    atexit.register(listener.stop)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [queue_handler]
