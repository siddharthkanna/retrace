"""Checks for the query_db tool, run against the real target database."""

import pytest
from psycopg_pool import ConnectionPool

from investigator.tools.database import MAX_ROWS, QueryDbInput, QueryDbOutput, query_db
from scenarios.base import charge, new_order_id, refund


def _run(pool: ConnectionPool, sql: str) -> QueryDbOutput:
    return query_db(pool, QueryDbInput(sql=sql))


def _count(pool: ConnectionPool, table: str) -> int:
    return _run(pool, f"SELECT count(*) FROM {table}").rows[0][0]


@pytest.fixture(scope="module")
def payment() -> dict:
    """One payment of 1000 with one refund of 400."""
    payment = charge(new_order_id(), 1000).json()
    refund(payment["id"], 400)
    return payment


def test_select_returns_columns_and_rows(target_pool, payment):
    result = _run(
        target_pool, f"SELECT order_id, amount_cents FROM payments WHERE id = {payment['id']}"
    )

    assert result.columns == ["order_id", "amount_cents"]
    assert result.rows == [[payment["order_id"], 1000]]
    assert result.row_count == 1
    assert result.error is None


def test_a_join_across_two_tables_works(target_pool, payment):
    result = _run(
        target_pool,
        "SELECT p.amount_cents, r.amount_cents FROM payments p"
        f" JOIN refunds r ON r.payment_id = p.id WHERE p.id = {payment['id']}",
    )

    assert result.rows == [[1000, 400]]


def test_a_large_result_is_capped_and_says_so(target_pool):
    result = _run(target_pool, "SELECT generate_series(1, 1000)")

    assert result.row_count == MAX_ROWS
    assert len(result.rows) == MAX_ROWS
    assert result.truncated


def test_a_result_that_fits_is_not_marked_truncated(target_pool):
    result = _run(target_pool, f"SELECT generate_series(1, {MAX_ROWS})")

    assert result.row_count == MAX_ROWS
    assert not result.truncated


def test_a_trailing_semicolon_is_accepted(target_pool):
    assert _run(target_pool, "SELECT 1;").rows == [[1]]


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM payments",
        "UPDATE payments SET status = 'changed'",
        "INSERT INTO payments (order_id) VALUES ('x')",
        "DROP TABLE refunds",
    ],
)
def test_statements_that_change_data_are_refused(target_pool, payment, statement):
    before = _count(target_pool, "payments"), _count(target_pool, "refunds")

    result = _run(target_pool, statement)

    assert result.error is not None
    assert result.rows == []
    assert (_count(target_pool, "payments"), _count(target_pool, "refunds")) == before


def test_two_statements_in_one_call_are_refused(target_pool):
    assert _run(target_pool, "SELECT 1; SELECT 2").error is not None


def test_a_delete_hidden_in_a_with_query_is_refused(target_pool, payment):
    before = _count(target_pool, "refunds")

    result = _run(target_pool, "WITH d AS (DELETE FROM refunds RETURNING *) SELECT * FROM d")

    assert "data-modifying" in result.error
    assert _count(target_pool, "refunds") == before


def test_a_mistake_returns_the_database_message(target_pool):
    result = _run(target_pool, "SELECT nope FROM payments")

    assert result.error == 'column "nope" does not exist'


def test_a_slow_query_is_cancelled(target_pool):
    result = _run(target_pool, "SELECT pg_sleep(8)")  # the login allows 5 seconds

    assert "timeout" in result.error
