"""Each error type of the interface names one action, and an error answer carries the store's status.

These tests run without a triple store. `requests.Session.request` is replaced by a stub that
answers each request as the test says, so every request goes through the client's own request
path, as it does against a store.

The five actions are those of the error map: Repair, Retry, Refresh, Refused, and Fix the call.
"""

from __future__ import annotations

import importlib
import json

import pytest
import requests

from kapps_triplestore_interface import GraphDB, GraphDBCredentials, exceptions
from kapps_triplestore_interface.exceptions import (
    AuthenticationError,
    InvalidInputError,
    InvalidIRIError,
    InvalidQueryError,
    InvalidDatasetError,
    PreconditionFailedError,
    ShaclValidationError,
    TripleStoreAccessError,
    TripleStoreInterfaceError,
    TripleStoreNotSupportedError,
    TripleStoreResponseError,
    TripleStoreUnavailableError,
)

REPOSITORY = "repo"
BASE_URL = "http://store.example.org:7200"
GRAPH = "http://example.org/error-types#graph"
S, P, O = (f"http://example.org/error-types#{name}" for name in ("s", "p", "o"))


# -- the types ---------------------------------------------------------------------------------


def _old_name():
    """`GraphDbException`, read as a consumer imports it."""
    module = importlib.import_module("kapps_triplestore_interface.exceptions")
    return module.GraphDbException


def test_the_old_name_is_the_response_error_and_its_import_warns_with_the_successor():
    with pytest.warns(DeprecationWarning, match="TripleStoreResponseError") as warned:
        from kapps_triplestore_interface.exceptions import (  # pylint: disable=import-outside-toplevel
            GraphDbException,
        )

    assert GraphDbException is TripleStoreResponseError
    assert len(warned) == 1
    assert "GraphDbException" in str(warned[0].message)


def test_each_use_of_the_old_name_warns_once():
    for _ in range(2):
        with pytest.warns(
            DeprecationWarning, match="TripleStoreResponseError"
        ) as warned:
            _old_name()
        assert len(warned) == 1


def test_the_old_name_constructs_without_a_status_as_consumers_call_it():
    with pytest.warns(DeprecationWarning):
        GraphDbException = _old_name()

    error = GraphDbException("Error while querying GraphDB (500) - out of memory")

    assert isinstance(error, TripleStoreResponseError)
    assert error.status is None
    assert error.message == "Error while querying GraphDB (500) - out of memory"
    assert str(error) == "Error while querying GraphDB (500) - out of memory"


def test_a_consumer_subclass_of_the_old_name_is_a_response_error():
    with pytest.warns(DeprecationWarning):
        GraphDbException = _old_name()

    class StoreRefusal(GraphDbException):
        pass

    with pytest.raises(GraphDbException):
        raise StoreRefusal("refused")
    assert issubclass(StoreRefusal, TripleStoreResponseError)


def test_an_unknown_name_of_the_module_is_still_an_attribute_error():
    name = "NoSuchError"

    with pytest.raises(AttributeError):
        getattr(exceptions, name)


@pytest.mark.parametrize(
    ("error_type", "base"),
    [
        (TripleStoreResponseError, TripleStoreInterfaceError),
        (AuthenticationError, TripleStoreResponseError),
        (TripleStoreAccessError, TripleStoreResponseError),
        (ShaclValidationError, TripleStoreResponseError),
        (TripleStoreUnavailableError, TripleStoreInterfaceError),
        (PreconditionFailedError, TripleStoreInterfaceError),
        (TripleStoreNotSupportedError, TripleStoreInterfaceError),
        (InvalidDatasetError, TripleStoreInterfaceError),
        (InvalidQueryError, TripleStoreInterfaceError),
        (InvalidInputError, TripleStoreInterfaceError),
        (InvalidIRIError, TripleStoreInterfaceError),
    ],
    ids=lambda value: value.__name__,
)
def test_the_type_tree_is_the_error_maps(error_type, base):
    assert error_type.__bases__ == (base,)


@pytest.mark.parametrize(
    "error_type",
    [
        TripleStoreUnavailableError,
        PreconditionFailedError,
        TripleStoreNotSupportedError,
    ],
    ids=lambda value: value.__name__,
)
def test_a_failure_that_is_not_an_error_answer_is_no_response_error(error_type):
    assert not issubclass(error_type, TripleStoreResponseError)


@pytest.mark.parametrize(
    ("error_type", "action"),
    [
        (TripleStoreResponseError, "Repair"),
        (AuthenticationError, "Repair"),
        (TripleStoreAccessError, "Repair"),
        (ShaclValidationError, "Refused"),
        (TripleStoreUnavailableError, "Retry"),
        (PreconditionFailedError, "Refresh"),
        (TripleStoreNotSupportedError, "Fix the call"),
        (InvalidDatasetError, "Repair"),
        (InvalidQueryError, "Fix the call"),
        (InvalidInputError, "Fix the call"),
        (InvalidIRIError, "Fix the call"),
    ],
    ids=lambda value: getattr(value, "__name__", value),
)
def test_each_type_names_its_action_in_its_docstring(error_type, action):
    assert f"Action: {action}." in error_type.__doc__


def test_the_unavailable_error_states_why_a_callers_retry_is_safe():
    doc = " ".join(TripleStoreUnavailableError.__doc__.split())

    assert "never sends a write again" in doc
    assert (
        "A checked write refuses a second application with `PreconditionFailedError`"
        in doc
    )
    assert "An insert or an import repeats as a no-op" in doc
    assert "blank nodes" in doc
    assert "raw update that the caller writes itself" in doc


def test_the_not_supported_error_is_a_plain_interface_error():
    error = TripleStoreNotSupportedError("The store has no prefix registry.")

    assert isinstance(error, TripleStoreInterfaceError)
    assert str(error) == "The store has no prefix registry."


@pytest.mark.parametrize(
    "error_type",
    [AuthenticationError, TripleStoreAccessError],
    ids=lambda value: value.__name__,
)
def test_the_subtypes_construct_with_a_message_alone_and_with_a_status(error_type):
    assert error_type("refused").status is None
    assert error_type("refused", status=418).status == 418


def test_a_shacl_refusal_constructs_as_before_and_carries_a_status():
    report = "<report>"

    assert ShaclValidationError("refused", report=report).status is None
    refused = ShaclValidationError("refused", report=report, status=500)
    assert (refused.report, refused.status, str(refused)) == (report, 500, "refused")


@pytest.mark.parametrize(
    "name",
    [
        "TripleStoreResponseError",
        "TripleStoreUnavailableError",
        "AuthenticationError",
        "TripleStoreAccessError",
        "TripleStoreNotSupportedError",
    ],
)
def test_the_package_exports_the_new_types(name):
    package = importlib.import_module("kapps_triplestore_interface")

    assert name in package.__all__
    assert getattr(package, name) is getattr(exceptions, name)


# -- error answers -----------------------------------------------------------------------------


def _answer(status: int, body: str = "", media_type: str = "text/plain;charset=UTF-8"):
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = media_type
    response._content = body.encode("utf-8")
    response.encoding = "utf-8"
    return response


class StubStore:
    """Answers the login and the repository list as GraphDB does, unless a test sets their
    answer, and every other request with `answer`. Records each request that the client sends.
    """

    def __init__(self):
        self.answer = _answer(200)
        self.login_answer = None
        self.list_answer = None
        self.sent: list[tuple[str, str]] = []

    def __call__(self, method, url, **kwargs):
        path = url.removeprefix(BASE_URL)
        self.sent.append((method, path))
        if path == "/rest/login":
            if self.login_answer is not None:
                return self.login_answer
            answer = _answer(200, "", "application/json")
            answer.headers["Authorization"] = "GDB token"
            return answer
        if path == "/rest/repositories":
            if self.list_answer is not None:
                return self.list_answer
            return _answer(200, json.dumps([{"id": REPOSITORY}]), "application/json")
        return self.answer


@pytest.fixture
def store(monkeypatch) -> StubStore:
    stub = StubStore()
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda session, method, url, **kwargs: stub(method, url, **kwargs),
    )
    return stub


def _client(use_gdb_token: bool = True) -> GraphDB:
    return GraphDB(
        GraphDBCredentials(
            base_url=BASE_URL,
            username="user",
            password="password",
            repository=REPOSITORY,
        ),
        use_gdb_token=use_gdb_token,
    )


@pytest.fixture
def client(store) -> GraphDB:
    return _client()


# Each operation that reports the store's error answer, and its message for the answer.
OPERATIONS = pytest.mark.parametrize(
    ("operation", "message"),
    [
        pytest.param(
            lambda db: db.query("ASK { ?s ?p ?o }"),
            "Error while querying GraphDB ({status}) - {body}",
            id="read",
        ),
        pytest.param(
            lambda db: db.query(f"INSERT DATA {{ <{S}> <{P}> <{O}> . }}", update=True),
            "Error while querying GraphDB ({status}) - {body}",
            id="update",
        ),
        pytest.param(
            lambda db: db.graph_get(GRAPH),
            f"Failed to fetch graph <{GRAPH}> in repository '{REPOSITORY}'"
            " ({status}) - {body}",
            id="fetch a graph",
        ),
        pytest.param(
            lambda db: db.graph_get(),
            f"Failed to fetch the default graph in repository '{REPOSITORY}'"
            " ({status}) - {body}",
            id="fetch the default graph",
        ),
        pytest.param(
            lambda db: db.graph_clear(GRAPH),
            f"Failed to clear graph <{GRAPH}> in repository '{REPOSITORY}'"
            " ({status}) - {body}",
            id="clear a graph",
        ),
    ],
)

# Each error status, and the type that it raises.
STATUSES = pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, TripleStoreResponseError),
        (401, AuthenticationError),
        (403, TripleStoreAccessError),
        (404, TripleStoreResponseError),
        (500, TripleStoreResponseError),
        (503, TripleStoreResponseError),
    ],
    ids=lambda value: getattr(value, "__name__", str(value)),
)

BODY = "the store's answer, unchanged: <b>Forbidden</b> (line 1, column 2)"


@OPERATIONS
@STATUSES
def test_an_error_answer_raises_its_type_with_the_status_and_the_answer(
    store, client, operation, message, status, error_type
):
    store.answer = _answer(status, BODY)

    with pytest.raises(TripleStoreResponseError) as failed:
        operation(client)

    assert type(failed.value) is error_type
    assert failed.value.status == status
    assert str(failed.value) == message.format(status=status, body=BODY)


@OPERATIONS
@pytest.mark.parametrize("status", [401, 403, 500])
def test_the_old_name_still_catches_each_error_answer(
    store, client, operation, message, status
):
    store.answer = _answer(status, BODY)
    with pytest.warns(DeprecationWarning):
        GraphDbException = _old_name()

    with pytest.raises(GraphDbException):
        operation(client)


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda db: db.query("ASK { ?s ?p ?o }"), id="read"),
        pytest.param(lambda db: db.graph_clear(GRAPH), id="clear a graph"),
    ],
)
def test_a_validation_report_still_raises_the_refusal_with_the_status(
    store, client, operation
):
    store.answer = _answer(
        500, "<report>", "application/shacl-validation-report+n-quads;charset=UTF-8"
    )

    with pytest.raises(ShaclValidationError) as refused:
        operation(client)

    assert (refused.value.status, refused.value.report) == (500, "<report>")


@STATUSES
def test_listing_the_repositories_raises_on_an_error_answer(
    store, client, status, error_type
):
    store.list_answer = _answer(status, BODY)

    with pytest.raises(TripleStoreResponseError) as failed:
        client.datasets_get()

    assert type(failed.value) is error_type
    assert failed.value.status == status
    assert str(failed.value) == f"Failed to list repositories ({status}) - {BODY}"


def test_a_failed_repository_list_on_construction_raises_the_store_error(store):
    """With Basic authentication, the list is the first request that the store can refuse."""
    store.list_answer = _answer(401, BODY)

    with pytest.raises(AuthenticationError) as failed:
        _client(use_gdb_token=False)

    assert failed.value.status == 401


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, AuthenticationError),
        (403, TripleStoreAccessError),
        (500, TripleStoreResponseError),
    ],
    ids=["401", "403", "500"],
)
def test_a_refused_login_raises_its_type_with_the_status_and_the_answer(
    store, status, error_type
):
    store.login_answer = _answer(status, BODY)

    with pytest.raises(TripleStoreResponseError) as failed:
        _client()

    assert type(failed.value) is error_type
    assert failed.value.status == status
    assert str(failed.value) == f"Failed to obtain a GDB token ({status}) - {BODY}"


@pytest.mark.parametrize(
    "graph",
    [pytest.param(GRAPH, id="named graph"), pytest.param(None, id="default graph")],
)
def test_fetching_a_graph_returns_the_graph_on_200_and_never_none(store, client, graph):
    store.answer = _answer(200, f"<{S}> <{P}> <{O}> .\n", "text/plain")

    fetched = client.graph_get(graph)

    assert fetched is not None and len(fetched) == 1


# -- the existence checks ----------------------------------------------------------------------

EXISTENCE_CHECKS = pytest.mark.parametrize(
    "check",
    [
        pytest.param(lambda db: db.triple_exists((S, P, O)), id="triple_exists"),
        pytest.param(
            lambda db: db.any_triple_exists([(S, P, O)]), id="any_triple_exists"
        ),
        pytest.param(
            lambda db: db.all_triple_exists([(S, P, O)]), id="all_triple_exists"
        ),
        pytest.param(lambda db: db.iri_exists(S, as_sub=True), id="iri_exists"),
    ],
)


@EXISTENCE_CHECKS
def test_an_existence_check_against_a_failing_store_raises_the_store_error(
    store, client, check
):
    store.answer = _answer(500, BODY)

    with pytest.raises(TripleStoreResponseError) as failed:
        check(client)

    assert not isinstance(failed.value, InvalidInputError)
    assert failed.value.status == 500


@EXISTENCE_CHECKS
@pytest.mark.parametrize("found", [True, False])
def test_an_existence_check_answers_what_the_store_answers(store, client, check, found):
    store.answer = _answer(
        200,
        json.dumps({"head": {}, "boolean": found}),
        "application/sparql-results+json",
    )

    assert check(client) is found
