"""A query parses its answer once, and formats it for the log only when DEBUG is on.

These tests run without a triple store: the stub in `_stub_store.py` answers, and the answer
counts how often its JSON is parsed.
"""

from __future__ import annotations

import json
import logging

import requests

from kapps_triplestore_interface import GraphDB, TripleStoreEndpoint, connect
from kapps_triplestore_interface.auth import BasicAuth
from tests._stub_store import (  # pylint: disable=unused-import
    BASE_URL,
    DATASET,
    PASSWORD,
    USERNAME,
    store,
)

ENDPOINT = TripleStoreEndpoint(url=BASE_URL, dataset=DATASET)
SELECT = "SELECT ?s WHERE { ?s ?p ?o }"
ANSWER = {"head": {"vars": ["s"]}, "results": {"bindings": []}}


class CountingResponse(requests.Response):
    """A 200 answer that counts its JSON parses."""

    def __init__(self):
        super().__init__()
        self.status_code = 200
        self.headers["Content-Type"] = "application/sparql-results+json"
        self._content = json.dumps(ANSWER).encode("utf-8")
        self.encoding = "utf-8"
        self.parses = 0

    def json(self, **kwargs):
        self.parses += 1
        return super().json(**kwargs)


def _store(stub, caplog, level) -> tuple[GraphDB, CountingResponse]:
    connected = connect(ENDPOINT, BasicAuth(USERNAME, PASSWORD))
    response = CountingResponse()
    stub.answers[f"/repositories/{DATASET}"] = response
    caplog.set_level(level, logger=connected.logger.name)
    caplog.clear()
    return connected, response


def test_at_info_a_query_parses_its_answer_once_and_logs_nothing(store, caplog):
    connected, response = _store(store, caplog, logging.INFO)

    assert connected.query(SELECT) == ANSWER
    assert response.parses == 1
    assert [r for r in caplog.records if r.name == connected.logger.name] == []


def test_at_debug_the_line_names_the_query_and_the_answer(store, caplog):
    connected, response = _store(store, caplog, logging.DEBUG)

    connected.query(SELECT)

    assert response.parses == 1
    line = caplog.records[-1].getMessage()
    assert SELECT in line
    assert str(ANSWER) in line


def test_at_debug_an_update_logs_its_success_line(store, caplog):
    connected, _ = _store(store, caplog, logging.DEBUG)
    update = requests.Response()
    update.status_code = 200
    store.answers[f"/repositories/{DATASET}/statements"] = update

    assert connected.query("INSERT DATA { <a:b> <a:c> <a:d> }", update=True) is True
    assert "Update successful (200)" in caplog.records[-1].getMessage()
