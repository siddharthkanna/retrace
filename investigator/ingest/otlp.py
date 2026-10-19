"""Turns logs and traces sent in the OpenTelemetry format (OTLP over HTTP) into table rows."""

import base64
import gzip
import zlib
from datetime import UTC, datetime
from typing import Any, NamedTuple

from google.protobuf import json_format
from google.protobuf.message import DecodeError, Message
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import Span, Status

JSON = "application/json"

UNKNOWN_SERVICE = "unknown"

# The levels the logs table uses, least severe first.
_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_OTHER_LEVEL_NAMES = {"TRACE": "DEBUG", "WARN": "WARNING", "FATAL": "CRITICAL"}


class OtlpError(ValueError):
    """What was sent could not be read."""


class SpanRow(NamedTuple):
    span_id: str
    trace_id: str
    parent_span_id: str | None
    service: str
    name: str
    kind: str
    start_time: datetime
    end_time: datetime
    status: str
    attributes: dict[str, Any]


class LogRow(NamedTuple):
    ts: datetime
    service: str
    level: str
    logger: str
    message: str
    trace_id: str | None
    span_id: str | None
    attributes: dict[str, Any]


def read_spans(body: bytes, content_type: str, content_encoding: str | None) -> list[SpanRow]:
    """Read one batch of spans, sent as protobuf or as JSON."""
    as_json = _is_json(content_type)
    batch = _parse(ExportTraceServiceRequest(), body, as_json, content_encoding)
    return [
        SpanRow(
            span_id=_hex(span.span_id, as_json),
            trace_id=_hex(span.trace_id, as_json),
            parent_span_id=_hex(span.parent_span_id, as_json),
            service=_service(group.resource),
            name=span.name,
            # An unspecified kind means an internal step.
            kind=Span.SpanKind.Name(span.kind)
            .removeprefix("SPAN_KIND_")
            .replace("UNSPECIFIED", "INTERNAL"),
            start_time=_time(span.start_time_unix_nano),
            end_time=_time(span.end_time_unix_nano),
            status=Status.StatusCode.Name(span.status.code).removeprefix("STATUS_CODE_"),
            attributes=_attributes(span.attributes),
        )
        for group in batch.resource_spans
        for scope in group.scope_spans
        for span in scope.spans
    ]


def read_logs(body: bytes, content_type: str, content_encoding: str | None) -> list[LogRow]:
    """Read one batch of log lines, sent as protobuf or as JSON."""
    as_json = _is_json(content_type)
    batch = _parse(ExportLogsServiceRequest(), body, as_json, content_encoding)
    return [
        LogRow(
            ts=_time(record.time_unix_nano or record.observed_time_unix_nano),
            service=_service(group.resource),
            level=_level(record),
            logger=scope.scope.name,
            message=_text(record.body),
            trace_id=_hex(record.trace_id, as_json),
            span_id=_hex(record.span_id, as_json),
            attributes=_attributes(record.attributes),
        )
        for group in batch.resource_logs
        for scope in group.scope_logs
        for record in scope.log_records
    ]


def _is_json(content_type: str) -> bool:
    return content_type.split(";")[0].strip().lower() == JSON


def _parse[M: Message](message: M, body: bytes, as_json: bool, content_encoding: str | None) -> M:
    try:
        if content_encoding == "gzip":
            body = gzip.decompress(body)
        if as_json:
            json_format.Parse(body, message, ignore_unknown_fields=True)
        else:
            message.ParseFromString(body)
    except (json_format.ParseError, DecodeError, OSError, EOFError, zlib.error) as exc:
        raise OtlpError(f"The request could not be read: {type(exc).__name__}.") from exc
    return message


def _hex(identifier: bytes, as_json: bool) -> str | None:
    if not identifier:
        return None
    # OTLP's JSON form writes IDs as hex, but the JSON reader takes them for base64.
    # Encoding them back gives the hex text that was sent.
    return base64.b64encode(identifier).decode().lower() if as_json else identifier.hex()


def _time(unix_nanoseconds: int) -> datetime:
    return datetime.fromtimestamp(unix_nanoseconds / 1e9, UTC)


def _service(resource: Resource) -> str:
    return str(_attributes(resource.attributes).get("service.name") or UNKNOWN_SERVICE)


def _attributes(pairs: list[KeyValue]) -> dict[str, Any]:
    return {pair.key: _value(pair.value) for pair in pairs}


def _value(value: AnyValue) -> Any:
    kind = value.WhichOneof("value")
    if kind is None:
        return None
    if kind == "array_value":
        return [_value(item) for item in value.array_value.values]
    if kind == "kvlist_value":
        return _attributes(value.kvlist_value.values)
    if kind == "bytes_value":
        return value.bytes_value.hex()
    return getattr(value, kind)


def _text(body: AnyValue) -> str:
    value = _value(body)
    return value if isinstance(value, str) else json_format.MessageToJson(body, indent=None)


def _level(record: LogRecord) -> str:
    """The record's level, in the names the logs table uses."""
    if record.severity_number:
        # OTLP numbers its levels 1-24, four to a level: TRACE, DEBUG, INFO, WARN, ERROR, FATAL.
        return _LEVELS[max(0, (record.severity_number - 5) // 4)]
    name = record.severity_text.upper()
    name = _OTHER_LEVEL_NAMES.get(name, name)
    return name if name in _LEVELS else "INFO"
