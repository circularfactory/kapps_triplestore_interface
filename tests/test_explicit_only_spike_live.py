"""Spike: does `infer=false` read what the explicit pseudo-graph reads?

The query builder writes "explicit statements only" (`include_implicit=False`) as GraphDB's
pseudo-graph `FROM <http://www.ontotext.com/explicit>`, into the query text. The RDF4J protocol
has a request parameter for the same scope, `infer`, which another RDF4J-based store also reads.
If both give the same rows for the reads that applications built on the interface make, the
adapter can own that switch, and no query text needs a vendor graph (option B). If not, the store
must render the query (option A).

Per read shape, the probe sends three variants of the same builder query and records their rows:

- **pseudo**: `include_implicit=False`, which renders the pseudo-graph; sent as `query()` sends it.
- **infer=false**: the same builder query with both scopes on (no pseudo-graph), sent with the
  request parameter `infer=false` (the private prototype `RDF4JClient._query`).
- **control**: the same builder query with both scopes on, sent as `query()` sends it, so with
  inference. Where the control has no more rows than the pseudo variant, no inferred statement
  reaches the shape, and an "equal" verdict for it says nothing about inference.

The verdict per shape is a measurement, not a test assertion: the probe fails only when its own
seed is missing. Set `EXPLICIT_PROBE_REPORT` to a file path to receive the result table in
Markdown; the table also goes to the terminal summary of each test (`-rA`).

The Kadi adapter is probed only when `EXPLICIT_PROBE_KADI_URL`, `EXPLICIT_PROBE_KADI_DATASET`
and `EXPLICIT_PROBE_KADI_PAT` name a disposable Kadi dataset and a token with the read and
write scopes. Without them it is skipped and the report says "Kadi: not measured".

The shapes copy the explicit-only reads of an object-graph mapper and of a service layer built
on the interface, as text. Each names what it stands for; the report of the spike lists
their sources.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from kapps_triplestore_interface import (
    GraphDB,
    KadiPATAuth,
    TripleStoreEndpoint,
    connect,
)
from kapps_triplestore_interface.auth import BasicAuth
from kapps_triplestore_interface.sparql_query import SPARQLQuery
from tests._stub_store import (  # pylint: disable=unused-import
    BASE_URL,
    DATASET,
    PASSWORD,
    USERNAME,
    store,
)

EX = "http://example.org/explicit_spike#"
GRAPH = "http://example.org/explicit_spike_graph"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"

# The ontology: a class chain, a domain on the superclass, a union domain, an inverse pair, a
# subproperty, and a cardinality restriction on the subclass. On `rdfsplus-optimized` it makes
# the store infer subclass types, inverse links, superproperty values and transitive subclasses.
ONTOLOGY = f"""
<{EX}Sub> <{RDFS}subClassOf> <{EX}Super> .
<{EX}Super> <{RDFS}subClassOf> <{EX}Top> .
<{EX}Sub> a <{OWL}Class> .
<{EX}Super> a <{OWL}Class> .
<{EX}Top> a <{OWL}Class> .
<{EX}Other> a <{OWL}Class> .
<{EX}hasPart> a <{OWL}ObjectProperty> .
<{EX}hasPart> <{RDFS}domain> <{EX}Super> .
<{EX}partOf> <{OWL}inverseOf> <{EX}hasPart> .
<{EX}hasSpecialPart> <{RDFS}subPropertyOf> <{EX}hasPart> .
<{EX}name> <{RDFS}domain> _:union .
_:union <{OWL}unionOf> ( <{EX}Super> <{EX}Other> ) .
<{EX}Sub> <{RDFS}subClassOf> _:restriction .
_:restriction a <{OWL}Restriction> .
_:restriction <{OWL}onProperty> <{EX}hasPart> .
_:restriction <{OWL}maxCardinality> 1 .
"""

# The instances: in the default graph, an instance of the subclass with a subproperty link, a
# name and an anonymous node; in the named graph, a second instance with a subproperty link.
INSTANCES = f"""
<{EX}i> a <{EX}Sub> .
<{EX}i> <{EX}name> "i" .
<{EX}i> <{EX}hasSpecialPart> <{EX}j> .
<{EX}i> <{EX}detail> _:node .
_:node <{EX}hasSpecialPart> <{EX}k> .
_:node <{EX}name> "node" .
<{EX}g> <{EX}name> "g, in the default graph" .
"""
NAMED_INSTANCES = f"""
<{EX}g> a <{EX}Sub> .
<{EX}g> <{EX}hasSpecialPart> <{EX}h> .
"""
# `<i>` exists only in the default graph. `<g>` has its instance data in the named graph and one
# name in the default graph, so a read scoped to one graph shows whether it sees the other.
NIL = "http://rdf4j.org/schema/rdf4j#nil"


@dataclass(frozen=True)
class Shape:
    """A read shape: the builder query, with the scope given by `include_implicit`."""

    name: str
    build: Callable[[bool], SPARQLQuery]
    # Where the shape comes from.
    source: str


def _select(variables, where, **kwargs) -> Callable[[bool], SPARQLQuery]:
    return lambda implicit: SPARQLQuery.select(
        variables=variables, where_clauses=where, include_implicit=implicit, **kwargs
    )


def _ask(where, **kwargs) -> Callable[[bool], SPARQLQuery]:
    return lambda implicit: SPARQLQuery.ask(
        where_clauses=where, include_implicit=implicit, **kwargs
    )


# A mapper's property discovery: the domains of a class and its superclasses, also in unions.
_CLASS_SPEC_BRANCHES = "\nUNION\n".join(
    f"{{ {branch} }}"
    for branch in (
        f"?property <{RDFS}domain> ?class .",
        f"?property <{RDFS}domain> ?union_class . "
        f"?union_class <{OWL}unionOf> ?list . "
        f"?list <{RDF}rest>*/<{RDF}first> ?class .",
    )
)

SHAPES = [
    Shape(
        "subject triples, default graph",
        _select(["?p", "?o"], [f"<{EX}i> ?p ?o ."]),
        "a mapper's stored values of a subject; interface `triples_get`",
    ),
    Shape(
        "subject triples, no graph named, subject in both graphs",
        _select(["?p", "?o"], [f"<{EX}g> ?p ?o ."]),
        "the default graph's scope: does either variant see a named graph?",
    ),
    Shape(
        "subject triples, default graph alone (rdf4j#nil)",
        _select(["?p", "?o"], [f"<{EX}g> ?p ?o ."], named_graph=NIL),
        "interface checked writes' scope `rdf4j#nil`, without the named graphs",
    ),
    Shape(
        "class specification: properties",
        _select(
            ["?property"],
            [_CLASS_SPEC_BRANCHES, f"<{EX}Sub> <{RDFS}subClassOf>* ?class ."],
        ),
        "a mapper's property discovery of a class",
    ),
    Shape(
        "class specification: maximum counts",
        _select(
            ["?property", "?bound"],
            [
                f"<{EX}Sub> <{RDFS}subClassOf>* ?restriction .",
                "FILTER(isBlank(?restriction))",
                f"?restriction <{OWL}onProperty> ?property .",
                f"{{ ?restriction <{OWL}maxCardinality> ?bound . }}",
            ],
        ),
        "a mapper's maximum counts of a class",
    ),
    Shape(
        "fetch: anonymous node",
        _select(
            ["?bnode", "?property", "?value"],
            [f"<{EX}i> <{EX}detail> ?bnode .", "?bnode ?property ?value ."],
        ),
        "a mapper's fetch of an anonymous node",
    ),
    Shape(
        "stored node with OPTIONAL content",
        _select(
            ["?node", "?p", "?v"],
            [f"<{EX}i> <{EX}detail> ?node . OPTIONAL {{ ?node ?p ?v }}"],
        ),
        "a service layer's stored node of a holder",
    ),
    Shape(
        "interfaces: superproperties",
        _select(
            ["?sub", "?sup"],
            [
                f"VALUES ?start {{ <{EX}hasSpecialPart> }}",
                f"?start <{RDFS}subPropertyOf>* ?sub .",
                f"?sub <{RDFS}subPropertyOf> ?sup .",
                "FILTER(?sub != ?sup && isIRI(?sup))",
            ],
        ),
        "a mapper's superproperty walk",
    ),
    Shape(
        "classes of an instance",
        _select(
            ["?class"],
            [f"?class <{RDF}type> <{OWL}Class> .", f"<{EX}i> <{RDF}type> ?class ."],
        ),
        "interface `owl_get_classes_of_individual` (explicit only by default)",
    ),
    Shape(
        "subject triples, named graph (FROM)",
        _select(["?p", "?o"], [f"<{EX}g> ?p ?o ."], named_graph=GRAPH),
        "interface `triples_get(named_graph=...)`, as a service layer calls it",
    ),
    Shape(
        "ASK, default graph, asserted triple",
        _ask([f"<{EX}i> <{EX}hasSpecialPart> <{EX}j> ."]),
        "interface `iri_exists`, `triple_exists`",
    ),
    Shape(
        "ASK, default graph, inferred triple",
        _ask([f"<{EX}j> <{EX}partOf> <{EX}i> ."]),
        "interface `iri_exists`, `triple_exists`",
    ),
    Shape(
        "ASK, named graph (GRAPH), asserted triple",
        _ask([f"<{EX}g> <{EX}hasSpecialPart> <{EX}h> ."], named_graph=GRAPH),
        "interface `iri_exists(named_graph=...)`; the pseudo variant has FROM and no "
        "FROM NAMED, so a difference may be that clash, not inference",
    ),
    Shape(
        "ASK, named graph (GRAPH), inferred triple",
        _ask([f"<{EX}g> a <{EX}Super> ."], named_graph=GRAPH),
        "interface `iri_exists(named_graph=...)`; the pseudo variant has FROM and no "
        "FROM NAMED, so a difference may be that clash, not inference",
    ),
]


def _rows(answer) -> Counter:
    """The rows of a raw SELECT answer as a multiset, or the boolean of an ASK.

    Raw, so that a datatype or a language counts. Blank-node labels are kept: GraphDB answers
    the same label for a stored blank node in every request.
    """
    if "boolean" in answer:
        return Counter([("boolean", answer["boolean"])])
    return Counter(
        tuple(
            sorted(
                (
                    name,
                    term["type"],
                    term["value"],
                    term.get("datatype", ""),
                    term.get("xml:lang", ""),
                )
                for name, term in binding.items()
            )
        )
        for binding in answer["results"]["bindings"]
    )


@dataclass
class Measured:
    """The rows of the three variants of one shape, through one adapter."""

    adapter: str
    shape: Shape
    pseudo: Counter
    infer_false: Counter
    control: Counter

    @property
    def equal(self) -> bool:
        return self.pseudo == self.infer_false

    @property
    def inference_visible(self) -> bool:
        return self.control != self.pseudo

    def verdict(self) -> str:
        if not self.equal:
            if _unlabelled(self.pseudo) == _unlabelled(self.infer_false):
                return "equal up to blank-node labels"
            return "**different**"
        if not self.inference_visible:
            return "equal, no inference visible"
        return "equal"

    def difference(self) -> str:
        """The rows of one variant only, each group tagged with whether the control has it.

        A pseudo row that the control lacks lies outside the open scope's dataset: the
        pseudo-graph widened the scope (a defect of the rendering, not of `infer=false`).
        An `infer=false` row that pseudo lacks but the control has may be an inferred row.
        """
        parts = []
        for name, only in (
            ("only pseudo", self.pseudo - self.infer_false),
            ("only infer=false", self.infer_false - self.pseudo),
        ):
            in_control = only & self.control
            outside = only - self.control
            if in_control:
                parts.append(f"{name}, in control: {_brief(in_control)}")
            if outside:
                parts.append(f"{name}, not in control (wider scope): {_brief(outside)}")
        return "; ".join(parts)


def _unlabelled(rows: Counter) -> Counter:
    """`rows` with every blank-node label replaced by one placeholder."""
    return Counter(
        {
            tuple(
                (
                    (term[0], term[1], "_:", *term[3:])
                    if len(term) == 5 and term[1] == "bnode"
                    else term
                )
                for term in row
            ): count
            for row, count in rows.items()
        }
    )


def _brief(rows: Counter) -> str:
    def term(row):
        if row and row[0] == "boolean":
            return str(row[1])
        return "(" + ", ".join(f"{name}={value}" for name, _, value, _, _ in row) + ")"

    return ", ".join(term(row) for row in rows.elements())


def table(results: list[Measured]) -> str:
    """The result table in Markdown, one row per adapter and shape."""
    lines = [
        "| Adapter | Read shape | Verdict | Rows pseudo / infer=false / control | Differing rows | Source |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        counts = " / ".join(
            (
                str(sum(rows.values()))
                if not any(r[0] == "boolean" for r in rows)
                else str(next(iter(rows))[1])
            )
            for rows in (result.pseudo, result.infer_false, result.control)
        )
        lines.append(
            f"| {result.adapter} | {result.shape.name} | {result.verdict()} | {counts} "
            f"| {result.difference() or '-'} | {result.shape.source} |"
        )
    return "\n".join(lines)


def measure(store_query, adapter: str, shape: Shape) -> Measured:
    """The three variants of `shape`, sent through `store_query(text, infer)`."""
    pseudo = shape.build(False).to_string(validate=False)
    open_scope = shape.build(True).to_string(validate=False)
    assert "ontotext" not in open_scope
    return Measured(
        adapter=adapter,
        shape=shape,
        pseudo=_rows(store_query(pseudo, None)),
        infer_false=_rows(store_query(open_scope, False)),
        control=_rows(store_query(open_scope, None)),
    )


# --- The prototype flag, offline -----------------------------------------------------------


def test_the_prototype_sends_infer_false_as_a_request_parameter(
    store,
):  # pylint: disable=redefined-outer-name
    connected = connect(
        TripleStoreEndpoint(url=BASE_URL, dataset=DATASET),
        BasicAuth(USERNAME, PASSWORD),
    )

    connected._query(
        "ASK { ?s ?p ?o }", infer=False
    )  # pylint: disable=protected-access
    connected.query("ASK { ?s ?p ?o }")

    assert store.params[-2] == {"infer": "false"}
    assert store.params[-1] is None


def test_the_table_marks_a_difference_and_an_equality_without_inference():
    shape = SHAPES[0]
    row = (("o", "uri", EX + "x", "", ""),)
    differing = Measured("GraphDB", shape, Counter([row]), Counter(), Counter([row]))
    vacuous = Measured("GraphDB", shape, Counter([row]), Counter([row]), Counter([row]))

    text = table([differing, vacuous])

    assert "**different**" in text
    assert f"only pseudo, in control: (o={EX}x)" in text
    assert "equal, no inference visible" in text


def test_a_pseudo_row_outside_the_control_is_marked_as_a_wider_scope():
    row = (("o", "uri", EX + "x", "", ""),)
    widened = Measured("GraphDB", SHAPES[0], Counter([row]), Counter(), Counter())

    assert f"only pseudo, not in control (wider scope): (o={EX}x)" in table([widened])


def test_rows_that_differ_only_in_blank_node_labels_are_equal_up_to_labels():
    def node(label):
        return (("bnode", "bnode", label, "", ""), ("p", "uri", EX + "p", "", ""))

    relabelled = Measured(
        "GraphDB",
        SHAPES[0],
        Counter([node("a1")]),
        Counter([node("b7")]),
        Counter([node("a1"), node("a2")]),
    )

    assert relabelled.verdict() == "equal up to blank-node labels"


# --- The probe, live ------------------------------------------------------------------------

_RESULTS: list[Measured] = []


def _seed(write: Callable[[str], object]) -> None:
    write(f"INSERT DATA {{\n{ONTOLOGY}\n{INSTANCES}\n}}")
    write(f"INSERT DATA {{ GRAPH <{GRAPH}> {{\n{NAMED_INSTANCES}\n}} }}")


def _unseed(write: Callable[[str], object]) -> None:
    # The probe's subjects are in its namespace, or anonymous nodes at most three steps below
    # one of them (name, union, list, rest of the list).
    root = f'FILTER(STRSTARTS(STR(?r), "{EX}"))'
    write(
        f"""DELETE {{ ?s ?p ?o }} WHERE {{
  {{ ?s ?p ?o . FILTER(STRSTARTS(STR(?s), "{EX}")) }}
  UNION {{ ?r ?a ?s . ?s ?p ?o . {root} FILTER(isBlank(?s)) }}
  UNION {{ ?r ?a ?b1 . ?b1 ?b ?s . ?s ?p ?o . {root} FILTER(isBlank(?b1) && isBlank(?s)) }}
  UNION {{ ?r ?a ?b1 . ?b1 ?b ?b2 . ?b2 ?c ?s . ?s ?p ?o . {root}
          FILTER(isBlank(?b1) && isBlank(?b2) && isBlank(?s)) }}
}}"""
    )
    write(f"CLEAR SILENT GRAPH <{GRAPH}>")


@pytest.fixture(name="graphdb", scope="module")
def fixture_graphdb(db: GraphDB):
    ruleset = db.ruleset_get()
    if "rdfsplus-optimized" not in str(ruleset):
        pytest.skip(
            f"the probe needs the ruleset rdfsplus-optimized; the dataset has {ruleset}"
        )

    def write(text: str) -> None:
        db.query(text, update=True)

    _unseed(write)
    _seed(write)
    assert db.query(f"ASK {{ <{EX}i> a <{EX}Sub> }}")["boolean"], "the seed is missing"
    yield db
    _unseed(write)


def _report(result: Measured, request) -> None:
    _RESULTS.append(result)
    request.node.user_properties.append(("tsi56", table([result])))
    path = os.getenv("EXPLICIT_PROBE_REPORT")
    if path:
        Path(path).write_text(table(_RESULTS) + "\n", encoding="utf-8")
    print(table([result]))


@pytest.mark.live
@pytest.mark.parametrize("shape", SHAPES, ids=[shape.name for shape in SHAPES])
def test_graphdb_infer_false_against_the_explicit_pseudo_graph(graphdb, shape, request):
    def send(text: str, infer):
        return graphdb._query(text, infer=infer)  # pylint: disable=protected-access

    _report(measure(send, "GraphDB", shape), request)


def _kadi_store():
    names = (
        "EXPLICIT_PROBE_KADI_URL",
        "EXPLICIT_PROBE_KADI_DATASET",
        "EXPLICIT_PROBE_KADI_PAT",
    )
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        pytest.skip(
            "Kadi: not measured. It needs a Kadi instance, a disposable dataset on it, and a "
            f"personal access token with the read and write scopes; unset: {', '.join(missing)}"
        )
    return connect(
        TripleStoreEndpoint(
            url=os.environ["EXPLICIT_PROBE_KADI_URL"],
            dataset=os.environ["EXPLICIT_PROBE_KADI_DATASET"],
        ),
        KadiPATAuth(os.environ["EXPLICIT_PROBE_KADI_PAT"]),
    )


@pytest.fixture(name="kadi", scope="module")
def fixture_kadi():
    kadi = _kadi_store()

    def write(text: str) -> None:
        kadi.query(text, update=True)

    _unseed(write)
    _seed(write)
    yield kadi
    _unseed(write)


@pytest.mark.live
@pytest.mark.parametrize("shape", SHAPES, ids=[shape.name for shape in SHAPES])
def test_kadi_infer_false_against_the_explicit_pseudo_graph(kadi, shape, request):
    client = kadi._client  # pylint: disable=protected-access

    def send(text: str, infer):
        return client._query(text, infer=infer)  # pylint: disable=protected-access

    _report(measure(send, "Kadi", shape), request)
