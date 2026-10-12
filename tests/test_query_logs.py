"""Checks for the query_logs tool, run against real logs."""

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from investigator.tools.logs import MAX_LOGS, QueryLogsInput, QueryLogsOutput, query_logs
from scenarios.base import charge, new_order_id, refund
from tests.helpers import wait_for


def _search(telemetry_pool: ConnectionPool, **filters: Any) -> QueryLogsOutput:
    return query_logs(telemetry_pool, QueryLogsInput(**filters))


@pytest.fixture(scope="module")
def order_id(telemetry_pool: ConnectionPool) -> str:
    """Make one charge and wait until all three of its log lines are stored."""
    order_id = new_order_id()
    charge(order_id, 500)
    assert wait_for(lambda: _search(telemetry_pool, contains=order_id).total_matches == 3)
    return order_id


@pytest.fixture(scope="module")
def trace_id(telemetry_pool: ConnectionPool, order_id: str) -> str:
    return _search(telemetry_pool, contains=order_id).logs[0].trace_id


def test_contains_finds_text_inside_the_details(telemetry_pool, order_id):
    result = _search(telemetry_pool, contains=order_id)

    assert [log.message for log in result.logs] == [
        "charge requested",
        "charge created",
        "payment recorded",
    ]
    assert not result.truncated


def test_trace_id_returns_one_request_in_time_order(telemetry_pool, trace_id):
    logs = _search(telemetry_pool, trace_id=trace_id).logs

    assert logs[0].message == "charge requested"
    assert logs[-1].message == "payment recorded"
    assert {log.trace_id for log in logs} == {trace_id}
    assert [log.timestamp for log in logs] == sorted(log.timestamp for log in logs)


def test_service_narrows_to_one_service(telemetry_pool, trace_id):
    logs = _search(telemetry_pool, trace_id=trace_id, service="provider-mock").logs

    assert [log.message for log in logs] == ["charge created"]


def test_min_level_leaves_out_less_severe_lines(telemetry_pool):
    started = datetime.now(UTC)
    refund(999_999_999, 100)  # refused, which writes one WARNING line

    logs = wait_for(lambda: _search(telemetry_pool, since=started, min_level="WARNING").logs)

    assert "request rejected" in {log.message for log in logs}
    assert {log.level for log in logs} <= {"WARNING", "ERROR", "CRITICAL"}


def test_since_and_until_bound_the_results(telemetry_pool, trace_id):
    logs = _search(telemetry_pool, trace_id=trace_id).logs
    first, last = logs[0], logs[-1]

    before = _search(telemetry_pool, trace_id=trace_id, until=first.timestamp).logs
    after = _search(telemetry_pool, trace_id=trace_id, since=last.timestamp).logs

    assert first in before and last not in before
    assert last in after and first not in after


def test_a_broad_search_is_capped_and_says_so(telemetry_pool):
    for _ in range(15):  # each charge writes several lines, so this passes the cap
        charge(new_order_id(), 100)
    assert wait_for(lambda: _search(telemetry_pool).total_matches > MAX_LOGS)

    result = _search(telemetry_pool)

    assert len(result.logs) == MAX_LOGS
    assert result.truncated
    assert result.total_matches > MAX_LOGS


def test_the_tool_connection_cannot_write(telemetry_pool):
    with telemetry_pool.connection() as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM logs")
