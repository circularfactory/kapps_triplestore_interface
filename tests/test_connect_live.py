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


def _endpoint(db: GraphDB, dataset: str | None = None) -> TripleStoreEndpoint:
    return TripleStoreEndpoint(
        url=db._credentials.base_url, dataset=dataset or db._credentials.repository
    )


def _auth(db: GraphDB, password: str | None = None) -> GDBTokenAuth:
    return GDBTokenAuth(db._credentials.username, password or db._credentials.password)


def test_connect_returns_a_store_that_answers(db):
    store = connect(_endpoint(db), _auth(db))
    try:
        assert store.dataset == db.dataset
        assert store.query("ASK {}")["boolean"] is True
    finally:
        store.close()


def test_connect_to_a_dataset_that_does_not_exist_raises_the_repository_error(db):
    with pytest.raises(InvalidDatasetError):
        connect(_endpoint(db, "SomeWrongRepository"), _auth(db))


def test_connect_with_a_wrong_password_raises_authentication_error(db):
    with pytest.raises(AuthenticationError):
        connect(_endpoint(db), _auth(db, "SomeWrongPassword"))
