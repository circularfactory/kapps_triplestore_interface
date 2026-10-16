"""`connect()` builds the adapter, makes the provider log in now, sends one probe, and returns
the store, or raises the typed error of the failure.

These tests run without a triple store. The stub in `_stub_store.py` answers as GraphDB does;
each test sets the answer that it needs. The probe is `ASK {}` on the dataset.
"""

from __future__ import annotations

import importlib
import inspect
import typing

import pytest

from kapps_triplestore_interface import (
    AuthenticationError,
    BasicAuth,
    GDBTokenAuth,
    GraphDB,
    TripleStoreAccessError,
    TripleStoreEndpoint,
    TripleStoreResponseError,
    TripleStoreUnavailableError,
    connect,
)
from kapps_triplestore_interface.exceptions import InvalidDatasetError
from tests._stub_store import (  # pylint: disable=unused-import
    BASE_URL,
    DATASET,
    PASSWORD,
    USERNAME,
    answer,
    store,
)

ENDPOINT = TripleStoreEndpoint(url=BASE_URL, dataset=DATASET)
PROBE = f"/repositories/{DATASET}"
LOGIN = "/rest/login"
BODY = "the store's answer, unchanged"


def _token() -> GDBTokenAuth:
    return GDBTokenAuth(USERNAME, PASSWORD)


def _basic() -> BasicAuth:
    return BasicAuth(USERNAME, PASSWORD)


# -- the probe's outcomes ----------------------------------------------------------------------


def test_a_reachable_store_is_returned_after_one_login_and_one_probe(store):
    connected = connect(ENDPOINT, _token())

    assert isinstance(connected, GraphDB)
    assert connected.dataset == DATASET
    assert store.sent == [
        ("POST", LOGIN, None),
        ("POST", PROBE, "GDB token-1"),
    ]
    assert store.bodies[1] == "ASK {}"


def test_with_basic_authentication_the_probe_is_the_only_request(store):
    connect(ENDPOINT, _basic())

    assert store.paths() == [PROBE]


def test_the_store_works_after_connect(store):
    connected = connect(ENDPOINT, _token())

    assert connected.query("ASK { ?s ?p ?o }")["boolean"] is True
    assert store.paths() == [LOGIN, PROBE, PROBE]


def test_an_unreachable_store_raises_unavailable(store):
    store.unreachable = True

    with pytest.raises(TripleStoreUnavailableError):
        connect(ENDPOINT, _token())


def test_a_refused_login_raises_authentication_error(store):
    store.answers[LOGIN] = answer(401, BODY)

    with pytest.raises(AuthenticationError) as refused:
        connect(ENDPOINT, _token())

    assert refused.value.status == 401
    assert store.paths() == [LOGIN]


def test_a_401_on_the_probe_raises_authentication_error(store):
    store.answers[PROBE] = answer(401, BODY)

    with pytest.raises(AuthenticationError) as refused:
        connect(ENDPOINT, _basic())

    assert refused.value.status == 401


@pytest.mark.parametrize("refused_path", [LOGIN, PROBE])
def test_a_403_raises_access_error(store, refused_path):
    store.answers[refused_path] = answer(403, BODY)

    with pytest.raises(TripleStoreAccessError) as refused:
        connect(ENDPOINT, _token())

    assert refused.value.status == 403
    assert BODY in str(refused.value)


def test_a_dataset_that_does_not_exist_raises_the_dataset_error(store):
    store.answers[PROBE] = answer(404, f"Unknown repository: {DATASET}")

    with pytest.raises(InvalidDatasetError) as missing:
        connect(ENDPOINT, _token())

    message = str(missing.value)
    assert f"'{DATASET}'" in message
    assert BASE_URL in message
    assert f"(404) - Unknown repository: {DATASET}" in message


def test_any_other_error_answer_of_the_probe_raises_its_type_with_the_status(store):
    store.answers[PROBE] = answer(500, BODY)

    with pytest.raises(TripleStoreResponseError) as failed:
        connect(ENDPOINT, _token())

    assert type(failed.value) is TripleStoreResponseError
    assert failed.value.status == 500


# -- the public names --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["connect", "TripleStore", "TripleStoreEndpoint", "BasicAuth", "GDBTokenAuth"],
)
def test_the_package_exports_the_public_names_of_connect(name):
    package = importlib.import_module("kapps_triplestore_interface")

    assert name in package.__all__
    assert getattr(package, name) is not None


def test_the_type_of_the_auth_providers_is_not_public():
    """The two providers are the public face of authentication. The type that both satisfy
    stays private for now, because a later auth plan can still shape a public auth type; a
    caller that needs a type names the providers.
    """
    package = importlib.import_module("kapps_triplestore_interface")
    auth = importlib.import_module("kapps_triplestore_interface.auth")
    public_classes = {
        name
        for name, value in vars(auth).items()
        if inspect.isclass(value)
        and value.__module__ == auth.__name__
        and not name.startswith("_")
    }

    assert public_classes == {"BasicAuth", "GDBTokenAuth"}
    assert "TripleStoreAuth" not in package.__all__
    assert not hasattr(package, "TripleStoreAuth")


@pytest.mark.parametrize(
    "function, expected",
    [
        (connect, {BasicAuth, GDBTokenAuth}),
        (GraphDB.__init__, {BasicAuth, GDBTokenAuth, type(None)}),
    ],
    ids=["connect", "GraphDB"],
)
def test_a_public_signature_types_auth_by_the_two_providers(function, expected):
    """No private name appears in a public signature, nor in the rendered reference."""
    assert set(typing.get_args(typing.get_type_hints(function)["auth"])) == expected
