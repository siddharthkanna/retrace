"""Checks for the get_config tool, run against the real payment API."""

from investigator.tools.configuration import GetConfigInput, GetConfigOutput, get_config
from scenarios.base import API, PROVIDER, set_flags

FLAGS = {"payment-api": f"{API}/admin/flags"}
UNREACHABLE = {"missing": "http://no-such-host.invalid:9/settings"}


def _read(sources: dict[str, str]) -> GetConfigOutput:
    return get_config(sources, GetConfigInput())


def test_returns_the_current_settings_of_a_source():
    (source,) = _read(FLAGS).sources

    assert source.source == "payment-api"
    assert source.values == {"forward_idempotency_key": True, "refund_row_locking": True}
    assert source.error is None


def test_a_changed_setting_shows_up_on_the_next_read():
    set_flags(refund_row_locking=False)

    (source,) = _read(FLAGS).sources

    assert source.values["refund_row_locking"] is False


def test_an_unreachable_source_is_reported_as_an_error():
    (source,) = _read(UNREACHABLE).sources

    assert source.values is None
    assert "ConnectError" in source.error


def test_a_failing_source_does_not_stop_the_others():
    working, failing = _read(FLAGS | UNREACHABLE).sources

    assert working.values is not None
    assert failing.error is not None


def test_a_reply_that_is_not_named_settings_is_reported_as_an_error():
    (source,) = _read({"a-list": f"{PROVIDER}/charges"}).sources

    assert source.values is None
    assert source.error == "the source did not return named settings"


def test_with_no_sources_the_result_is_empty():
    assert _read({}).sources == []
