"""An unchecked update warns that interface 3.0.0 always checks it.

`triples_update` and `triple_update` with `check_exist=False` emit one `DeprecationWarning`
at the caller's line, through GraphDB and through the Kadi adapter alike. The call still sends
what it sent before. The other operations keep `check_exist=False` without a warning.

These tests run without a triple store: `query` is stubbed for GraphDB, and the Kadi adapter
answers through the stub in `_stub_store.py`.
"""

# pylint: disable=duplicate-code
from __future__ import annotations

import inspect
import json
import logging
import threading
import warnings

import pytest
from rdflib import Literal

from kapps_triplestore_interface import GraphDB, IRI, connect_kadi
from tests._stub_store import BASE_URL, answer, store  # pylint: disable=unused-import

S = IRI("http://example.org/unchecked#s")
P = IRI("http://example.org/unchecked#p")
OLD = (S, P, Literal(1))
NEW = (S, P, Literal(2))
SUBJECT = IRI("http://example.org/unchecked#absent")
API = "/api/triple-store"
NAME = "my-repository"


class _Recorder:  # pylint: disable=too-few-public-methods
    def __init__(self):
        self.updates = []

    def __call__(self, query, update=False, **kwargs):
        text = query.to_string() if hasattr(query, "to_string") else query
        if update:
            self.updates.append(text)
            return True
        return {"head": {}, "boolean": True}


@pytest.fixture(name="db")
def fixture_db():
    db = GraphDB.__new__(GraphDB)
    db.logger = logging.getLogger("stub")
    db._named_graph = None
    db._repository = "stub"
    db._blank_ids = set()
    db._sessions = []
    db._sessions_lock = threading.Lock()
    db._sessions_generation = 0
    db.query = _Recorder()
    return db


@pytest.fixture(name="kadi")
def fixture_kadi(store):  # pylint: disable=redefined-outer-name
    store.answers[API] = answer(200, json.dumps({"name": NAME}), "application/json")
    return connect_kadi(host=BASE_URL, pat="pat_not-a-real-token")


def _deprecations(caught):
    return [w for w in caught if issubclass(w.category, DeprecationWarning)]


def test_unchecked_triples_update_warns_once_at_the_callers_line(db):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        line = inspect.currentframe().f_lineno + 1
        db.triples_update([OLD], [NEW], check_exist=False)
    (warning,) = _deprecations(caught)
    assert warning.filename == __file__
    assert warning.lineno == line
    message = str(warning.message)
    assert "triples_update" in message and "check_exist" in message
    assert "True whether or not" in message and "3.0.0" in message


def test_unchecked_triple_update_warns_once_at_the_callers_line(db):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        line = inspect.currentframe().f_lineno + 1
        db.triple_update(OLD, new_obj=Literal(2), check_exist=False)
    (warning,) = _deprecations(caught)
    assert warning.filename == __file__
    assert warning.lineno == line
    assert "triple_update" in str(warning.message)
    assert "3.0.0" in str(warning.message)


def test_unchecked_triples_update_warns_through_the_kadi_adapter(kadi):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        line = inspect.currentframe().f_lineno + 1
        kadi.triples_update([OLD], [NEW], check_exist=False)
    (warning,) = _deprecations(caught)
    assert warning.filename == __file__
    assert warning.lineno == line


def test_the_unchecked_update_still_sends_one_request(db):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert db.triples_update([OLD], [NEW], check_exist=False) is True
    assert len(db.query.updates) == 1
    assert "DELETE" in db.query.updates[0] and "INSERT" in db.query.updates[0]


def test_absent_subjects_with_check_exist_false_also_warns(db):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        db.triples_update([OLD], [], check_exist=False, absent_subjects=[SUBJECT])
    assert len(_deprecations(caught)) == 1


def test_a_checked_update_does_not_warn(db):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        db.triples_update([OLD], [NEW])
        db.triples_update([OLD], [NEW], check_exist=True)
        db.triple_update(OLD, new_obj=Literal(2))
    assert not _deprecations(caught)


@pytest.mark.parametrize(
    "operation",
    [
        lambda db: db.triples_add([OLD], check_exist=False),
        lambda db: db.triples_delete([OLD], check_exist=False),
        lambda db: db.triple_delete(OLD, check_exist=False),
    ],
    ids=["triples_add", "triples_delete", "triple_delete"],
)
def test_the_other_operations_keep_check_exist_false_without_a_warning(db, operation):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        operation(db)
    assert not _deprecations(caught)


def test_two_empty_lists_warn_and_send_nothing(db):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert db.triples_update([], [], check_exist=False) is True
    assert len(_deprecations(caught)) == 1
    assert not db.query.updates
