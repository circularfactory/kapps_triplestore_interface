"""`ruleset_get()`: which reasoning ruleset a dataset runs, as the store names it.

These tests run without a triple store. The stub in `_stub_store.py` answers as GraphDB does;
each test sets the answer that it needs.

The GraphDB adapter reads the repository's configuration, `GET /rest/repositories/<id>`, the
request that `shapes_set` sends before it sets shapes, and returns the value of its `ruleset`
parameter, or `None` when the configuration has no ruleset value. An error answer raises what
that configuration read raises, unchanged. The method reports; it does not judge whether a
ruleset is supported.

The reading of the configuration is one internal function, `_ruleset_of`, tested here for each
answer that the configuration can give. A store that does not say which ruleset it runs, such
as an adapter that inherits the contract's default, returns `None`.
"""

# pytest passes the fixtures by name, and an exact type is what these tests check.
# pylint: disable=redefined-outer-name,unused-argument,unidiomatic-typecheck

from __future__ import annotations

import json

import pytest

from kapps_triplestore_interface import (
    BasicAuth,
    GraphDB,
    TripleStore,
    TripleStoreAccessError,
    TripleStoreEndpoint,
    TripleStoreResponseError,
)
from kapps_triplestore_interface.graph_db import _ruleset_of
from tests._stub_store import (  # pylint: disable=unused-import
    BASE_URL,
    DATASET,
    PASSWORD,
    USERNAME,
    answer,
    store,
)

CONFIGURATION = f"/rest/repositories/{DATASET}"
BODY = "the store's answer, unchanged"


@pytest.fixture
def adapter(store) -> GraphDB:
    """The adapter, built after the stub, so that every request reaches the stub."""
    return GraphDB(
        endpoint=TripleStoreEndpoint(url=BASE_URL, dataset=DATASET),
        auth=BasicAuth(USERNAME, PASSWORD),
    )


def _configuration(**params: object) -> dict:
    """A repository configuration as GraphDB's REST API answers it, with `params`."""
    return {
        "id": DATASET,
        "title": "",
        "type": "graphdb",
        "sesameType": "graphdb:SailRepository",
        "location": "",
        "params": {
            name: {"name": name, "label": name, "value": value}
            for name, value in params.items()
        },
    }


def _configuration_answer(**params: object):
    return answer(200, json.dumps(_configuration(**params)), "application/json")


# -- the adapter -------------------------------------------------------------------------------


@pytest.mark.parametrize("ruleset", ["rdfsplus-optimized", "owl2-rl", "owl-max"])
def test_ruleset_get_returns_the_ruleset_of_the_configuration_in_one_read(
    store, adapter, ruleset
):
    store.answers[CONFIGURATION] = _configuration_answer(
        ruleset=ruleset, isShacl="true"
    )

    assert adapter.ruleset_get() == ruleset
    assert [(method, path) for method, path, _ in store.sent] == [
        ("GET", CONFIGURATION)
    ]


def test_ruleset_get_of_a_configuration_without_a_ruleset_is_none(store, adapter):
    store.answers[CONFIGURATION] = _configuration_answer(isShacl="true")

    assert adapter.ruleset_get() is None


def test_ruleset_get_of_a_missing_dataset_raises_the_response_error_with_404(
    store, adapter
):
    store.answers[CONFIGURATION] = answer(404, BODY)

    with pytest.raises(TripleStoreResponseError) as failed:
        adapter.ruleset_get()

    assert type(failed.value) is TripleStoreResponseError
    assert failed.value.status == 404
    assert str(failed.value).endswith(f"(404) - {BODY}")
    assert f"'{DATASET}'" in str(failed.value)


def test_ruleset_get_raises_the_type_of_the_status_of_an_error_answer(store, adapter):
    store.answers[CONFIGURATION] = answer(403, BODY)

    with pytest.raises(TripleStoreAccessError) as failed:
        adapter.ruleset_get()

    assert type(failed.value) is TripleStoreAccessError
    assert failed.value.status == 403


# -- a store that does not say -----------------------------------------------------------------


class _StoreWithoutRuleset(TripleStore):
    """An adapter that inherits the contract and does not say which ruleset it runs."""


def test_an_adapter_that_does_not_say_returns_none():
    assert _StoreWithoutRuleset().ruleset_get() is None


# -- the reading of the configuration, for each answer -----------------------------------------


@pytest.mark.parametrize(
    ("configuration", "expected"),
    [
        (_configuration(ruleset="rdfsplus-optimized"), "rdfsplus-optimized"),
        (_configuration(ruleset="owl2-rl", isShacl="true"), "owl2-rl"),
        (_configuration(ruleset=" owl-max \n"), "owl-max"),
        (_configuration(isShacl="true"), None),
        (_configuration(ruleset=""), None),
        (_configuration(ruleset="   "), None),
        (_configuration(ruleset=None), None),
        (_configuration(ruleset=7), None),
        ({**_configuration(), "params": {"ruleset": "owl2-rl"}}, None),
        ({"id": DATASET}, None),
        ({"params": None}, None),
        ([], None),
        (None, None),
    ],
    ids=[
        "rdfsplus-optimized",
        "owl2-rl-beside-other-params",
        "surrounding-white-space",
        "no-ruleset",
        "empty",
        "white-space-only",
        "null",
        "not-a-string",
        "param-not-an-object",
        "no-params",
        "params-not-an-object",
        "not-an-object",
        "nothing",
    ],
)
def test_the_reading_takes_the_ruleset_value_of_the_configuration(
    configuration, expected
):
    assert _ruleset_of(configuration) == expected
