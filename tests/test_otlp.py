"""Checks for receiving logs and traces in the OpenTelemetry format."""

import gzip
import json
import os
import secrets
from datetime import UTC, datetime

import httpx
import pytest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span, Status

from investigator.ingest.otlp import OtlpError, read_logs, read_spans
from investigator.tools.logs import QueryLogsInput, query_logs
from investigator.tools.trace import GetTraceInput, get_trace

INVESTIGATOR = os.environ["INVESTIGATOR_URL"]
PROTOBUF = "application/x-protobuf"
# Nanoseconds since 1970, in 2023: in the past, so other tests' "since now" searches never
# find these rows.
STARTED = 1_700_000_000_000_000_000


def _text(key: str, value: str) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(string_value=value))


def _spans(trace_id: bytes, span_id: bytes) -> ExportTraceServiceRequest:
    """One failed server span from a service named orders."""
    batch = ExportTraceServiceRequest()
    group = batch.resource_spans.add()
    group.resource.attributes.append(_text("service.name", "orders"))
    group.scope_spans.add().spans.append(
        Span(
            trace_id=trace_id,
            span_id=span_id,
            name="POST /orders",
            kind=Span.SPAN_KIND_SERVER,
            start_time_unix_nano=STARTED,
            end_time_unix_nano=STARTED + 250_000_000,
            status=Status(code=Status.STATUS_CODE_ERROR),
            attributes=[
                _text("http.route", "/orders"),
                KeyValue(key="http.status_code", value=AnyValue(int_value=500)),
            ],
        )
    )
    return batch


def _logs(trace_id: bytes, span_id: bytes, **record) -> ExportLogsServiceRequest:
    """One log line from a service named orders."""
    batch = ExportLogsServiceRequest()
    group = batch.resource_logs.add()
    group.resource.attributes.append(_text("service.name", "orders"))
    scope = group.scope_logs.add()
    scope.scope.name = "orders.checkout"
    scope.log_records.add(
        time_unix_nano=STARTED,
        body=AnyValue(string_value="stock check failed"),
        trace_id=trace_id,
        span_id=span_id,
        attributes=[_text("order_id", "order-1")],
        **record,
    )
    return batch


def test_spans_sent_as_protobuf_are_read():
    trace_id, span_id = secrets.token_bytes(16), secrets.token_bytes(8)

    [span] = read_spans(_spans(trace_id, span_id).SerializeToString(), PROTOBUF, None)

    assert span.trace_id == trace_id.hex()
    assert span.span_id == span_id.hex()
    assert span.parent_span_id is None
    assert (span.service, span.name, span.kind, span.status) == (
        "orders",
        "POST /orders",
        "SERVER",
        "ERROR",
    )
    assert span.start_time == datetime.fromtimestamp(STARTED / 1e9, UTC)
    assert (span.end_time - span.start_time).total_seconds() == 0.25
    assert span.attributes == {"http.route": "/orders", "http.status_code": 500}


def test_spans_sent_as_json_keep_their_hex_ids():
    body = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "5B8EFFF798038103D269B633813FC60C",
                                "spanId": "eee19b7ec3c1b174",
                                "parentSpanId": "eee19b7ec3c1b173",
                                "name": "step",
                                "startTimeUnixNano": str(STARTED),
                                "endTimeUnixNano": str(STARTED),
                            }
                        ]
                    }
                ]
            }
        ]
    }

    [span] = read_spans(json.dumps(body).encode(), "application/json; charset=utf-8", None)

    assert span.trace_id == "5b8efff798038103d269b633813fc60c"
    assert span.span_id == "eee19b7ec3c1b174"
    assert span.parent_span_id == "eee19b7ec3c1b173"
    # Nothing said which service, what kind of step, or how it ended.
    assert (span.service, span.kind, span.status) == ("unknown", "INTERNAL", "UNSET")


def test_a_gzipped_batch_is_read():
    body = gzip.compress(
        _spans(secrets.token_bytes(16), secrets.token_bytes(8)).SerializeToString()
    )

    assert len(read_spans(body, PROTOBUF, "gzip")) == 1


@pytest.mark.parametrize(("body", "encoding"), [(b"\xff\xff\xff", None), (b"not gzip", "gzip")])
def test_a_batch_that_cannot_be_read_is_refused(body, encoding):
    with pytest.raises(OtlpError):
        read_spans(body, PROTOBUF, encoding)


def test_a_log_line_is_read():
    trace_id, span_id = secrets.token_bytes(16), secrets.token_bytes(8)
    batch = _logs(trace_id, span_id, severity_number=17)

    [log] = read_logs(batch.SerializeToString(), PROTOBUF, None)

    assert (log.service, log.level, log.logger, log.message) == (
        "orders",
        "ERROR",
        "orders.checkout",
        "stock check failed",
    )
    assert (log.trace_id, log.span_id) == (trace_id.hex(), span_id.hex())
    assert log.attributes == {"order_id": "order-1"}


@pytest.mark.parametrize(
    ("record", "level"),
    [
        ({"severity_number": 1}, "DEBUG"),  # TRACE
        ({"severity_number": 9}, "INFO"),
        ({"severity_number": 13}, "WARNING"),
        ({"severity_number": 24}, "CRITICAL"),  # FATAL4
        ({"severity_text": "warn"}, "WARNING"),
        ({"severity_text": "Error"}, "ERROR"),
        ({"severity_text": "notice"}, "INFO"),
        ({}, "INFO"),
    ],
)
def test_levels_are_stored_in_the_names_the_logs_table_uses(record, level):
    batch = _logs(b"", b"", **record)

    [log] = read_logs(batch.SerializeToString(), PROTOBUF, None)

    assert log.level == level
    assert (log.trace_id, log.span_id) == (None, None)


def test_what_a_system_sends_can_be_found_by_the_agents_tools(telemetry_pool):
    trace_id, span_id = secrets.token_bytes(16), secrets.token_bytes(8)
    headers = {"Content-Type": PROTOBUF}

    for _ in range(2):  # sent twice, as a sender does when it gets no answer
        sent = httpx.post(
            f"{INVESTIGATOR}/v1/traces",
            content=_spans(trace_id, span_id).SerializeToString(),
            headers=headers,
        )
        assert sent.status_code == 200
    sent = httpx.post(
        f"{INVESTIGATOR}/v1/logs",
        content=_logs(trace_id, span_id, severity_number=17).SerializeToString(),
        headers=headers,
    )
    assert sent.status_code == 200

    trace = get_trace(telemetry_pool, GetTraceInput(trace_id=trace_id.hex()))
    assert sorted((entry.type, entry.service) for entry in trace.timeline) == [
        ("log", "orders"),
        ("span", "orders"),
    ]
    found = query_logs(telemetry_pool, QueryLogsInput(trace_id=trace_id.hex(), min_level="ERROR"))
    assert [log.message for log in found.logs] == ["stock check failed"]


def test_a_json_batch_gets_a_json_reply():
    sent = httpx.post(f"{INVESTIGATOR}/v1/logs", json={"resourceLogs": []})

    assert sent.status_code == 200
    assert sent.json() == {}


def test_an_unreadable_batch_is_answered_with_400():
    sent = httpx.post(
        f"{INVESTIGATOR}/v1/traces", content=b"\xff\xff\xff", headers={"Content-Type": PROTOBUF}
    )

    assert sent.status_code == 400
