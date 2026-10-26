"""The contract type declares exactly the operations that the layers above the interface call.

These tests run without a triple store.

The operations were measured in the code of the object-graph mapper and the middleware on
2026-10-10: every call that their sources, tests, examples and demo scripts make on a
store. An operation that none of them calls is not in the contract, even when the GraphDB
adapter has it. The contract declares each operation under its new name: `graph_get`,
`graph_add`, `graph_clear` and `dataset` replace the names that were measured.

The store registries are the exception that the border names: callers reached past the
interface for a dataset's prefixes and its SHACL shapes, so the contract declares the four
operations that replace those calls.
"""

from __future__ import annotations

import inspect

import pytest

from kapps_triplestore_interface import GraphDB, TripleStore

MEASURED = {
    "query",
    "triple_exists",
    "triple_add",
    "triple_delete",
    "triples_get",
    "triples_add",
    "triples_delete",
    "triples_update",
    "iri_exists",
    "new_iri",
    "is_subclass",
    "owl_get_classes_of_individual",
    "graph_get",
    "graph_add",
    "graph_clear",
    "close",
    "dataset",
}

# The store registries: the operations that replace those callers' calls past the interface.
REGISTRIES = {"prefixes_get", "prefix_set", "prefix_delete", "shapes_set", "validate"}

OPERATIONS = sorted((MEASURED | REGISTRIES) - {"dataset"})


def _declared(contract: type) -> set[str]:
    return {name for name in vars(contract) if not name.startswith("_")}


def _parameters(function) -> list[tuple[str, object, object]]:
    return [
        (parameter.name, parameter.kind, parameter.default)
        for parameter in inspect.signature(function).parameters.values()
    ]


def test_the_contract_declares_exactly_the_measured_operations_and_the_registries():
    assert _declared(TripleStore) == MEASURED | REGISTRIES


@pytest.mark.parametrize("name", OPERATIONS)
def test_the_adapter_has_each_operation_with_the_parameters_of_the_contract(name):
    assert _parameters(getattr(GraphDB, name)) == _parameters(
        getattr(TripleStore, name)
    )


def test_the_dataset_of_a_store_is_a_read_only_attribute_of_the_contract():
    assert isinstance(TripleStore.dataset, property)
    assert TripleStore.dataset.fset is None
    assert isinstance(GraphDB.dataset, property)


def test_the_adapter_satisfies_the_contract_without_inheriting_it():
    """A structural contract. A test double satisfies it as the adapter does, and inheriting a
    `Protocol` would add members to the adapter's class that a consumer's inventory of them
    does not know."""
    assert TripleStore not in GraphDB.__mro__
    assert getattr(TripleStore, "_is_protocol", False)
