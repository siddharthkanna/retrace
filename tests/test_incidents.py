"""End-to-end checks for the investigator's incident endpoints."""

import os

import httpx

INVESTIGATOR = os.environ["INVESTIGATOR_URL"]


def _open(description: str = "A customer was charged twice.", **fields: str) -> httpx.Response:
    return httpx.post(f"{INVESTIGATOR}/incidents", json={"description": description, **fields})


def test_open_then_fetch_an_incident():
    created = _open()
    assert created.status_code == 201
    incident = created.json()
    assert incident["severity"] == "medium"
    assert incident["status"] == "open"
    assert incident["source"] == "reported"

    fetched = httpx.get(f"{INVESTIGATOR}/incidents/{incident['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == incident


def test_severity_can_be_set():
    assert _open(severity="critical").json()["severity"] == "critical"


def test_invalid_severity_is_rejected():
    assert _open(severity="urgent").status_code == 422


def test_empty_description_is_rejected():
    assert _open(description="").status_code == 422


def test_system_fields_cannot_be_set():
    assert _open(status="resolved").status_code == 422
    assert _open(source="watcher").status_code == 422


def test_unknown_incident_is_404():
    assert httpx.get(f"{INVESTIGATOR}/incidents/999999999").status_code == 404


def test_list_is_newest_first_and_respects_limit():
    first = _open("first").json()
    second = _open("second").json()

    listed = httpx.get(f"{INVESTIGATOR}/incidents", params={"limit": 2}).json()
    assert [i["id"] for i in listed] == [second["id"], first["id"]]
