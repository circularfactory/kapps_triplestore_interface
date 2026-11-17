"""`close()` releases every session the client opened, also when the client is used again after it.

These tests run without a triple store. The stub in `_stub_store.py` answers as GraphDB does.
Each session's requests and its `close()` are recorded in order: a session is released when the
last thing that happened to it is `close()`. A session closed once and then used again holds a
connection pool once more, and is not released.

The other thread is one long-lived thread, the same before and after the first `close()`: a new
thread would get a new session anyway, and would not show what a thread's old session does.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

from kapps_triplestore_interface import BasicAuth, GraphDB, TripleStoreEndpoint
from tests._stub_store import (  # pylint: disable=unused-import
    BASE_URL,
    DATASET,
    PASSWORD,
    USERNAME,
    store,
)

READ = "ASK { ?s ?p ?o }"


@pytest.fixture
def events(store, monkeypatch) -> dict[int, list[str]]:
    """The events of each session, by its `id`: "request" and "close", in order."""
    recorded: dict[int, list[str]] = {}
    answer = requests.Session.request
    close = requests.Session.close

    def request(session, method, url, **kwargs):
        recorded.setdefault(id(session), []).append("request")
        return answer(session, method, url, **kwargs)

    def closing(session):
        recorded.setdefault(id(session), []).append("close")
        close(session)

    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setattr(requests.Session, "close", closing)
    return recorded


@pytest.fixture
def adapter(store) -> GraphDB:
    return GraphDB(
        endpoint=TripleStoreEndpoint(url=BASE_URL, dataset=DATASET),
        auth=BasicAuth(USERNAME, PASSWORD),
    )


def _released(events: dict[int, list[str]]) -> dict[int, bool]:
    return {session: steps[-1] == "close" for session, steps in events.items()}


def test_a_client_used_again_after_close_has_closed_every_session_at_its_next_close(
    adapter, events
):
    with ThreadPoolExecutor(max_workers=1) as other_thread:
        adapter.query(READ)
        other_thread.submit(adapter.query, READ).result()
        adapter.close()

        adapter.query(READ)
        other_thread.submit(adapter.query, READ).result()
        adapter.close()

    assert len(events) >= 2
    assert all(_released(events).values()), events


def test_a_request_after_close_does_not_reuse_the_closed_session(adapter, events):
    adapter.query(READ)
    before = adapter._session
    adapter.close()

    adapter.query(READ)

    assert adapter._session is not before
    assert events[id(before)] == ["request", "close"]


def test_a_close_while_a_request_is_on_its_way_still_releases_that_session(
    adapter, events, monkeypatch
):
    """`close()` of another thread crosses a request: the request opens a connection pool in
    the session again. The session is closed once the request returns."""
    request = requests.Session.request
    crossed = []

    def close_on_the_way(session, method, url, **kwargs):
        if not crossed:
            crossed.append(True)
            with ThreadPoolExecutor(max_workers=1) as other_thread:
                other_thread.submit(adapter.close).result()
        return request(session, method, url, **kwargs)

    monkeypatch.setattr(requests.Session, "request", close_on_the_way)

    adapter.query(READ)

    assert crossed
    assert all(_released(events).values()), events
