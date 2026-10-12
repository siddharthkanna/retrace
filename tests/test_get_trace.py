"""Checks for the get_trace tool, run against a real request."""

import pytest
from psycopg_pool import ConnectionPool

from investigator.tools.logs import QueryLogsInput, query_logs
from investigator.tools.trace import GetTraceInput, GetTraceOutput, get_trace
from scenarios.base import charge, new_order_id
from tests.helpers import wait_for


@pytest.fixture(scope="module")
def trace(telemetry_pool: ConnectionPool) -> GetTraceOutput:
    """Make one charge and wait until its whole trace is stored."""
    order_id = new_order_id()
    charge(order_id, 500)
    logs = wait_for(lambda: query_logs(telemetry_pool, QueryLogsInput(contains=order_id)).logs)
    trace_id = logs[0].trace_id

    def complete_trace() -> GetTraceOutput | None:
        result = get_trace(telemetry_pool, GetTraceInput(trace_id=trace_id))
        kinds = [entry.type for entry in result.timeline]
        # A healthy charge leaves 3 spans and 5 log lines.
        return result if (kinds.count("span"), kinds.count("log")) == (3, 5) else None

    result = wait_for(complete_trace)
    assert result is not None, "the trace never became complete"
    return result


def test_trace_has_spans_and_logs_from_both_services(trace):
    assert trace.found
    assert {(entry.type, entry.service) for entry in trace.timeline} == {
        ("span", "payment-api"),
        ("log", "payment-api"),
        ("span", "provider-mock"),
        ("log", "provider-mock"),
    }


def test_timeline_is_in_time_order(trace):
    timestamps = [entry.timestamp for entry in trace.timeline]

    assert timestamps == sorted(timestamps)


def test_a_log_line_comes_after_the_span_it_was_written_in(trace):
    span_position = {
        entry.span_id: index for index, entry in enumerate(trace.timeline) if entry.type == "span"
    }

    for index, entry in enumerate(trace.timeline):
        if entry.type == "log":
            assert span_position[entry.span_id] < index


def test_summary_describes_the_request(trace):
    assert trace.services == ["payment-api", "provider-mock"]
    assert trace.started_at == trace.timeline[0].timestamp
    assert trace.duration_ms > 0
    assert not trace.truncated


def test_unknown_trace_is_reported_as_not_found(telemetry_pool):
    result = get_trace(telemetry_pool, GetTraceInput(trace_id="no-such-trace"))

    assert not result.found
    assert result.timeline == []
    assert result.duration_ms is None
