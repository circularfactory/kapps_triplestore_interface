"""`owl_get_classes_of_individual` leaves out the classes of `ignored_prefixes`.

A list entry is either a prefix name, as a plain string (`"owl"`, the default `["owl", "rdfs"]`),
or a namespace, as an rdflib `Namespace` (a full namespace IRI). A list may mix both.

These tests run without a triple store. A stub store evaluates the query text it receives with
rdflib against a small graph, so a test sees what the caller sees: whether the query parses, and
which classes come back. The query names its prefixes without declaring them, as the store has
them registered; the stub declares `rdf`, `rdfs` and `owl`. The stub drops the `FROM` clause that
selects GraphDB's explicit statements: the filter under test does not depend on it.
"""

from __future__ import annotations

import pytest
import requests
from pyparsing import ParseException
from rdflib import OWL, RDF, RDFS, Graph, Namespace, URIRef
from rdflib.plugins.sparql import prepareQuery

from kapps_triplestore_interface import BasicAuth, GraphDB, IRI, TripleStoreEndpoint
from tests._stub_store import BASE_URL, DATASET, PASSWORD, USERNAME, answer

EX = Namespace("http://example.org/ns#")
OTHER = Namespace("http://example.org/other#")
ODD = Namespace('http://example.org/odd"quote\\slash#')
INDIVIDUAL = URIRef("http://example.org/data#thing")

CLASSES = {
    "ex": EX.Machine,
    "other": OTHER.Tool,
    "odd": ODD.Part,
    "owl": OWL.Thing,
    "rdfs": RDFS.Resource,
}


def _graph() -> Graph:
    graph = Graph()
    for cls in CLASSES.values():
        graph.add((cls, RDF.type, OWL.Class))
        graph.add((INDIVIDUAL, RDF.type, cls))
    return graph


class EvaluatingStore:
    """Evaluates each SPARQL query it receives against `_graph()`, as the store would."""

    def __init__(self):
        self.graph = _graph()
        self.queries: list[str] = []

    def __call__(self, method, url, headers=None, data=None, **kwargs):
        self.queries.append(data)
        text = "\n".join(
            line for line in data.splitlines() if not line.startswith("FROM ")
        )
        try:
            query = prepareQuery(text, initNs={"rdf": RDF, "rdfs": RDFS, "owl": OWL})
        except ParseException as error:
            return answer(400, f"MALFORMED QUERY: {error}")
        result = self.graph.query(query)
        return answer(
            200,
            result.serialize(format="json").decode("utf-8"),
            "application/sparql-results+json",
        )


@pytest.fixture
def store(monkeypatch) -> EvaluatingStore:
    stub = EvaluatingStore()
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda session, method, url, **kwargs: stub(method, url, **kwargs),
    )
    return stub


@pytest.fixture
def adapter(store) -> GraphDB:
    return GraphDB(
        endpoint=TripleStoreEndpoint(url=BASE_URL, dataset=DATASET),
        auth=BasicAuth(USERNAME, PASSWORD),
    )


def _classes(adapter: GraphDB, **kwargs) -> set[IRI]:
    return set(adapter.owl_get_classes_of_individual(INDIVIDUAL, **kwargs))


def _without(*names: str) -> set[URIRef]:
    return {cls for name, cls in CLASSES.items() if name not in names}


def test_a_namespace_leaves_out_its_classes_and_keeps_the_others(adapter):
    classes = _classes(adapter, ignored_prefixes=[EX])

    assert EX.Machine not in classes
    assert OTHER.Tool in classes
    assert classes == _without("ex")


@pytest.mark.parametrize(
    ("ignored_prefixes", "left_out"),
    [
        pytest.param(None, ("owl", "rdfs"), id="the default"),
        pytest.param(["owl", "rdfs"], ("owl", "rdfs"), id="prefix names"),
        pytest.param(["owl"], ("owl",), id="one prefix name"),
        pytest.param(["owl", EX], ("owl", "ex"), id="a mixed list"),
        pytest.param([], (), id="an empty list"),
        pytest.param([OWL, RDFS], ("owl", "rdfs"), id="rdflib's defined namespaces"),
        pytest.param([URIRef(str(EX))], ("ex",), id="a URIRef"),
    ],
)
def test_prefix_names_namespaces_and_mixed_lists_filter_as_given(
    adapter, ignored_prefixes, left_out
):
    assert _classes(adapter, ignored_prefixes=ignored_prefixes) == _without(*left_out)


def test_a_namespace_with_a_quote_and_a_backslash_is_escaped(adapter, store):
    classes = _classes(adapter, ignored_prefixes=[ODD])

    assert classes == _without("odd")
    assert str(ODD) not in store.queries[-1]  # never written into the query as raw text
