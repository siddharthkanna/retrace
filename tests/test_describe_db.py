"""Checks for the describe_db tool, run against the real target database."""

import pytest
from psycopg_pool import ConnectionPool

from investigator.tools.database import DescribeDbInput, Table, describe_db
from scenarios.base import charge, new_order_id


@pytest.fixture(scope="module")
def described(target_pool: ConnectionPool) -> dict[str, Table]:
    """The tool's output, keyed by table name."""
    return {table.name: table for table in describe_db(target_pool, DescribeDbInput()).tables}


def test_lists_the_tables_of_the_target_database(described):
    assert set(described) == {"payments", "refunds"}


def test_columns_have_types_and_say_whether_they_are_required(described):
    columns = {column.name: column for column in described["payments"].columns}

    assert columns["order_id"].type == "text"
    assert not columns["order_id"].nullable
    assert columns["amount_cents"].type == "integer"
    assert columns["provider_charge_id"].nullable


def test_a_column_that_links_to_another_table_says_so(described):
    references = {column.name: column.references for column in described["refunds"].columns}

    assert references["payment_id"] == "payments.id"
    assert references["amount_cents"] is None


def test_row_counts_are_exact(target_pool):
    def payments_count() -> int:
        tables = describe_db(target_pool, DescribeDbInput()).tables
        return next(table.row_count for table in tables if table.name == "payments")

    before = payments_count()
    charge(new_order_id(), 100)

    assert payments_count() == before + 1
