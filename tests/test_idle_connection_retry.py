"""A read whose pooled connection the store closed while idle is sent again once; a write is not.

The remote GraphDB this was measured against closes a keep-alive connection that has been
idle for 5 s. When the client's next request leaves on that connection just as the store
closes it, the store reads nothing more and answers nothing, and the HTTP client raises
`requests.ConnectionError` with
`RemoteDisconnected('Remote end closed connection without response')`. Measured on
2026-10-02: 9 of 16 reads failed at an idle time of 5.0 s, and none at 4.5 s or 6.0 s. The
interface raises `TripleStoreUnavailableError`, chained to that error.

These tests run without a triple store. A local HTTP server answers the few requests the
client sends, over keep-alive connections. `expire_open_connections` marks every connection
that is open at that moment as idle past the store's limit: the next request on it is read,
and the connection is then closed without an answer. That is what the client sees when the
store's close crosses its request. A connection that the store closed well before the request
does not need this fix: urllib3 sees that it is dead and opens a new one.
"""

from __future__ import annotations

import itertools
import json
import socketserver
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler

import pytest
import requests
from rdflib import URIRef

from kapps_triplestore_interface import (
    IRI,
    GraphDB,
    GraphDBCredentials,
    TripleStoreUnavailableError,
)
from kapps_triplestore_interface.queries.checked_write import RECEIPT_GRAPH

REPOSITORY = "repo"
READ = "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"
SUBJECT, PREDICATE, OBJECT = (
    IRI(f"http://example.org/idle#{name}") for name in ("s", "p", "o")
)
WRITE = f"INSERT DATA {{ {SUBJECT.n3()} {PREDICATE.n3()} {OBJECT.n3()} . }}"
STATEMENT = f"{SUBJECT.n3()} {PREDICATE.n3()} {OBJECT.n3()} .\n"
GRAPH = IRI("http://example.org/idle#graph")
GRAPH_STORE_PATH_PREFIX = f"/repositories/{REPOSITORY}/rdf-graphs/service?"
ANSWER = {
    "head": {"vars": ["s"]},
    "results": {
        "bindings": [{"s": {"type": "uri", "value": "http://example.org/idle#s"}}]
    },
}


@dataclass
class Received:
    """One request as the store received it, and whether the store answered it."""

    connection: int
    path: str
    body: str
    answered: bool


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, so the client pools the connection
    timeout = 10  # a handler thread never outlives a stuck test by long

    def setup(self):
        super().setup()
        self.connection_id = self.server.store.opened()

    def finish(self):
        self.server.store.closed(self.connection_id)
        super().finish()

    def do_GET(self):
        self._serve(b"")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self._serve(self.rfile.read(length))

    def _serve(self, body: bytes):
        store: IdleClosingStore = self.server.store
        answered = not store.decide_close(self.connection_id)
        store.record(
            Received(self.connection_id, self.path, body.decode("utf-8"), answered)
        )
        if not answered:
            # The request is read; the connection closes with no status line.
            self.close_connection = True
            return
        self._answer()

    def _answer(self):
        if self.path == "/rest/login":
            self._send(200, b"", {"Authorization": "GDB token"})
        elif self.path == "/rest/repositories":
            self._send(200, json.dumps([{"id": REPOSITORY}]).encode("utf-8"))
        elif self.path.startswith(f"/repositories/{REPOSITORY}/rdf-graphs/service?"):
            self._send(200, STATEMENT.encode("utf-8"), content_type="text/plain")
        elif self.path == f"/repositories/{REPOSITORY}":
            self._send(200, json.dumps(ANSWER).encode("utf-8"))
        elif self.path == f"/repositories/{REPOSITORY}/statements":
            self._send(204, b"")
        else:
            self._send(404, b"")

    def _send(
        self,
        status: int,
        body: bytes,
        headers: dict | None = None,
        content_type: str = "application/json",
    ):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if body:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # keep the test output clean
        pass


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class IdleClosingStore:
    """A local stand-in for GraphDB that closes idle keep-alive connections on request."""

    def __init__(self):
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._open: set[int] = set()
        self._expired: set[int] = set()
        self.close_every_connection = False
        self.received: list[Received] = []
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.store = self
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, args=(0.05,), daemon=True
        )
        self._thread.start()

    def opened(self) -> int:
        with self._lock:
            connection = next(self._ids)
            self._open.add(connection)
            return connection

    def closed(self, connection: int):
        with self._lock:
            self._open.discard(connection)

    def record(self, received: Received):
        with self._lock:
            self.received.append(received)

    def decide_close(self, connection: int) -> bool:
        """Whether the store closes this connection instead of answering its request.

        An expired connection is closed once: the decision uses up its expiry.
        """
        with self._lock:
            if self.close_every_connection or connection in self._expired:
                self._expired.discard(connection)
                return True
            return False

    def expire_open_connections(self):
        """Every connection open now has been idle past the store's limit."""
        with self._lock:
            self._expired |= self._open

    def requests_to(self, path: str) -> list[Received]:
        with self._lock:
            return [received for received in self.received if received.path == path]

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def store():
    store = IdleClosingStore()
    yield store
    store.stop()


@pytest.fixture
def client(store):
    db = GraphDB(
        GraphDBCredentials(
            base_url=store.url,
            username="user",
            password="password",
            repository=REPOSITORY,
        )
    )
    yield db
    db.close()


def test_a_read_on_a_connection_the_store_closed_while_idle_is_sent_again_once(
    store, client
):
    store.expire_open_connections()

    assert client.query(READ) == ANSWER

    reads = store.requests_to(f"/repositories/{REPOSITORY}")
    assert [read.answered for read in reads] == [False, True]
    assert [read.body for read in reads] == [READ, READ]
    retry_reused_the_closed_connection = reads[1].connection == reads[0].connection
    assert not retry_reused_the_closed_connection


def test_a_write_on_a_connection_the_store_closed_while_idle_raises_and_is_not_sent_again(
    store, client
):
    store.expire_open_connections()

    with pytest.raises(TripleStoreUnavailableError) as failed:
        client.query(WRITE, update=True)

    assert isinstance(failed.value.__cause__, requests.ConnectionError)
    assert "RemoteDisconnected" in str(failed.value)
    writes = store.requests_to(f"/repositories/{REPOSITORY}/statements")
    assert [(write.body, write.answered) for write in writes] == [(WRITE, False)]


def test_a_checked_write_on_a_connection_the_store_closed_while_idle_is_not_sent_again(
    store, client
):
    """A checked write is an update: its precondition and its receipt travel in it.

    It is not sent again, and its receipt is not asked for: the store may still have
    applied it.
    """
    store.expire_open_connections()

    with pytest.raises(TripleStoreUnavailableError):
        client.triples_add([(SUBJECT, PREDICATE, OBJECT)])

    writes = store.requests_to(f"/repositories/{REPOSITORY}/statements")
    assert [write.answered for write in writes] == [False]
    assert str(RECEIPT_GRAPH) in writes[0].body
    assert store.requests_to(f"/repositories/{REPOSITORY}") == []


def test_a_read_whose_retry_fails_as_well_raises_unavailable(store, client):
    store.close_every_connection = True

    with pytest.raises(TripleStoreUnavailableError) as failed:
        client.query(READ)

    assert type(failed.value.__cause__) is requests.ConnectionError
    assert "RemoteDisconnected" in str(failed.value)
    reads = store.requests_to(f"/repositories/{REPOSITORY}")
    assert [read.answered for read in reads] == [False, False]  # sent again once only


def test_the_repository_list_on_a_connection_the_store_closed_while_idle_is_sent_again_once(
    store, client
):
    store.expire_open_connections()

    assert client.datasets_get(only_ids=True) == [REPOSITORY]

    # The first listing is the constructor's.
    lists = store.requests_to("/rest/repositories")
    assert [listing.answered for listing in lists] == [True, False, True]
    retry_reused_the_closed_connection = lists[2].connection == lists[1].connection
    assert not retry_reused_the_closed_connection


def test_graph_get_on_a_connection_the_store_closed_while_idle_is_sent_again_once(
    store, client
):
    store.expire_open_connections()

    graph = client.graph_get(GRAPH)

    assert (URIRef(SUBJECT), URIRef(PREDICATE), URIRef(OBJECT)) in graph
    fetches = [
        received
        for received in store.received
        if received.path.startswith(GRAPH_STORE_PATH_PREFIX)
    ]
    assert [fetch.answered for fetch in fetches] == [False, True]
    retry_reused_the_closed_connection = fetches[1].connection == fetches[0].connection
    assert not retry_reused_the_closed_connection


def test_a_read_outside_query_whose_retry_fails_as_well_is_sent_again_once_only(
    store, client
):
    store.close_every_connection = True

    with pytest.raises(TripleStoreUnavailableError):
        client.datasets_get()
    with pytest.raises(TripleStoreUnavailableError):
        client.graph_get(GRAPH)

    assert [r.answered for r in store.requests_to("/rest/repositories")][1:] == [
        False,
        False,
    ]
    fetches = [r for r in store.received if r.path.startswith(GRAPH_STORE_PATH_PREFIX)]
    assert [fetch.answered for fetch in fetches] == [False, False]


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(lambda db: db.datasets_get(), id="repository list"),
        pytest.param(lambda db: db.graph_get(GRAPH), id="graph_get"),
        pytest.param(lambda db: db.query(READ), id="query"),
    ],
)
def test_a_refused_connection_raises_unavailable_with_no_second_send(
    client, monkeypatch, read
):
    sends = []

    def refuse(session, method, url, **kwargs):
        sends.append(url)
        raise requests.ConnectionError(
            ConnectionRefusedError(111, "Connection refused")
        )

    monkeypatch.setattr(requests.Session, "request", refuse)

    with pytest.raises(TripleStoreUnavailableError) as failed:
        read(client)

    assert isinstance(failed.value.__cause__, requests.ConnectionError)
    assert len(sends) == 1
