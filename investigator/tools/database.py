"""describe_db and query_db: look at the database of the system being investigated."""

from typing import Any

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field


class DescribeDbInput(BaseModel):
    """describe_db takes no input."""

    model_config = ConfigDict(extra="forbid")


class Column(BaseModel):
    name: str
    type: str
    nullable: bool
    # Set when this column points at another table, for example "payments.id".
    references: str | None = None


class Table(BaseModel):
    name: str
    row_count: int
    columns: list[Column]


class DescribeDbOutput(BaseModel):
    tables: list[Table]


def describe_db(pool: ConnectionPool, request: DescribeDbInput) -> DescribeDbOutput:
    """Return every table the login can read, with its columns, links and size."""
    with pool.connection() as conn:
        columns = conn.execute(
            "SELECT table_name, column_name, data_type, is_nullable = 'YES'"
            " FROM information_schema.columns WHERE table_schema = 'public'"
            " ORDER BY table_name, ordinal_position"
        ).fetchall()

        # information_schema hides foreign keys from a read-only login, so these
        # come from pg_catalog. Only single-column links are reported.
        links = {
            (table, column): f"{ref_table}.{ref_column}"
            for table, column, ref_table, ref_column in conn.execute(
                "SELECT c.conrelid::regclass::text, a.attname,"
                " c.confrelid::regclass::text, af.attname"
                " FROM pg_constraint c"
                " JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]"
                " JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = c.confkey[1]"
                " WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace"
            )
        }

        tables: dict[str, Table] = {}
        for table, column, data_type, nullable in columns:
            if table not in tables:
                row_count = conn.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()[0]
                tables[table] = Table(name=table, row_count=row_count, columns=[])
            tables[table].columns.append(
                Column(
                    name=column,
                    type=data_type,
                    nullable=nullable,
                    references=links.get((table, column)),
                )
            )

    return DescribeDbOutput(tables=list(tables.values()))


MAX_ROWS = 50


class QueryDbInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(
        min_length=1,
        max_length=4000,
        description=(
            "One read-only SELECT statement. Call describe_db first to see the tables and columns."
        ),
    )


class QueryDbOutput(BaseModel):
    columns: list[str] = []
    rows: list[list[Any]] = []
    row_count: int = 0
    truncated: bool = False
    # Set instead of rows when the statement was refused or failed.
    error: str | None = None


def query_db(pool: ConnectionPool, request: QueryDbInput) -> QueryDbOutput:
    """Run one read-only SELECT and return at most MAX_ROWS rows."""
    statement = request.sql.strip().rstrip(";").strip()
    if not statement.lower().startswith(("select", "with")) or ";" in statement:
        return QueryDbOutput(error="Only a single SELECT statement is allowed.")

    try:
        # A server-side cursor: the database hands over only the rows we ask for,
        # and it refuses anything that is not a single read query.
        with pool.connection() as conn, conn.cursor(name="query_db") as cur:
            cur.execute(statement)
            rows = cur.fetchmany(MAX_ROWS + 1)
            columns = [column.name for column in cur.description]
    except psycopg.Error as exc:
        return QueryDbOutput(error=exc.diag.message_primary or str(exc))

    return QueryDbOutput(
        columns=columns,
        rows=[list(row) for row in rows[:MAX_ROWS]],
        row_count=min(len(rows), MAX_ROWS),
        truncated=len(rows) > MAX_ROWS,
    )
