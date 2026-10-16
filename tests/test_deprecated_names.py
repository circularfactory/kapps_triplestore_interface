"""The old names still work for one release, and each use of one warns once and names its successor.

The interface's public names follow one convention and name no vendor, as the triple store
border decision of the KAPPS family states. Each name that this release replaces stays as a
deprecated alias:

| Old | New |
|---|---|
| `fetch_statements` | `graph_get` |
| `import_statements` | `graph_add` |
| `clear_graph` | `graph_clear` |
| `get_list_of_named_graphs` | `graphs_get` |
| `get_list_of_repositories` | `datasets_get` |
| the store's `repository` attribute | `dataset` |
| `GraphDBCredentials` | `TripleStoreEndpoint` and an auth provider |
| the `use_gdb_token` flag | `GDBTokenAuth`, and `BasicAuth` for `use_gdb_token=False` |
| `InvalidRepositoryError` | `InvalidDatasetError` |

These tests run without a triple store. `requests.Session.request` is replaced by a fake that
answers each request as GraphDB does, so every request goes through the adapter's own request
path, as it does against a store.
"""

from __future__ import annotations

import importlib
import inspect
import json
import warnings
from typing import Callable

import pytest
import requests
from rdflib import Graph

from kapps_triplestore_interface import (
    BasicAuth,
    GDBTokenAuth,
    GraphDB,
    TripleStore,
    TripleStoreEndpoint,
)
from kapps_triplestore_interface.exceptions import (
    InvalidDatasetError,
    TripleStoreResponseError,
)

BASE_URL = "http://store.example.org:7200"
DATASET = "repo"
OTHER = "other"
USERNAME = "user"
PASSWORD = "secret"
GRAPH = "http://example.org/deprecated-names#graph"
NAMED_GRAPHS = ["http://example.org/deprecated-names#one"]
STATEMENT = (
    "<http://example.org/deprecated-names#s> <http://example.org/deprecated-names#p>"
    ' "o" .\n'
)


def _answer(status: int, body: str = "", media_type: str = "text/plain"):
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = media_type
    response._content = body.encode("utf-8")
    response.encoding = "utf-8"
    return response


class FakeStore:
    """Answers as GraphDB does: the graph store, the queries, the repository list and the login.

    Each request is recorded as `(method, path, params, body, Authorization header)`. A test
    that sets `graph_store_answer` gets that answer for every request to the graph store.
    """

    def __init__(self):
        self.sent: list[tuple] = []
        self.graph_store_answer: requests.Response | None = None

    def __call__(self, method, url, headers=None, params=None, data=None, **kwargs):
        path = url.removeprefix(BASE_URL)
        authorization = (headers or {}).get("Authorization")
        self.sent.append((method.upper(), path, params, data, authorization))
        method = method.upper()
        if path == "/rest/login":
            response = _answer(200, json.dumps({"authorities": []}), "application/json")
            response.headers["Authorization"] = "GDB token-1"
            return response
        if path == "/rest/repositories":
            return _answer(
                200, json.dumps([{"id": DATASET}, {"id": OTHER}]), "application/json"
            )
        if "/rdf-graphs/service" in path:
            if self.graph_store_answer is not None:
                return self.graph_store_answer
            if method == "GET":
                return _answer(200, STATEMENT, "application/n-triples")
            return _answer(204)
        bindings = [{"graph": {"type": "uri", "value": g}} for g in NAMED_GRAPHS]
        return _answer(
            200,
            json.dumps(
                {"head": {"vars": ["graph"]}, "results": {"bindings": bindings}}
            ),
            "application/sparql-results+json",
        )


@pytest.fixture(name="fake")
def _fake(monkeypatch) -> FakeStore:
    stub = FakeStore()
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda session, method, url, **kwargs: stub(method, url, **kwargs),
    )
    return stub


@pytest.fixture(name="client")
def _client(fake) -> GraphDB:  # pylint: disable=unused-argument
    return GraphDB(
        endpoint=TripleStoreEndpoint(url=BASE_URL, dataset=DATASET),
        auth=BasicAuth(USERNAME, PASSWORD),
    )


def _deprecations(
    caught: list[warnings.WarningMessage],
) -> list[warnings.WarningMessage]:
    return [w for w in caught if issubclass(w.category, DeprecationWarning)]


def _use(action: Callable[[], object]) -> tuple[object, list[warnings.WarningMessage]]:
    """Run `action`, and give its result and the deprecation warnings that it emitted."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = action()
    return result, _deprecations(caught)


def _assert_one_warning_names(caught, old: str, *new: str) -> None:
    """Exactly one deprecation warning; it names the old name and each successor, and it
    points at the line of this file that used the old name."""
    assert len(caught) == 1, [str(w.message) for w in caught]
    message = str(caught[0].message)
    assert old in message
    for name in new:
        assert name in message
    assert caught[0].filename == __file__


# -- the Graph Store verbs, the lists, and the dataset -----------------------------------------

OPERATIONS = [
    pytest.param(
        "fetch_statements",
        "graph_get",
        lambda db, name: getattr(db, name)(GRAPH),
        id="fetch_statements",
    ),
    pytest.param(
        "import_statements",
        "graph_add",
        lambda db, name: getattr(db, name)(
            STATEMENT, graph_iri=GRAPH, content_type="application/n-triples"
        ),
        id="import_statements",
    ),
    pytest.param(
        "clear_graph",
        "graph_clear",
        lambda db, name: getattr(db, name)(GRAPH),
        id="clear_graph",
    ),
    pytest.param(
        "get_list_of_named_graphs",
        "graphs_get",
        lambda db, name: getattr(db, name)(),
        id="get_list_of_named_graphs",
    ),
    pytest.param(
        "get_list_of_repositories",
        "datasets_get",
        lambda db, name: getattr(db, name)(only_ids=True),
        id="get_list_of_repositories",
    ),
]


@pytest.mark.parametrize("old, new, call", OPERATIONS)
def test_the_new_name_does_what_the_old_name_did_and_does_not_warn(
    fake, client, old, new, call
):
    old_result, _ = _use(lambda: call(client, old))
    old_requests = list(fake.sent)
    fake.sent.clear()

    new_result, caught = _use(lambda: call(client, new))

    assert caught == []
    assert fake.sent == old_requests
    if isinstance(old_result, Graph):
        assert set(new_result) == set(old_result)
    else:
        assert new_result == old_result


def test_the_new_names_answer_as_the_store_does(client):
    assert set(client.graph_get(GRAPH)) == set(
        Graph().parse(data=STATEMENT, format="nt")
    )
    assert client.graph_add(STATEMENT, content_type="application/n-triples") is True
    assert client.graph_clear(GRAPH) is True
    assert [str(graph) for graph in client.graphs_get()] == NAMED_GRAPHS
    assert client.datasets_get(only_ids=True) == [DATASET, OTHER]


@pytest.mark.parametrize("old, new, call", OPERATIONS[:3])
def test_an_old_graph_store_name_answers_an_error_answer_as_its_successor_does(
    fake, client, old, new, call
):
    """The old name calls its successor, so an error answer raises the same error through both."""
    fake.graph_store_answer = _answer(500, "Unknown error")

    with pytest.raises(TripleStoreResponseError) as through_new:
        call(client, new)
    with pytest.warns(DeprecationWarning, match=new):
        with pytest.raises(TripleStoreResponseError) as through_old:
            call(client, old)

    assert type(through_old.value) is type(through_new.value)
    assert str(through_old.value) == str(through_new.value)
    assert through_old.value.status == 500


@pytest.mark.parametrize("old, new, call", OPERATIONS)
def test_each_call_of_an_old_name_warns_once_naming_its_successor(
    client, old, new, call
):
    for _ in range(2):
        _, caught = _use(lambda: call(client, old))

        _assert_one_warning_names(caught, old, new)


def test_the_dataset_is_the_store_attribute_and_does_not_warn(client):
    dataset, caught = _use(lambda: client.dataset)

    assert dataset == DATASET
    assert caught == []


def test_each_read_of_the_old_attribute_warns_once_naming_dataset(client):
    for _ in range(2):
        repository, caught = _use(lambda: client.repository)

        assert repository == DATASET
        _assert_one_warning_names(caught, "repository", "dataset")


def test_setting_the_dataset_checks_it_against_the_store_without_a_warning(client):
    def select():
        client.dataset = OTHER

    _, caught = _use(select)

    assert client.dataset == OTHER
    assert caught == []
    with pytest.raises(InvalidDatasetError):
        client.dataset = "missing"


def test_setting_the_old_attribute_sets_the_dataset_and_warns_once(client):
    def select():
        client.repository = OTHER

    _, caught = _use(select)

    assert client.dataset == OTHER
    _assert_one_warning_names(caught, "repository", "dataset")


# -- the credentials and the token flag ---------------------------------------------------------


def _old_credentials_name():
    """`GraphDBCredentials`, read as a consumer imports it."""
    return importlib.import_module("kapps_triplestore_interface").GraphDBCredentials


@pytest.mark.parametrize(
    "module",
    [
        "kapps_triplestore_interface",
        "kapps_triplestore_interface.utils.graph_db_credentials",
    ],
)
def test_each_use_of_the_credentials_name_warns_once_naming_the_endpoint_and_the_providers(
    module,
):
    for _ in range(2):
        _, caught = _use(
            lambda: getattr(importlib.import_module(module), "GraphDBCredentials")
        )

        _assert_one_warning_names(
            caught,
            "GraphDBCredentials",
            "TripleStoreEndpoint",
            "GDBTokenAuth",
            "BasicAuth",
        )


def test_the_import_of_the_credentials_name_warns_once():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from kapps_triplestore_interface import (  # pylint: disable=import-outside-toplevel
            GraphDBCredentials,
        )

    _assert_one_warning_names(_deprecations(caught), "GraphDBCredentials")
    assert GraphDBCredentials.__name__ == "GraphDBCredentials"


def test_a_star_import_of_the_package_still_brings_the_credentials_name_and_warns_once():
    namespace: dict = {}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        exec(  # pylint: disable=exec-used
            compile("from kapps_triplestore_interface import *", __file__, "exec"),
            namespace,
        )

    caught = _deprecations(caught)
    assert len(caught) == 1, [str(w.message) for w in caught]
    assert "GraphDBCredentials" in str(caught[0].message)
    assert namespace["GraphDBCredentials"].__name__ == "GraphDBCredentials"


def test_the_credentials_build_the_endpoint_and_a_gdb_token_provider(fake):
    with pytest.warns(DeprecationWarning):
        GraphDBCredentials = _old_credentials_name()
    credentials = GraphDBCredentials(BASE_URL, USERNAME, PASSWORD, DATASET)

    client, caught = _use(lambda: GraphDB(credentials=credentials))

    # The use of the old name is the name itself: building the store with it adds no warning.
    assert caught == []
    assert client._endpoint == TripleStoreEndpoint(url=BASE_URL, dataset=DATASET)
    assert isinstance(client._auth_provider, GDBTokenAuth)
    # The provider logged in for a token, and the client sent the token.
    assert [(m, p) for m, p, *_ in fake.sent] == [
        ("POST", "/rest/login"),
        ("GET", "/rest/repositories"),
    ]
    assert fake.sent[1][4] == "GDB token-1"
    assert client.dataset == DATASET


@pytest.mark.parametrize(
    "flag, provider, successor",
    [(True, GDBTokenAuth, "GDBTokenAuth"), (False, BasicAuth, "BasicAuth")],
)
def test_the_token_flag_still_chooses_the_provider_and_warns_once_naming_it(
    fake, flag, provider, successor
):
    with pytest.warns(DeprecationWarning):
        GraphDBCredentials = _old_credentials_name()
    credentials = GraphDBCredentials(BASE_URL, USERNAME, PASSWORD, DATASET)

    client, caught = _use(lambda: GraphDB(credentials=credentials, use_gdb_token=flag))

    _assert_one_warning_names(caught, "use_gdb_token", successor)
    assert isinstance(client._auth_provider, provider)
    if provider is BasicAuth:
        assert [p for _, p, *_ in fake.sent] == ["/rest/repositories"]
        assert fake.sent[0][4].startswith("Basic ")


def test_the_token_flag_given_by_position_warns_once(
    fake,
):  # pylint: disable=unused-argument
    with pytest.warns(DeprecationWarning):
        GraphDBCredentials = _old_credentials_name()
    credentials = GraphDBCredentials(BASE_URL, USERNAME, PASSWORD, DATASET)

    client, caught = _use(lambda: GraphDB(credentials, 60, False))

    _assert_one_warning_names(caught, "use_gdb_token", "BasicAuth")
    assert isinstance(client._auth_provider, BasicAuth)


def test_the_store_from_the_environment_still_builds_and_does_not_warn(
    fake, monkeypatch
):  # pylint: disable=unused-argument
    for name, value in {
        "GRAPHDB_URL": BASE_URL,
        "GRAPHDB_USERNAME": USERNAME,
        "GRAPHDB_PASSWORD": PASSWORD,
        "GRAPHDB_REPOSITORY": DATASET,
    }.items():
        monkeypatch.setenv(name, value)

    client, caught = _use(GraphDB.from_env)

    assert caught == []
    assert client.dataset == DATASET


# -- the error of a missing dataset ------------------------------------------------------------


def test_each_use_of_the_old_error_name_warns_once_naming_its_successor():
    module = importlib.import_module("kapps_triplestore_interface.exceptions")
    for _ in range(2):
        old, caught = _use(lambda: module.InvalidRepositoryError)

        assert old is InvalidDatasetError
        _assert_one_warning_names(
            caught, "InvalidRepositoryError", "InvalidDatasetError"
        )


def test_the_old_error_name_still_catches_a_missing_dataset(client):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from kapps_triplestore_interface.exceptions import (  # pylint: disable=import-outside-toplevel
            InvalidRepositoryError,
        )
    assert len(_deprecations(caught)) == 1

    with pytest.raises(InvalidRepositoryError):
        client.dataset = "missing"


# -- the contract ----------------------------------------------------------------------------

OLD_NAMES = [
    "fetch_statements",
    "import_statements",
    "clear_graph",
    "get_list_of_named_graphs",
    "get_list_of_repositories",
    "repository",
]


@pytest.mark.parametrize("name", OLD_NAMES)
def test_the_contract_declares_no_old_name(name):
    assert name not in vars(TripleStore)


@pytest.mark.parametrize("name", OLD_NAMES)
def test_the_adapter_marks_each_old_name_deprecated_for_the_documentation(name):
    member = vars(GraphDB)[name]
    marked = getattr(member, "fget", member)
    assert "deprecated" in marked.__deprecated__


@pytest.mark.parametrize(
    "old, new",
    [
        ("fetch_statements", "graph_get"),
        ("import_statements", "graph_add"),
        ("clear_graph", "graph_clear"),
        ("get_list_of_named_graphs", "graphs_get"),
        ("get_list_of_repositories", "datasets_get"),
    ],
)
def test_each_old_name_takes_the_parameters_of_its_successor(old, new):
    def parameters(function):
        return [
            (parameter.name, parameter.kind, parameter.default)
            for parameter in inspect.signature(function).parameters.values()
        ]

    assert parameters(getattr(GraphDB, old)) == parameters(getattr(GraphDB, new))
