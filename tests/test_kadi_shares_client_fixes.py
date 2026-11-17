"""The client fixes that the Kadi store shares with GraphDB through `RDF4JClient`.

Three of the four fixes live in the shared client, and the Kadi store gets them: the sessions of
a client used again after `close()`, the namespaces in `ignored_prefixes`, and a 404 that names
the dataset as unknown. Kadi states its own errors in JSON, so a 404 of Kadi keeps its type and
its status line. The fourth fix, the login sent once more after an idle close, is GraphDB's
alone: a Kadi token is not renewed, so the Kadi store never logs in.

These tests run without a triple store. The stub in `_stub_store.py` answers as Kadi does.
"""

from __future__ import annotations

import json

import pytest
import requests
from rdflib import Namespace

from kapps_triplestore_interface import TripleStoreResponseError, connect_kadi
from kapps_triplestore_interface.exceptions import InvalidDatasetError
from tests._stub_store import BASE_URL, answer, store  # pylint: disable=unused-import

PAT = "pat_not-a-real-token"
NAME = "my-repository"
API = "/api/triple-store"
QUERY = f"{API}/repositories/{NAME}"
READ = "ASK { ?s ?p ?o }"
NO_CLASSES = json.dumps({"head": {"vars": ["class"]}, "results": {"bindings": []}})


@pytest.fixture(name="kadi")
def fixture_kadi(store):  # pylint: disable=redefined-outer-name
    """The stub answers as a Kadi instance whose triple store has the dataset `NAME`."""
    store.answers[API] = answer(200, json.dumps({"name": NAME}), "application/json")
    return store


def test_a_kadi_store_used_again_after_close_releases_its_new_session(
    kadi, monkeypatch
):  # pylint: disable=unused-argument
    events: dict[int, list[str]] = {}
    request = requests.Session.request
    close = requests.Session.close

    def recording(session, method, url, **kwargs):
        events.setdefault(id(session), []).append("request")
        return request(session, method, url, **kwargs)

    def closing(session):
        events.setdefault(id(session), []).append("close")
        close(session)

    monkeypatch.setattr(requests.Session, "request", recording)
    monkeypatch.setattr(requests.Session, "close", closing)
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    # `connect_kadi` asks Kadi through a session of its own, closed at once.
    events.clear()

    connected.query(READ)
    connected.close()
    connected.query(READ)
    connected.close()

    assert len(events) == 2
    assert all(steps[-1] == "close" for steps in events.values()), events


def test_a_namespace_in_ignored_prefixes_goes_through_kadi_as_a_string(kadi):
    kadi.answers[QUERY] = answer(200, NO_CLASSES, "application/sparql-results+json")
    connected = connect_kadi(host=BASE_URL, pat=PAT)

    connected.owl_get_classes_of_individual(
        "http://example.org/i",
        ignored_prefixes=[Namespace("http://example.org/ignored#"), "owl"],
    )

    sent = kadi.bodies[-1]
    assert '!STRSTARTS(STR(?class), "http://example.org/ignored#")' in sent
    assert "!STRSTARTS(STR(?class), STR(owl:))" in sent


def test_a_404_in_kadis_json_keeps_its_type_and_status_line(kadi):
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    kadi.answers[QUERY] = answer(
        404,
        json.dumps({"code": 404, "message": "Not Found", "description": "Not found."}),
        "application/json",
    )

    with pytest.raises(TripleStoreResponseError) as error:
        connected.query(READ)
    assert not isinstance(error.value, InvalidDatasetError)
    assert str(error.value) == "404 Not Found: Not found."
    assert error.value.status == 404


def test_a_404_that_names_the_dataset_unknown_raises_invalid_dataset_through_kadi(kadi):
    """Should Kadi pass on the answer of its RDF4J store, the dataset is named as missing."""
    connected = connect_kadi(host=BASE_URL, pat=PAT)
    kadi.answers[QUERY] = answer(404, f"Unknown repository: {NAME}")

    with pytest.raises(InvalidDatasetError, match=NAME):
        connected.query(READ)
