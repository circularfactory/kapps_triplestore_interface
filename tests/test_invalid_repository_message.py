"""The invalid-repository error tells a wrong name from a server that has no repositories yet.

These tests run without a triple store. The server's answer to the repository list is mocked.
"""

from types import SimpleNamespace

import pytest

from kapps_triplestore_interface import GraphDB, GraphDBCredentials
from kapps_triplestore_interface.exceptions import InvalidDatasetError

BASE_URL = "http://graphdb.example.org:7200"


def connect(
    monkeypatch: pytest.MonkeyPatch, repositories: list[str], wanted_repository: str
) -> GraphDB:
    """Open a client on `wanted_repository` while the mocked server lists `repositories`."""
    monkeypatch.setattr(
        GraphDB, "_get_authentication_token", lambda self, user, password: "t"
    )
    monkeypatch.setattr(
        GraphDB,
        "_make_request",
        lambda self, method, endpoint, **kwargs: SimpleNamespace(
            status_code=200, json=lambda: [{"id": repo} for repo in repositories]
        ),
    )
    credentials = GraphDBCredentials(
        base_url=BASE_URL,
        username="user",
        password="secret",
        repository=wanted_repository,
    )
    return GraphDB(credentials=credentials)


def test_server_without_repositories_says_so_and_names_the_server(monkeypatch):
    with pytest.raises(InvalidDatasetError) as error:
        connect(monkeypatch, [], "Wanted")
    message = str(error.value)
    assert "no repositories" in message
    assert BASE_URL in message
    assert "Allowed values" not in message


def test_name_missing_from_a_non_empty_list_keeps_the_message(monkeypatch):
    with pytest.raises(InvalidDatasetError) as error:
        connect(monkeypatch, ["One", "Two"], "Wanted")
    assert str(error.value) == "Invalid repository name. Allowed values are: One, Two."
