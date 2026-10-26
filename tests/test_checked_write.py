"""Unit tests of the checked write, with `query` stubbed.

They assert on the requests a write sends: the update with its precondition and its receipt,
the `ASK` for the receipt, and the removal of the receipt, which rides at the end of the
client's next checked write, or in `close()`. What the store does with them is tested live in
`test_checked_write_live.py`.
"""

import logging
import re
import threading
from uuid import uuid4

import pytest
from rdflib import BNode, Literal, URIRef
from rdflib.plugins.sparql.parser import parseUpdate

from kapps_triplestore_interface import (
    GraphDB,
    IRI,
    PreconditionFailedError,
    SPARQLQuery,
)
from kapps_triplestore_interface.exceptions import (
    InvalidInputError,
    ShaclValidationError,
    TripleStoreInterfaceError,
    TripleStoreResponseError,
    TripleStoreUnavailableError,
)
from kapps_triplestore_interface.queries.checked_write import (
    DEFAULT_GRAPH,
    RECEIPT_GRAPH,
    RECEIPT_PREDICATE,
    receipts_to_remove,
)
from kapps_triplestore_interface.utils import utils

S = IRI("http://example.org/s")
S2 = IRI("http://example.org/s2")
P = IRI("http://example.org/p")
Q = IRI("http://example.org/q")
GRAPH = IRI("http://example.org/graph")

RECEIPT_IRI = re.compile(r"<(urn:uuid:[0-9a-f-]{36})>")


class StubStore:
    """Records every request. Answers the receipt `ASK` with `found`."""

    def __init__(self):
        self.requests = []  # (text, update)
        self.found = True
        self.fail_update_at = None  # index of an update request that raises

    def __call__(self, query, update=False, **kwargs):
        text = query.to_string() if isinstance(query, SPARQLQuery) else query
        self.requests.append((text, update))
        if update:
            index = sum(1 for _, u in self.requests if u) - 1
            if self.fail_update_at == index:
                raise TripleStoreResponseError(
                    "Error while querying GraphDB (500) - stub"
                )
            return True
        return {"head": {}, "boolean": self.found}


@pytest.fixture
def store() -> StubStore:
    return StubStore()


@pytest.fixture
def stub_db(store) -> GraphDB:
    """A GraphDB whose `query` is the stub. Built with `__new__`: `__init__` logs in."""
    db = GraphDB.__new__(GraphDB)
    db.logger = logging.getLogger("stub")
    db._named_graph = None
    db._repository = "stub"
    db._blank_ids = set()
    db._sessions = []
    db._sessions_lock = threading.Lock()
    db.query = store
    return db


# Each checked write: (call, the precondition's triples as `.triples`, patterns its WHERE needs)
def _add(db, g):
    return db.triples_add([(S, P, Literal(1))], named_graph=g)


def _delete(db, g):
    return db.triples_delete([(S, P, Literal(1)), (S, Q, Literal(2))], named_graph=g)


def _update(db, g):
    return db.triples_update([(S, P, Literal(1))], [(S, P, Literal(2))], named_graph=g)


def _single_delete(db, g):
    return db.triple_delete((S, P, Literal(1)), named_graph=g)


def _single_update(db, g):
    return db.triple_update((S, P, Literal(1)), new_obj=Literal(2), named_graph=g)


OLD = (S, P, Literal(1))
WRITES = {
    "triples_add": (_add, [OLD]),
    "triples_delete": (_delete, [OLD, (S, Q, Literal(2))]),
    "triples_update": (_update, [OLD]),
    "triple_delete": (_single_delete, [OLD]),
    "triple_update": (_single_update, [OLD]),
}


@pytest.fixture(params=sorted(WRITES))
def write(request):
    return request.param


@pytest.fixture(params=[None, GRAPH], ids=["default-graph", "named-graph"])
def graph(request):
    return request.param


def _split(update: str) -> dict:
    """The clauses of a rendered update, by keyword at the start of a line."""
    clauses, current = {}, None
    for line in update.splitlines():
        head = line.split(" ", 1)[0]
        if head in ("WITH", "DELETE", "INSERT", "USING", "WHERE"):
            current = head
            clauses[current] = line
        elif current:
            clauses[current] += "\n" + line
    return clauses


def test_the_update_carries_the_receipt_and_the_precondition(
    stub_db, store, write, graph
):
    call, named = WRITES[write]
    assert call(stub_db, graph) is True

    update, is_update = store.requests[0]
    assert is_update
    parseUpdate(update)
    clauses = _split(update)

    receipt = RECEIPT_IRI.search(clauses["INSERT"]).group(1)
    assert (
        f"GRAPH {RECEIPT_GRAPH.n3()} {{ <{receipt}> {RECEIPT_PREDICATE.n3()} "
        in clauses["INSERT"]
    )
    assert "^^<http://www.w3.org/2001/XMLSchema#dateTime>" in clauses["INSERT"]

    old = utils.triple_to_string(OLD, ".")
    if write == "triples_add":
        assert "FILTER NOT EXISTS" in clauses["WHERE"]
        assert old in clauses["WHERE"]
        assert "DELETE" not in clauses
    else:
        assert old in clauses["WHERE"]
        assert old in clauses["DELETE"]

    if graph is None:
        assert "WITH" not in clauses
        assert clauses["USING"] == f"USING {DEFAULT_GRAPH.n3()}"
        if "DELETE" in clauses:
            assert f"GRAPH {DEFAULT_GRAPH.n3()} {{" in clauses["DELETE"]
    else:
        assert clauses["WITH"] == f"WITH {GRAPH.n3()}"
        assert "USING" not in clauses
        assert "GRAPH" not in clauses.get("DELETE", "")


def test_a_found_receipt_is_kept_to_remove_and_the_write_returns_true(
    stub_db, store, write, graph
):
    """Two requests: the update and the `ASK`. The receipt waits for the next request."""
    call, _ = WRITES[write]
    assert call(stub_db, graph) is True

    assert [u for _, u in store.requests] == [True, False]
    receipt = RECEIPT_IRI.search(store.requests[0][0]).group(1)
    ask = store.requests[1][0]
    assert ask.startswith("ASK") and f"<{receipt}>" in ask and RECEIPT_GRAPH.n3() in ask
    assert [str(r) for r in receipts_to_remove(stub_db)] == [receipt]


def test_a_missing_receipt_raises_and_sends_no_cleanup(stub_db, store, write, graph):
    call, named = WRITES[write]
    store.found = False

    with pytest.raises(PreconditionFailedError) as refused:
        call(stub_db, graph)

    assert refused.value.triples == named
    assert refused.value.named_graph == graph
    assert write in refused.value.message
    assert [u for _, u in store.requests] == [True, False]


def test_the_client_default_graph_is_the_target(stub_db, store, write):
    call, _ = WRITES[write]
    stub_db._named_graph = GRAPH
    store.found = False

    with pytest.raises(PreconditionFailedError) as refused:
        call(stub_db, None)

    assert refused.value.named_graph == GRAPH
    assert _split(store.requests[0][0])["WITH"] == f"WITH {GRAPH.n3()}"


def test_a_failed_write_propagates_and_asks_nothing(stub_db, store, write):
    call, _ = WRITES[write]
    store.fail_update_at = 0

    with pytest.raises(TripleStoreResponseError):
        call(stub_db, None)

    assert len(store.requests) == 1


@pytest.mark.parametrize("graph_", [None, GRAPH], ids=["default-graph", "named-graph"])
def test_check_exist_false_sends_one_request_without_receipt(
    stub_db, store, write, graph_
):
    call, _ = WRITES[write]
    kwargs = {"check_exist": False, "named_graph": graph_}
    calls = {
        "triples_add": lambda: stub_db.triples_add([OLD], **kwargs),
        "triples_delete": lambda: stub_db.triples_delete([OLD], **kwargs),
        "triples_update": lambda: stub_db.triples_update(
            [OLD], [(S, P, Literal(2))], **kwargs
        ),
        "triple_delete": lambda: stub_db.triple_delete(OLD, **kwargs),
        "triple_update": lambda: stub_db.triple_update(
            OLD, new_obj=Literal(2), **kwargs
        ),
    }
    assert calls[write]() is True

    assert len(store.requests) == 1
    text = store.requests[0][0]
    assert "urn:x-kapps" not in text
    assert "USING" not in text
    expected_start = {
        "triples_add": "INSERT DATA",
        "triples_delete": "DELETE DATA",
        "triple_delete": "DELETE DATA",
    }.get(write)
    if expected_start:
        assert text.lstrip().startswith(expected_start)


def test_unchecked_triples_update_keeps_its_query_text(stub_db, store):
    """`check_exist=False` sends the text that `triples_update` sent before the checked write."""
    stub_db.triples_update(
        [OLD], [(S, P, Literal(2))], check_exist=False, named_graph=GRAPH
    )

    assert store.requests[0][0] == (
        f"WITH {GRAPH.n3()}\n"
        "DELETE {\n"
        f"  {utils.triple_to_string(OLD, '.')}\n"
        "}\n"
        "INSERT {\n"
        f"  {utils.triple_to_string((S, P, Literal(2)), '.')}\n"
        "}\n"
        "WHERE {\n"
        f"  {utils.triple_to_string(OLD, '.')}\n"
        "}"
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda db: db.triples_add([]),
        lambda db: db.triples_add([], absent_subjects=[S]),
        lambda db: db.triples_delete([]),
        lambda db: db.triples_update([], []),
        lambda db: db.triples_update([], [], absent_subjects=[S]),
    ],
    ids=["add", "add-absent", "delete", "update", "update-absent"],
)
def test_empty_input_sends_nothing(stub_db, store, call):
    assert call(stub_db) is True
    assert store.requests == []


def test_the_add_precondition_is_none_of_the_groups(stub_db, store):
    """`FILTER NOT EXISTS { {g1} UNION {g2} }`: one existing group refuses the add.

    The removed `insert_exists` form, `FILTER NOT EXISTS { t1 . t2 }`, meant "not all of them".
    """
    node = BNode("n")
    stub_db.triples_add([(S, P, node), (node, Q, Literal(1)), (S2, P, Literal(3))])

    where = _split(store.requests[0][0])["WHERE"]
    assert where.count("UNION") == 1
    groups = re.findall(r"\{\n((?:\s+[^\n{}]+\n)+)\s+\}", where)
    assert len(groups) == 2
    # the blank node is a variable inside the check, not the variable that the insert mints
    check_vars = set(re.findall(r"\?\w+", groups[0]))
    insert_vars = set(re.findall(r"\?\w+", _split(store.requests[0][0])["INSERT"]))
    assert len(check_vars) == 1 and len(insert_vars) == 1
    assert check_vars.isdisjoint(insert_vars)
    assert "BIND(BNODE() AS " + insert_vars.pop() + ")" in where


@pytest.mark.parametrize("write_", ["triples_add", "triples_update"])
def test_absent_subjects_add_one_filter_each(stub_db, store, write_):
    if write_ == "triples_add":
        stub_db.triples_add([OLD], absent_subjects=[S, str(S2)])
    else:
        stub_db.triples_update(
            [OLD], [(S, P, Literal(2))], absent_subjects=[S, str(S2)]
        )

    update = store.requests[0][0]
    parseUpdate(update)
    where = _split(update)["WHERE"]
    assert re.search(
        rf"FILTER NOT EXISTS \{{ {re.escape(S.n3())} \?\w+ \?\w+ \. \}}", where
    )
    assert re.search(
        rf"FILTER NOT EXISTS \{{ {re.escape(S2.n3())} \?\w+ \?\w+ \. \}}", where
    )
    if write_ == "triples_update":
        assert utils.triple_to_string(OLD, ".") in where


@pytest.mark.parametrize("write_", ["triples_add", "triples_update"])
def test_absent_subjects_are_named_in_the_error(stub_db, store, write_):
    store.found = False
    with pytest.raises(PreconditionFailedError) as refused:
        if write_ == "triples_add":
            stub_db.triples_add([OLD], absent_subjects=[S2], named_graph=GRAPH)
        else:
            stub_db.triples_update([OLD], [], absent_subjects=[S2], named_graph=GRAPH)

    assert refused.value.triples == [OLD, (S2, None, None)]
    assert refused.value.named_graph == GRAPH


@pytest.mark.parametrize("write_", ["triples_add", "triples_update"])
def test_absent_subjects_check_also_without_check_exist(stub_db, store, write_):
    if write_ == "triples_add":
        stub_db.triples_add([OLD], check_exist=False, absent_subjects=[S2])
    else:
        stub_db.triples_update([OLD], [], check_exist=False, absent_subjects=[S2])

    update = store.requests[0][0]
    assert RECEIPT_GRAPH.n3() in update
    where = _split(update)["WHERE"]
    assert where.count("FILTER NOT EXISTS") == 1
    assert S2.n3() in where


@pytest.mark.parametrize(
    "subjects",
    [[BNode("b")], ["_:b"], str(S)],
    ids=["bnode", "bnode-string", "single-string"],
)
def test_absent_subjects_must_be_a_list_of_iris(stub_db, store, subjects):
    with pytest.raises(InvalidInputError):
        stub_db.triples_add([OLD], absent_subjects=subjects)
    assert store.requests == []


def test_each_write_has_its_own_receipt(stub_db, store):
    stub_db.triple_delete(OLD)
    stub_db.triple_delete(OLD)
    updates = [text for text, update in store.requests if update and "INSERT" in text]
    receipts = {RECEIPT_IRI.search(text).group(1) for text in updates}
    assert len(receipts) == 2


def test_the_error_type():
    assert issubclass(PreconditionFailedError, TripleStoreInterfaceError)
    assert not issubclass(PreconditionFailedError, TripleStoreResponseError)
    error = PreconditionFailedError("m", triples=[OLD], named_graph=GRAPH)
    assert (error.message, error.triples, error.named_graph) == ("m", [OLD], GRAPH)
    assert str(error) == "m"
    assert PreconditionFailedError("m").triples == []


def test_insert_exists_is_gone():
    """Its `FILTER NOT EXISTS { t1 . t2 }` meant "not all of them exist", and it had no caller."""
    assert not hasattr(SPARQLQuery, "insert_exists")
    assert not hasattr(SPARQLQuery, "add_insert_exists_block")


def test_the_receipt_names_carry_no_vendor_word():
    for value in (RECEIPT_GRAPH, RECEIPT_PREDICATE):
        assert isinstance(value, URIRef)
        assert not re.search(r"graphdb|ontotext|rdf4j", value, re.IGNORECASE)


# --- the removal of a receipt rides in the next checked write ----------------------------

REMOVAL = re.compile(
    r"DELETE WHERE \{ GRAPH "
    + re.escape(RECEIPT_GRAPH.n3())
    + r" \{ <(urn:uuid:[0-9a-f-]{36})> \?p \?o \} \}"
)


def _operations(text: str) -> list:
    """The operations of an update request, split at the `;` between them."""
    return [part.strip() for part in re.split(r" ;\n", text)]


def _written(text: str) -> str:
    """The receipt that the first operation of an update request inserts."""
    return RECEIPT_IRI.search(_split(_operations(text)[0])["INSERT"]).group(1)


def _removed(text: str) -> list:
    return REMOVAL.findall(text)


class ReceiptStore(StubStore):
    """A recording store that holds receipts: an update inserts its receipt and applies its
    removals, and the `ASK` answers whether the receipt is there. Safe for several threads.
    """

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.present = set()
        self.inserted = []
        self.removed = []

    def __call__(self, query, update=False, **kwargs):
        with self.lock:
            answer = super().__call__(query, update, **kwargs)
            text = self.requests[-1][0]
            if update:
                first = _operations(text)[0]
                if RECEIPT_PREDICATE.n3() in first:
                    receipt = RECEIPT_IRI.search(first).group(1)
                    self.inserted.append(receipt)
                    if self.found:
                        self.present.add(receipt)
                for receipt in _removed(text):
                    self.removed.append(receipt)
                    self.present.discard(receipt)
                return answer
            receipt = RECEIPT_IRI.search(text).group(1)
            return {"head": {}, "boolean": receipt in self.present}


@pytest.fixture
def receipt_store() -> ReceiptStore:
    return ReceiptStore()


@pytest.fixture
def receipt_db(stub_db, receipt_store) -> GraphDB:
    stub_db.query = receipt_store
    return stub_db


N = 5


def test_n_checked_writes_send_n_updates_and_n_asks_and_no_removal_of_their_own(
    receipt_db, receipt_store, write, graph
):
    call, _ = WRITES[write]
    for _ in range(N):
        assert call(receipt_db, graph) is True

    kinds = [u for _, u in receipt_store.requests]
    assert kinds == [True, False] * N
    for text, update in receipt_store.requests:
        assert not text.lstrip().startswith("DELETE WHERE")
        if update:
            parseUpdate(text)


def test_update_k_starts_with_its_own_update_and_ends_with_the_removal_of_receipt_k_1(
    receipt_db, receipt_store, write, graph
):
    call, _ = WRITES[write]
    for _ in range(N):
        call(receipt_db, graph)

    updates = [text for text, update in receipt_store.requests if update]
    receipts = [_written(text) for text in updates]
    assert len(set(receipts)) == N
    assert _removed(updates[0]) == []
    for k in range(1, N):
        operations = _operations(updates[k])
        # its own update first, as the request of a write on its own would be
        assert RECEIPT_PREDICATE.n3() in operations[0]
        assert not operations[0].startswith("DELETE WHERE")
        assert REMOVAL.findall(operations[0]) == []
        # and the removal of the previous receipt last, as an operation of its own
        assert operations[1:] == [
            f"DELETE WHERE {{ GRAPH {RECEIPT_GRAPH.n3()} {{ <{receipts[k - 1]}> ?p ?o }} }}"
        ]
    assert receipt_store.present == {receipts[-1]}


@pytest.mark.parametrize(
    "error",
    [
        TripleStoreResponseError("Error while querying GraphDB (500) - stub"),
        ShaclValidationError("refused", report="report"),
        TripleStoreUnavailableError("No answer - stub"),
    ],
    ids=["error-status", "shacl-refusal", "no-answer"],
)
def test_a_refused_update_keeps_the_receipts_it_carried(
    receipt_db, receipt_store, error
):
    receipt_db.triple_delete(OLD)
    receipt_db.triple_delete(OLD)
    first, second = (_written(t) for t, u in receipt_store.requests if u)

    def refuse(query, update=False, **kwargs):
        receipt_store.requests.append((query, update))
        raise error

    receipt_db.query = refuse
    with pytest.raises(type(error)) as raised:
        receipt_db.triple_delete(OLD)
    assert raised.value is error
    refused = receipt_store.requests[-1][0]
    assert _removed(refused) == [second]

    receipt_db.query = receipt_store
    receipt_db.triple_delete(OLD)
    again = [t for t, u in receipt_store.requests if u][-1]
    assert _removed(again) == [second]
    assert _written(again) not in (first, second)
    assert receipt_store.present == {_written(again)}


def test_a_false_precondition_raises_and_its_carried_removals_were_applied(
    receipt_db, receipt_store
):
    receipt_db.triple_delete(OLD)
    receipt_store.found = False

    with pytest.raises(PreconditionFailedError):
        receipt_db.triple_delete(OLD)

    first = _written(receipt_store.requests[0][0])
    assert _removed(receipt_store.requests[2][0]) == [first]
    assert receipt_store.present == set()
    assert len(receipts_to_remove(receipt_db)) == 0


def test_a_failed_ask_propagates_and_keeps_no_receipt_to_remove(
    receipt_db, receipt_store
):
    """As on `main`: the `ASK` error propagates, and the receipt stays for a sweep."""

    def ask_fails(query, update=False, **kwargs):
        if update:
            return receipt_store(query, update, **kwargs)
        raise TripleStoreUnavailableError("No answer - stub")

    receipt_db.query = ask_fails
    with pytest.raises(TripleStoreUnavailableError):
        receipt_db.triple_delete(OLD)
    assert len(receipts_to_remove(receipt_db)) == 0


def test_checked_writes_from_several_threads_remove_every_receipt(
    receipt_db, receipt_store
):
    threads, writes = 8, 25
    barrier = threading.Barrier(threads)
    errors = []

    def writer():
        barrier.wait()
        try:
            for _ in range(writes):
                assert receipt_db.triple_delete(OLD) is True
        except BaseException as error:  # reported below, never swallowed
            errors.append(error)

    workers = [threading.Thread(target=writer) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)

    assert errors == []
    assert len(receipt_store.inserted) == threads * writes
    receipt_db.close()
    assert receipt_store.present == set()
    assert sorted(receipt_store.removed) == sorted(receipt_store.inserted)


def test_close_removes_every_receipt_still_to_remove_in_one_request(
    receipt_db, receipt_store
):
    """Several receipts wait when writes of several threads overlap; one write leaves one."""
    receipt_db.triple_delete(OLD)
    others = [URIRef(f"urn:uuid:{uuid4()}") for _ in range(2)]
    for receipt in others:
        receipt_store.present.add(str(receipt))
        receipts_to_remove(receipt_db).add(receipt)
    held = set(receipt_store.present)
    assert len(held) == 3
    before = len(receipt_store.requests)

    receipt_db.close()

    sent = receipt_store.requests[before:]
    assert len(sent) == 1
    text, update = sent[0]
    assert update and text.startswith("DELETE WHERE")
    parseUpdate(text)
    assert set(_removed(text)) == held and len(_operations(text)) == 3
    assert receipt_store.present == set()

    receipt_db.close()
    assert len(receipt_store.requests) == before + 1


def test_close_sends_nothing_when_there_is_no_receipt_to_remove(
    receipt_db, receipt_store
):
    receipt_db.close()
    assert receipt_store.requests == []


def test_a_failed_removal_in_close_warns_keeps_the_receipts_and_closes_the_sessions(
    receipt_db, receipt_store, caplog
):
    receipt_db.triple_delete(OLD)
    receipt = _written(receipt_store.requests[0][0])
    closed = []

    class Session:
        def close(self):
            closed.append(self)

    receipt_db._sessions = [Session()]
    receipt_store.fail_update_at = 1

    with caplog.at_level(logging.WARNING, logger="stub"):
        receipt_db.close()

    assert len(closed) == 1
    assert [str(r) for r in receipts_to_remove(receipt_db)] == [receipt]
    assert any(
        record.levelno == logging.WARNING and receipt in record.getMessage()
        for record in caplog.records
    )
