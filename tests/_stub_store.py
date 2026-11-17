"""A stub of GraphDB's HTTP answers, for the offline tests of `connect()` and the auth providers.

`requests.Session.request` is replaced by a `StubStore`, so that every request goes through the
adapter's own request path, as it does against a store. The stub records each request with the
`Authorization` header that it carried. Each login issues a new token, and the stub accepts only
the tokens that it issued and that a test has not expired.
"""

from __future__ import annotations

import itertools
import json
import re

import pytest
import requests

BASE_URL = "http://store.example.org:7200"
DATASET = "repo"
USERNAME = "user"
PASSWORD = "secret"

# What the stub answers to a CONSTRUCT or DESCRIBE, as N-Triples: a triple of IRIs, one with a
# language-tagged literal outside ASCII, and one with a typed literal on a blank node.
GRAPH_ANSWER = (
    "<http://example.org/s> <http://example.org/p> <http://example.org/o> .\n"
    '<http://example.org/s> <http://example.org/label> "Grüße"@de .\n'
    '_:b0 <http://example.org/count> "7"^^<http://www.w3.org/2001/XMLSchema#integer> .\n'
)
N_TRIPLES = "application/n-triples"

# The prologue of a query: BASE and PREFIX declarations and comments. The stub reads the query
# form after it to pick the format of its answer, as the store does; the client reads nothing.
_PROLOGUE = re.compile(
    r"\A(?:\s+|#[^\n]*|BASE\s*<[^>]*>|PREFIX\s+[^\s:]*:\s*<[^>]*>)*",
    re.IGNORECASE,
)


def is_graph_query(query: object) -> bool:
    """Whether `query` is a CONSTRUCT or a DESCRIBE, after its prologue."""
    if not isinstance(query, str):
        return False
    prologue = _PROLOGUE.match(query)
    rest = query[prologue.end() :] if prologue else query
    return re.match(r"(CONSTRUCT|DESCRIBE)\b", rest, re.IGNORECASE) is not None


def answer(status: int, body: str = "", media_type: str = "text/plain;charset=UTF-8"):
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = media_type
    response._content = body.encode("utf-8")
    response.encoding = "utf-8"
    return response


class StubStore:
    """Answers as GraphDB does, unless a test sets the answer of a path.

    - `/rest/login` issues a new token, `GDB token-1`, `GDB token-2`, ...
    - Any other request that carries a token which the stub did not issue, or which a test
      expired, gets 401.
    - A query on the dataset answers `true`, and the repository list names the dataset.
    - A CONSTRUCT or DESCRIBE answers `GRAPH_ANSWER` as N-Triples when its `Accept` offers
      N-Triples, as the store's content negotiation does, and 406 when it does not.
    """

    def __init__(self):
        self.sent: list[tuple[str, str, str | None]] = []
        self.bodies: list[object] = []
        # The query parameters and the headers of each request, in the order of `sent`.
        self.params: list[object] = []
        self.headers: list[dict[str, str]] = []
        self.answers: dict[str, requests.Response] = {}
        # The answer to one method on one path, such as `("DELETE", "/a/b")`. It wins over
        # an answer in `answers` for the same path.
        self.method_answers: dict[tuple[str, str], requests.Response] = {}
        self.unreachable = False
        self._numbers = itertools.count(1)
        self._valid: set[str] = set()

    def expire(self, token: str) -> None:
        """The store no longer accepts `token`, as after its validity or a restart."""
        self._valid.discard(token)

    def paths(self) -> list[str]:
        return [path for _, path, _ in self.sent]

    def __call__(self, method, url, headers=None, **kwargs):
        path = url.removeprefix(BASE_URL)
        authorization = (headers or {}).get("Authorization")
        self.sent.append((method.upper(), path, authorization))
        self.bodies.append(kwargs.get("data", kwargs.get("json")))
        self.params.append(kwargs.get("params"))
        self.headers.append(dict(headers or {}))
        if self.unreachable:
            raise requests.ConnectionError(
                f"Failed to establish a new connection: {url}"
            )
        if (method.upper(), path) in self.method_answers:
            return self.method_answers[(method.upper(), path)]
        if path in self.answers:
            return self.answers[path]
        if path == "/rest/login":
            return self._login()
        if authorization is not None and authorization.startswith("GDB "):
            if authorization not in self._valid:
                return answer(401, "Unauthorized")
        if path == "/rest/repositories":
            return answer(200, json.dumps([{"id": DATASET}]), "application/json")
        if is_graph_query(kwargs.get("data")):
            if N_TRIPLES not in (headers or {}).get("Accept", ""):
                return answer(406, "No acceptable file format found.")
            rdf_answer = answer(200, GRAPH_ANSWER, N_TRIPLES)
            # A client that decoded the body as text by this guess would garble "Grüße".
            rdf_answer.encoding = "ISO-8859-1"
            return rdf_answer
        return answer(
            200,
            json.dumps({"head": {}, "boolean": True}),
            "application/sparql-results+json",
        )

    def _login(self):
        token = f"GDB token-{next(self._numbers)}"
        self._valid.add(token)
        body = {"username": USERNAME}
        response = answer(200, json.dumps(body), "application/json")
        response.headers["Authorization"] = token
        return response


@pytest.fixture
def store(monkeypatch) -> StubStore:
    stub = StubStore()
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda session, method, url, **kwargs: stub(method, url, **kwargs),
    )
    return stub
