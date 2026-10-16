"""A store's endpoint and its auth provider are read from the environment.

These tests run without a triple store. Each test sets the variables that it reads, and unsets
every other one, so that a variable of the shell or of CI cannot reach it.

`TRIPLESTORE_*` is read first. `GRAPHDB_*` is the deprecated fallback: a variable read from it
emits one `DeprecationWarning`, which names the variable that replaces it.
"""

from __future__ import annotations

import dataclasses
import warnings

import pytest

from kapps_triplestore_interface import BasicAuth, GDBTokenAuth, TripleStoreEndpoint

# Each variable and its deprecated fallback.
VARIABLES = {
    "TRIPLESTORE_URL": "GRAPHDB_URL",
    "TRIPLESTORE_DATASET": "GRAPHDB_REPOSITORY",
    "TRIPLESTORE_USERNAME": "GRAPHDB_USERNAME",
    "TRIPLESTORE_PASSWORD": "GRAPHDB_PASSWORD",
}
PROVIDERS = pytest.mark.parametrize("provider", [BasicAuth, GDBTokenAuth])


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name, fallback in VARIABLES.items():
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(fallback, raising=False)


def _set(monkeypatch, **variables):
    for name, value in variables.items():
        monkeypatch.setenv(name, value)


# -- the endpoint ------------------------------------------------------------------------------


def test_an_endpoint_is_the_url_and_the_dataset_and_holds_no_secret():
    endpoint = TripleStoreEndpoint(url="http://localhost:7200", dataset="repo")

    assert [field.name for field in dataclasses.fields(endpoint)] == ["url", "dataset"]
    assert (endpoint.url, endpoint.dataset) == ("http://localhost:7200", "repo")
    with pytest.raises(dataclasses.FrozenInstanceError):
        endpoint.url = "http://elsewhere:7200"


def test_the_endpoint_reads_the_triplestore_variables_without_a_warning(monkeypatch):
    _set(
        monkeypatch, TRIPLESTORE_URL="http://localhost:7200", TRIPLESTORE_DATASET="repo"
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        endpoint = TripleStoreEndpoint.from_env()

    assert endpoint == TripleStoreEndpoint(url="http://localhost:7200", dataset="repo")


def test_a_dataset_argument_takes_the_place_of_the_variable(monkeypatch):
    _set(monkeypatch, TRIPLESTORE_URL="http://localhost:7200", GRAPHDB_REPOSITORY="old")

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        endpoint = TripleStoreEndpoint.from_env(dataset="chosen")

    assert endpoint.dataset == "chosen"


def test_the_endpoint_falls_back_to_the_graphdb_variables_and_warns_for_each(
    monkeypatch,
):
    _set(monkeypatch, GRAPHDB_URL="http://localhost:7200", GRAPHDB_REPOSITORY="repo")

    with pytest.warns(DeprecationWarning) as warned:
        endpoint = TripleStoreEndpoint.from_env()

    assert endpoint == TripleStoreEndpoint(url="http://localhost:7200", dataset="repo")
    messages = [str(warning.message) for warning in warned]
    assert len(messages) == 2
    assert "GRAPHDB_URL" in messages[0] and "TRIPLESTORE_URL" in messages[0]
    assert "GRAPHDB_REPOSITORY" in messages[1] and "TRIPLESTORE_DATASET" in messages[1]


def test_a_triplestore_variable_wins_over_its_fallback_without_a_warning(monkeypatch):
    _set(
        monkeypatch,
        TRIPLESTORE_URL="http://new:7200",
        GRAPHDB_URL="http://old:7200",
        TRIPLESTORE_DATASET="new",
        GRAPHDB_REPOSITORY="old",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        endpoint = TripleStoreEndpoint.from_env()

    assert endpoint == TripleStoreEndpoint(url="http://new:7200", dataset="new")


@pytest.mark.parametrize(
    ("present", "missing"),
    [
        ({"TRIPLESTORE_DATASET": "repo"}, "TRIPLESTORE_URL"),
        ({"TRIPLESTORE_URL": "http://localhost:7200"}, "TRIPLESTORE_DATASET"),
    ],
)
def test_a_missing_variable_is_named(monkeypatch, present, missing):
    _set(monkeypatch, **present)

    with pytest.raises(ValueError, match=missing):
        TripleStoreEndpoint.from_env()


# -- the auth providers ------------------------------------------------------------------------


@PROVIDERS
def test_a_provider_reads_the_triplestore_variables_without_a_warning(
    monkeypatch, provider
):
    _set(monkeypatch, TRIPLESTORE_USERNAME="user", TRIPLESTORE_PASSWORD="secret")

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        auth = provider.from_env()

    assert isinstance(auth, provider)
    assert "user" in repr(auth)


@PROVIDERS
def test_a_provider_falls_back_to_the_graphdb_variables_and_warns_for_each(
    monkeypatch, provider
):
    _set(monkeypatch, GRAPHDB_USERNAME="user", GRAPHDB_PASSWORD="secret")

    with pytest.warns(DeprecationWarning) as warned:
        provider.from_env()

    messages = [str(warning.message) for warning in warned]
    assert len(messages) == 2
    assert "GRAPHDB_USERNAME" in messages[0] and "TRIPLESTORE_USERNAME" in messages[0]
    assert "GRAPHDB_PASSWORD" in messages[1] and "TRIPLESTORE_PASSWORD" in messages[1]


@PROVIDERS
def test_a_provider_without_a_password_names_the_variable(monkeypatch, provider):
    _set(monkeypatch, TRIPLESTORE_USERNAME="user")

    with pytest.raises(ValueError, match="TRIPLESTORE_PASSWORD"):
        provider.from_env()


@PROVIDERS
def test_a_provider_never_shows_its_password(provider):
    auth = provider("user", "secret")

    assert "secret" not in repr(auth)
    assert "secret" not in str(auth)
