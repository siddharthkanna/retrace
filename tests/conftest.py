import pytest

from scenarios.base import reset


@pytest.fixture(autouse=True)
def healthy_system():
    yield
    reset()
