"""The store registries against a real GraphDB: prefixes, and SHACL shapes.

Every test here requests the `db` fixture, so it is in the `live` tier: it runs where the
suite's store is configured, as in CI, and skips elsewhere.

- **Prefixes.** A test writes only prefixes that it made itself, with a name that no other
  prefix has, and removes them afterwards. The test of the empty prefix skips on a dataset that
  maps the empty prefix already, because it would change a prefix that it did not make.
- **Shapes.** `shapes_set` replaces every shape of the dataset, so these tests need the suite's
  disposable dataset with SHACL validation, as every live test does. Each leaves the dataset
  with no shapes and without the data that it wrote. The documents name every IRI in full and
  declare no prefix, so that loading them adds no prefix to the dataset.
- **A dataset without SHACL validation.** One more dataset on the same store, created without
  SHACL validation, named by `GRAPHDB_TEST_REPOSITORY_WITHOUT_SHACL`. Without it, that test
  skips. The test writes nothing to it, unless the adapter fails to refuse.
"""

# pytest passes the fixtures by name.
# pylint: disable=redefined-outer-name,unused-argument

from __future__ import annotations

import os
import uuid

import pytest

from kapps_triplestore_interface import (
    GraphDB,
    GraphDBCredentials,
    ShaclValidationError,
    TripleStoreNotSupportedError,
)

WITHOUT_SHACL_ENV = "GRAPHDB_TEST_REPOSITORY_WITHOUT_SHACL"

EX = "http://example.org/store-registries#"
SH = "http://www.w3.org/ns/shacl#"
SHAPES_GRAPH = "http://rdf4j.org/schema/rdf4j#SHACLShapeGraph"
THING, ITEM, PART, COLOUR = (
    f"{EX}{name}" for name in ("Thing", "item", "part", "colour")
)

# A thing holds at most one part.
AT_MOST_ONE_PART = f"""
<{EX}PartShape> a <{SH}NodeShape> ;
    <{SH}targetClass> <{THING}> ;
    <{SH}property> [ <{SH}path> <{PART}> ; <{SH}maxCount> 1 ] .
"""
# A thing has no colour.
NO_COLOUR = f"""
<{EX}ColourShape> a <{SH}NodeShape> ;
    <{SH}targetClass> <{THING}> ;
    <{SH}property> [ <{SH}path> <{COLOUR}> ; <{SH}maxCount> 0 ] .
"""


def _unique_prefix() -> str:
    return f"registrytest{uuid.uuid4().hex[:8]}"


def _remove_if_present(db: GraphDB, *prefixes: str) -> None:
    present = db.prefixes_get()
    for prefix in prefixes:
        if prefix in present:
            db.prefix_delete(prefix)


# -- prefixes ----------------------------------------------------------------------------------


def test_a_prefix_is_set_read_changed_and_deleted(db: GraphDB):
    prefix = _unique_prefix()
    iri = f"{EX}{prefix}/"
    before = db.prefixes_get()
    assert prefix not in before
    try:
        db.prefix_set(prefix, iri)
        assert db.prefixes_get()[prefix] == iri

        db.prefix_set(prefix, f"{iri}changed/")
        assert db.prefixes_get()[prefix] == f"{iri}changed/"

        db.prefix_delete(prefix)
        assert db.prefixes_get() == before
    finally:
        _remove_if_present(db, prefix)


def test_the_empty_prefix_round_trips_and_its_delete_leaves_every_other_prefix(
    db: GraphDB,
):
    if "" in db.prefixes_get():
        pytest.skip(
            "the dataset maps the empty prefix already, and this test changes only prefixes"
            " that it made"
        )
    neighbour = _unique_prefix()
    try:
        # A prefix that the test made, beside the dataset's own, to see that both stay.
        db.prefix_set(neighbour, f"{EX}{neighbour}/")
        db.prefix_set("", f"{EX}empty/")
        assert db.prefixes_get()[""] == f"{EX}empty/"
        others = {p: n for p, n in db.prefixes_get().items() if p != ""}
        assert others[neighbour] == f"{EX}{neighbour}/"

        db.prefix_delete("")

        assert db.prefixes_get() == others
    finally:
        _remove_if_present(db, "", neighbour)


# -- shapes ------------------------------------------------------------------------------------


def _insert(db: GraphDB, triples: str) -> bool:
    return db.query(f"INSERT DATA {{ {triples} }}", update=True)


@pytest.fixture
def no_shapes_afterwards(db: GraphDB):
    """Remove the test's data and every shape after the test."""
    try:
        yield
    finally:
        db.query(f"DELETE WHERE {{ <{ITEM}> ?p ?o . }}", update=True)
        db.shapes_set("", "text/turtle")


def test_shapes_set_replaces_the_shapes(db: GraphDB, no_shapes_afterwards):
    db.shapes_set(AT_MOST_ONE_PART, "text/turtle")
    _insert(db, f"<{ITEM}> a <{THING}> ; <{PART}> <{EX}one> .")
    with pytest.raises(ShaclValidationError):
        _insert(db, f"<{ITEM}> <{PART}> <{EX}two> .")

    db.shapes_set(NO_COLOUR, "text/turtle")

    # Only the old shapes refused this write.
    assert _insert(db, f"<{ITEM}> <{PART}> <{EX}two> .")
    # The new shapes forbid this one.
    with pytest.raises(ShaclValidationError):
        _insert(db, f"<{ITEM}> <{COLOUR}> <{EX}red> .")
    assert not db.query(f"ASK {{ <{ITEM}> <{COLOUR}> ?colour }}")["boolean"]


def test_a_refused_replacement_keeps_the_old_shapes(db: GraphDB, no_shapes_afterwards):
    db.shapes_set(AT_MOST_ONE_PART, "text/turtle")
    _insert(db, f"<{ITEM}> a <{THING}> ; <{PART}> <{EX}one> ; <{COLOUR}> <{EX}red> .")

    # The data violates the new shapes, so the store refuses to replace the old ones.
    with pytest.raises(ShaclValidationError):
        db.shapes_set(NO_COLOUR, "text/turtle")

    # The old shapes still refuse a write that only they forbid.
    with pytest.raises(ShaclValidationError):
        _insert(db, f"<{ITEM}> <{PART}> <{EX}two> .")
    assert not db.query(f"ASK {{ <{ITEM}> <{PART}> <{EX}two> }}")["boolean"]


def test_shapes_set_with_an_empty_document_removes_every_shape(
    db: GraphDB, no_shapes_afterwards
):
    db.shapes_set(AT_MOST_ONE_PART + NO_COLOUR, "text/turtle")
    _insert(db, f"<{ITEM}> a <{THING}> ; <{PART}> <{EX}one> .")
    with pytest.raises(ShaclValidationError):
        _insert(db, f"<{ITEM}> <{PART}> <{EX}two> .")

    db.shapes_set("", "text/turtle")

    assert _insert(db, f"<{ITEM}> <{PART}> <{EX}two> .")
    assert _insert(db, f"<{ITEM}> <{COLOUR}> <{EX}red> .")


# -- a dataset without SHACL validation --------------------------------------------------------


@pytest.fixture
def without_shacl(db: GraphDB) -> GraphDB:
    """A client of the dataset without SHACL validation, on the suite's store, or skip."""
    dataset = os.getenv(WITHOUT_SHACL_ENV)
    if not dataset:
        pytest.skip(
            f"needs a dataset without SHACL validation; unset: {WITHOUT_SHACL_ENV}"
        )
    credentials = db._credentials
    store = GraphDB(
        credentials=GraphDBCredentials(
            base_url=credentials.base_url,
            username=credentials.username,
            password=credentials.password,
            repository=dataset,
        )
    )
    yield store
    store.close()


def _shapes_graph_size(store: GraphDB) -> int:
    """The statements of the shapes graph that a query sees. Without SHACL validation the
    shapes graph is a graph of plain data."""
    answer = store.query(
        f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{SHAPES_GRAPH}> {{ ?s ?p ?o }} }}"
    )
    return int(answer["results"]["bindings"][0]["n"]["value"])


def test_shapes_set_on_a_dataset_without_shacl_raises_and_writes_nothing(
    without_shacl: GraphDB,
):
    before = _shapes_graph_size(without_shacl)
    try:
        with pytest.raises(TripleStoreNotSupportedError) as refused:
            without_shacl.shapes_set(AT_MOST_ONE_PART, "text/turtle")

        assert f"'{without_shacl.dataset}'" in str(refused.value)
        assert _shapes_graph_size(without_shacl) == before
    finally:
        # Only if the adapter failed to refuse, and the graph held nothing before.
        if before == 0 and _shapes_graph_size(without_shacl) != 0:
            without_shacl.graph_clear(SHAPES_GRAPH)
