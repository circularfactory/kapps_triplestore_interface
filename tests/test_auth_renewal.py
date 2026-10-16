"""An auth provider logs in on first use, and again before its token expires or once after a 401.

These tests run without a triple store. The stub in `_stub_store.py` answers as GraphDB does:
each login issues a new token, and a request with a token that the store no longer accepts gets
401.

Building the adapter sends no request: the provider logs in at the first request that needs it.
"""

from __future__ import annotations

import pytest

from kapps_triplestore_interface import (
    AuthenticationError,
    BasicAuth,
    GDBTokenAuth,
    GraphDB,
    GraphDBCredentials,
    TripleStoreEndpoint,
)
from kapps_triplestore_interface import auth as auth_module
from tests._stub_store import (  # pylint: disable=unused-import
    BASE_URL,
    DATASET,
    PASSWORD,
    USERNAME,
    answer,
    store,
)

ENDPOINT = TripleStoreEndpoint(url=BASE_URL, dataset=DATASET)
QUERY = f"/repositories/{DATASET}"
UPDATE = f"/repositories/{DATASET}/statements"
LOGIN = "/rest/login"
DAY = 24 * 60 * 60


def _adapter(provider=GDBTokenAuth) -> GraphDB:
    return GraphDB(endpoint=ENDPOINT, auth=provider(USERNAME, PASSWORD))


# -- building sends nothing --------------------------------------------------------------------


@pytest.mark.parametrize("provider", [BasicAuth, GDBTokenAuth])
def test_building_the_adapter_sends_no_request(store, provider):
    adapter = _adapter(provider)

    assert store.sent == []
    assert adapter.dataset == DATASET


def test_the_adapter_takes_either_credentials_or_an_endpoint_and_a_provider(store):
    credentials = GraphDBCredentials(BASE_URL, USERNAME, PASSWORD, DATASET)

    with pytest.raises(TypeError):
        GraphDB(credentials, endpoint=ENDPOINT, auth=BasicAuth(USERNAME, PASSWORD))
    with pytest.raises(TypeError):
        GraphDB(endpoint=ENDPOINT)
    with pytest.raises(TypeError):
        GraphDB()
    assert store.sent == []


def test_a_client_built_from_credentials_still_logs_in_and_lists_at_construction(store):
    GraphDB(GraphDBCredentials(BASE_URL, USERNAME, PASSWORD, DATASET))

    assert store.paths() == [LOGIN, "/rest/repositories"]


# -- the GDB token -----------------------------------------------------------------------------


def test_the_provider_logs_in_on_first_use(store):
    adapter = _adapter()

    adapter.query("ASK {}")

    assert store.sent == [
        ("POST", LOGIN, None),
        ("POST", QUERY, "GDB token-1"),
    ]


def test_a_token_that_expires_during_a_run_is_renewed_and_the_request_succeeds(store):
    adapter = _adapter()
    adapter.query("ASK {}")
    store.expire("GDB token-1")

    assert adapter.query("ASK {}") == {"head": {}, "boolean": True}

    assert store.sent[2:] == [
        ("POST", QUERY, "GDB token-1"),
        ("POST", LOGIN, None),
        ("POST", QUERY, "GDB token-2"),
    ]


def test_a_second_401_after_the_renewal_raises_and_is_not_retried_again(store):
    adapter = _adapter()
    store.answers[QUERY] = answer(401, "Unauthorized")

    with pytest.raises(AuthenticationError) as refused:
        adapter.query("ASK {}")

    assert refused.value.status == 401
    assert store.sent == [
        ("POST", LOGIN, None),
        ("POST", QUERY, "GDB token-1"),
        ("POST", LOGIN, None),
        ("POST", QUERY, "GDB token-2"),
    ]


def test_a_write_that_the_store_refused_with_401_is_sent_once_more(store):
    """A 401 means that the store did not apply the write, so sending it again is safe."""
    adapter = _adapter()
    adapter.query("ASK {}")
    store.expire("GDB token-1")

    assert adapter.query("INSERT DATA { <urn:s> <urn:p> <urn:o> }", update=True) is True

    assert store.sent[2:] == [
        ("POST", UPDATE, "GDB token-1"),
        ("POST", LOGIN, None),
        ("POST", UPDATE, "GDB token-2"),
    ]


def test_the_provider_logs_in_again_before_its_token_expires(store, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(auth_module, "_now", lambda: now[0])
    adapter = _adapter()
    adapter.query("ASK {}")

    now[0] += 28 * DAY
    adapter.query("ASK {}")
    now[0] += 1 * DAY
    adapter.query("ASK {}")

    assert store.sent == [
        ("POST", LOGIN, None),
        ("POST", QUERY, "GDB token-1"),
        ("POST", QUERY, "GDB token-1"),
        ("POST", LOGIN, None),
        ("POST", QUERY, "GDB token-2"),
    ]


def test_a_refused_new_login_raises_the_type_of_its_status(store):
    adapter = _adapter()
    adapter.query("ASK {}")
    store.expire("GDB token-1")
    store.answers[LOGIN] = answer(401, "Bad credentials")

    with pytest.raises(
        AuthenticationError, match=r"Failed to obtain a GDB token \(401\)"
    ):
        adapter.query("ASK {}")


def test_a_client_built_from_credentials_renews_its_token_too(store):
    adapter = GraphDB(GraphDBCredentials(BASE_URL, USERNAME, PASSWORD, DATASET))
    store.expire("GDB token-1")

    adapter.query("ASK {}")

    assert store.sent[2:] == [
        ("POST", QUERY, "GDB token-1"),
        ("POST", LOGIN, None),
        ("POST", QUERY, "GDB token-2"),
    ]


# -- basic authentication ----------------------------------------------------------------------


def test_basic_authentication_sends_its_header_and_never_logs_in(store):
    adapter = _adapter(BasicAuth)

    adapter.query("ASK {}")

    [(method, path, authorization)] = store.sent
    assert (method, path) == ("POST", QUERY)
    assert authorization.startswith("Basic ")


def test_basic_authentication_raises_a_401_at_once(store):
    """Basic authentication has nothing to renew, so the same request would get 401 again."""
    adapter = _adapter(BasicAuth)
    store.answers[QUERY] = answer(401, "Unauthorized")

    with pytest.raises(AuthenticationError):
        adapter.query("ASK {}")

    assert store.paths() == [QUERY]
