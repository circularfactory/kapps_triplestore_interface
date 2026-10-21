"""`connect()` against a real GraphDB.

These tests request the `db` fixture, so they run where the suite's store is configured, as in
CI, and skip elsewhere.
"""

from __future__ import annotations

import pytest

from kapps_triplestore_interface import (
    AuthenticationError,
    GDBTokenAuth,
    GraphDB,
    TripleStoreEndpoint,
    connect,
)
from kapps_triplestore_interface.exceptions import InvalidDatasetError


def _endpoint(store_settings, dataset: str | None = None) -> TripleStoreEndpoint:
    return TripleStoreEndpoint(
        url=store_settings["base_url"], dataset=dataset or store_settings["repository"]
    )


def _auth(store_settings, password: str | None = None) -> GDBTokenAuth:
    return GDBTokenAuth(
        store_settings["username"], password or store_settings["password"]
    )


def test_connect_returns_a_store_that_answers(db, store_settings):
    store = connect(_endpoint(store_settings), _auth(store_settings))
    try:
        assert store.dataset == db.dataset
        assert store.query("ASK {}")["boolean"] is True
    finally:
        store.close()


def test_connect_to_a_dataset_that_does_not_exist_raises_the_repository_error(
    db, store_settings
):
    with pytest.raises(InvalidDatasetError):
        connect(_endpoint(store_settings, "SomeWrongRepository"), _auth(store_settings))


def test_connect_with_a_wrong_password_raises_authentication_error(db, store_settings):
    with pytest.raises(AuthenticationError):
        connect(_endpoint(store_settings), _auth(store_settings, "SomeWrongPassword"))
