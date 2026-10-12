import os
from collections.abc import Iterator

import pytest
from psycopg_pool import ConnectionPool

from scenarios.base import reset


@pytest.fixture(autouse=True)
def healthy_system():
    yield
    reset()


@pytest.fixture(scope="session")
def telemetry_pool() -> Iterator[ConnectionPool]:
    """Read-only connection to the logs and traces."""
    with ConnectionPool(os.environ["TELEMETRY_DATABASE_URL"], open=True) as pool:
        yield pool


@pytest.fixture(scope="session")
def target_pool() -> Iterator[ConnectionPool]:
    """Read-only connection to the database of the system being investigated."""
    with ConnectionPool(os.environ["TARGET_DATABASE_URL"], open=True) as pool:
        yield pool


@pytest.fixture(scope="session")
def investigator_pool() -> Iterator[ConnectionPool]:
    """The investigator's own database, where incidents and investigations are kept."""
    with ConnectionPool(os.environ["INVESTIGATOR_DATABASE_URL"], open=True) as pool:
        yield pool
