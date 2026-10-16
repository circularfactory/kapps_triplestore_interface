"""A store that gives no answer raises `TripleStoreUnavailableError`, chained to the transport error.

These tests run without a triple store. A local HTTP server answers the login and the
repository list as GraphDB does. For every other request it reads the request and then stays
silent, so that the client's timeout ends the request. A port on which nothing listens stands
for a store that cannot be reached.

The idle close of a pooled connection, and the one more send of a read after it, are tested in
`test_idle_connection_retry.py`.
"""

from __future__ import annotations

import json
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler

import pytest
import requests

from kapps_triplestore_interface import (
    IRI,
    GraphDB,
    GraphDBCredentials,
    TripleStoreUnavailableError,
)
from kapps_triplestore_interface.exceptions import TripleStoreInterfaceError

REPOSITORY = "repo"
READ = "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"
SUBJECT, PREDICATE, OBJECT = (
    IRI(f"http://example.org/unavailable#{name}") for name in ("s", "p", "o")
)
WRITE = f"INSERT DATA {{ {SUBJECT.n3()} {PREDICATE.n3()} {OBJECT.n3()} . }}"
# Long enough for the login and the list on a loaded machine, short enough for a fast suite.
TIMEOUT = 0.5


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 10

    def do_GET(self):
        self._serve(b"")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self._serve(self.rfile.read(length))

    do_PUT = do_POST

    def do_DELETE(self):
        self._serve(b"")

    def _serve(self, body: bytes):
        store: SilentStore = self.server.store
        if self.path == "/rest/login":
            self._send(200, b"", {"Authorization": "GDB token"})
            return
        if self.path == "/rest/repositories":
            self._send(200, json.dumps([{"id": REPOSITORY}]).encode("utf-8"))
            return
        store.record(self.path, body.decode("utf-8"))
        # Silent: the request is read, and no answer comes before the client gives up.
        store.released.wait(timeout=10)
        self.close_connection = True

    def _send(self, status: int, body: bytes, headers: dict | None = None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # keep the test output clean
        pass


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class SilentStore:
    """A local stand-in for GraphDB that answers no request but the login and the list."""

    def __init__(self):
        self._lock = threading.Lock()
        self.received: list[tuple[str, str]] = []
        self.released = threading.Event()
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.store = self
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, args=(0.05,), daemon=True
        )
        self._thread.start()

    def record(self, path: str, body: str):
        with self._lock:
            self.received.append((path, body))

    def requests_to(self, path: str) -> list[str]:
        with self._lock:
            return [body for received, body in self.received if received == path]

    def stop(self):
        self.released.set()
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def store():
    store = SilentStore()
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
        ),
        timeout=TIMEOUT,
    )
    yield db
    db.close()


def _closed_port() -> int:
    """A local port on which nothing listens: a connection to it is refused."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_a_store_that_cannot_be_reached_raises_unavailable_with_the_transport_error_as_cause():
    url = f"http://127.0.0.1:{_closed_port()}"

    with pytest.raises(TripleStoreUnavailableError) as failed:
        GraphDB(
            GraphDBCredentials(
                base_url=url,
                username="user",
                password="password",
                repository=REPOSITORY,
            )
        )

    assert isinstance(failed.value.__cause__, requests.ConnectionError)
    assert isinstance(failed.value, TripleStoreInterfaceError)
    assert not isinstance(failed.value, requests.RequestException)
    assert f"{url}/rest/login" in str(failed.value)


def test_a_read_that_times_out_raises_unavailable_and_is_not_sent_again(store, client):
    with pytest.raises(TripleStoreUnavailableError) as failed:
        client.query(READ)

    assert isinstance(failed.value.__cause__, requests.ReadTimeout)
    assert store.requests_to(f"/repositories/{REPOSITORY}") == [READ]


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(lambda db: db.query(WRITE, update=True), id="update"),
        pytest.param(
            lambda db: db.triples_add([(SUBJECT, PREDICATE, OBJECT)]),
            id="checked write",
        ),
        pytest.param(
            lambda db: db.graph_add(f"{SUBJECT.n3()} {PREDICATE.n3()} {OBJECT.n3()} ."),
            id="import",
        ),
        pytest.param(lambda db: db.graph_clear(), id="clear"),
    ],
)
def test_a_write_that_times_out_raises_unavailable_and_is_not_sent_again(
    store, client, write
):
    with pytest.raises(TripleStoreUnavailableError) as failed:
        write(client)

    assert isinstance(failed.value.__cause__, requests.ReadTimeout)
    assert len(store.received) == 1


def test_the_message_names_the_request_and_keeps_the_transport_error(store, client):
    with pytest.raises(TripleStoreUnavailableError) as failed:
        client.query(WRITE, update=True)

    message = str(failed.value)
    assert f"POST {store.url}/repositories/{REPOSITORY}/statements" in message
    assert str(failed.value.__cause__) in message
