"""A stub of GraphDB's HTTP answers, for the offline tests of `connect()` and the auth providers.

`requests.Session.request` is replaced by a `StubStore`, so that every request goes through the
adapter's own request path, as it does against a store. The stub records each request with the
`Authorization` header that it carried. Each login issues a new token, and the stub accepts only
the tokens that it issued and that a test has not expired.
"""

from __future__ import annotations

import itertools
import json

import pytest
import requests

BASE_URL = "http://store.example.org:7200"
DATASET = "repo"
USERNAME = "user"
PASSWORD = "secret"


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
