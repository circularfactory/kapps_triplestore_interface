"""A clear that the store refuses raises, and names the repository and the graph.

Two halves, as in `test_shacl_validation_error.py`. The first sends recorded answers through
the client, so it runs without a store. The second loads a shape into a live store and makes the
store refuse a clear. That needs a repository with SHACL validation. The development CI
provisions one.
"""

import logging

import pytest
import requests

from kapps_triplestore_interface import (
    GraphDB,
    GraphDBCredentials,
    ShaclValidationError,
)
from kapps_triplestore_interface.exceptions import (
    TripleStoreInterfaceError,
    TripleStoreResponseError,
)

# GraphDB 10.8.5's answer (KIT, 2026-10-04) to a clear of a named graph that held the only
# value of a `sh:minCount 1` path.
RECORDED_MEDIA_TYPE = "application/shacl-validation-report+n-quads;charset=UTF-8"
RECORDED_REPORT = """\
_:84a87a1d504944d8a6a3c3a2ad43a4ca31154579 <http://www.w3.org/ns/shacl#conforms> "false"^^<http://www.w3.org/2001/XMLSchema#boolean> .
_:84a87a1d504944d8a6a3c3a2ad43a4ca31154579 <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/ns/shacl#ValidationReport> .
_:84a87a1d504944d8a6a3c3a2ad43a4ca31154579 <http://rdf4j.org/schema/rdf4j#truncated> "false"^^<http://www.w3.org/2001/XMLSchema#boolean> .
_:84a87a1d504944d8a6a3c3a2ad43a4ca31154579 <http://www.w3.org/ns/shacl#result> _:84a87a1d504944d8a6a3c3a2ad43a4ca31154580 .
_:84a87a1d504944d8a6a3c3a2ad43a4ca31154580 <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/ns/shacl#ValidationResult> .
_:84a87a1d504944d8a6a3c3a2ad43a4ca31154580 <http://www.w3.org/ns/shacl#focusNode> <http://example.org/clear-refusal#thing> .
_:84a87a1d504944d8a6a3c3a2ad43a4ca31154580 <http://rdf4j.org/shacl-extensions#shapesGraph> <http://rdf4j.org/schema/rdf4j#SHACLShapeGraph> .
_:84a87a1d504944d8a6a3c3a2ad43a4ca31154580 <http://www.w3.org/ns/shacl#resultPath> <http://example.org/clear-refusal#part> .
_:84a87a1d504944d8a6a3c3a2ad43a4ca31154580 <http://www.w3.org/ns/shacl#sourceConstraintComponent> <http://www.w3.org/ns/shacl#MinCountConstraintComponent> .
_:84a87a1d504944d8a6a3c3a2ad43a4ca31154580 <http://www.w3.org/ns/shacl#resultSeverity> <http://www.w3.org/ns/shacl#Violation> .
<http://example.org/clear-refusal#ThingPartShape> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/ns/shacl#PropertyShape> .
_:84a87a1d504944d8a6a3c3a2ad43a4ca31154580 <http://www.w3.org/ns/shacl#sourceShape> <http://example.org/clear-refusal#ThingPartShape> .
<http://example.org/clear-refusal#ThingPartShape> <http://www.w3.org/ns/shacl#path> <http://example.org/clear-refusal#part> .
<http://example.org/clear-refusal#ThingPartShape> <http://www.w3.org/ns/shacl#minCount> "1"^^<http://www.w3.org/2001/XMLSchema#integer> .
"""

EX = "http://example.org/clear-refusal#"
PARTS = f"{EX}parts"
GRAPH_STORE = "repositories/repo/rdf-graphs/service"


def _response(status: int, media_type: str | None, body: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    if media_type is not None:
        response.headers["Content-Type"] = media_type
    response._content = body.encode("utf-8")
    response.encoding = "utf-8"
    return response


@pytest.fixture
def clears() -> list:
    """The clears that the client of `answering` sent: endpoint and query parameters."""
    return []


@pytest.fixture
def answering(monkeypatch, clears):
    """A client whose store answers every clear with the response passed to the fixture.

    The login and the list of repositories answer as GraphDB does. Nothing reaches a network.
    """

    def client(clear_answer: requests.Response) -> GraphDB:
        def make_request(self, method, endpoint, timeout=None, **kwargs):
            if endpoint == "rest/login":
                answer = _response(200, "application/json", "")
                answer.headers["Authorization"] = "GDB token"
                return answer
            if endpoint == "rest/repositories":
                return _response(200, "application/json", '[{"id": "repo"}]')
            if method == "delete" and endpoint.startswith(GRAPH_STORE):
                clears.append((endpoint, kwargs.get("params")))
                return clear_answer
            raise AssertionError(f"unexpected request: {method} {endpoint}")

        monkeypatch.setattr(GraphDB, "_make_request", make_request)
        return GraphDB(
            GraphDBCredentials(
                base_url="http://example.org",
                username="user",
                password="password",
                repository="repo",
            )
        )

    return client


def test_a_recorded_refusal_raises_the_shacl_type_with_the_report_verbatim(answering):
    db = answering(_response(500, RECORDED_MEDIA_TYPE, RECORDED_REPORT))

    with pytest.raises(ShaclValidationError) as refused:
        db.graph_clear(PARTS)

    assert refused.value.report == RECORDED_REPORT
    assert str(refused.value) == (
        f"Failed to clear graph <{PARTS}> in repository 'repo' (500) - {RECORDED_REPORT}"
    )
    assert isinstance(refused.value, TripleStoreResponseError)
    assert isinstance(refused.value, TripleStoreInterfaceError)


def test_a_refusal_logs_the_report_at_debug_and_nothing_louder(answering, caplog):
    db = answering(_response(500, RECORDED_MEDIA_TYPE, RECORDED_REPORT))
    # The client logs at INFO when it is built. Only the records of the clear count.
    caplog.clear()

    with caplog.at_level(logging.DEBUG), pytest.raises(ShaclValidationError):
        db.graph_clear(PARTS)

    assert [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.levelno >= logging.INFO
    ] == []
    assert [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG and RECORDED_REPORT in record.getMessage()
    ] == [
        f"Failed to clear graph <{PARTS}> in repository 'repo' (500) - {RECORDED_REPORT}"
    ]


# GraphDB 10.8.5's answer (KIT, 2026-10-04) to a clear of the default graph under a shape
# with `sh:minCount` on a sequence path with an inverse step.
# The store fails while it validates. Its answer is not a validation report.
INTERNAL_ERROR = """\
Internal error while trying to validate SHACL Shape http://example.org/clear-refusal#S
<http://example.org/clear-refusal#S> a sh:PropertyShape;
  sh:targetClass <http://example.org/clear-refusal#Box>;
  sh:path (<http://example.org/cfc#hasPossessedWorkpiece> [
        sh:inversePath <http://example.org/cfc#hasPossessor>
      ]);
  sh:minCount 1 ."""


# Each error answer that is not a refusal.
EACH_OTHER_ERROR_ANSWER = pytest.mark.parametrize(
    ("graph", "target", "status", "media_type", "body"),
    [
        (None, "the default graph", 500, "text/plain;charset=UTF-8", INTERNAL_ERROR),
        (
            PARTS,
            f"graph <{PARTS}>",
            503,
            "text/html",
            "<html>Service Unavailable</html>",
        ),
        (PARTS, f"graph <{PARTS}>", 404, None, ""),
    ],
    ids=["store-fails-while-validating", "unavailable", "no-media-type"],
)


@EACH_OTHER_ERROR_ANSWER
def test_every_other_error_answer_raises_the_general_type(
    answering, graph, target, status, media_type, body
):
    db = answering(_response(status, media_type, body))

    with pytest.raises(TripleStoreResponseError) as failed:
        db.graph_clear(graph)

    assert type(failed.value) is TripleStoreResponseError
    assert failed.value.status == status
    assert str(failed.value) == (
        f"Failed to clear {target} in repository 'repo' ({status}) - {body}"
    )


@EACH_OTHER_ERROR_ANSWER
def test_every_other_error_answer_logs_at_error(
    answering, caplog, graph, target, status, media_type, body
):
    db = answering(_response(status, media_type, body))
    # The client logs at INFO when it is built. Only the records of the clear count.
    caplog.clear()

    with caplog.at_level(logging.DEBUG), pytest.raises(TripleStoreResponseError):
        db.graph_clear(graph)

    assert [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.levelno >= logging.INFO
    ] == [
        ("ERROR", f"Failed to clear {target} in repository 'repo' ({status}) - {body}")
    ]


@pytest.mark.parametrize(
    ("graph", "endpoint", "params"),
    [
        (PARTS, GRAPH_STORE, {"graph": PARTS}),
        (None, f"{GRAPH_STORE}?default", None),
    ],
    ids=["named-graph", "default-graph"],
)
def test_a_clear_the_store_accepts_returns_true(
    answering, clears, graph, endpoint, params
):
    db = answering(_response(204, None, ""))

    assert db.graph_clear(graph) is True
    assert clears == [(endpoint, params)]


# The live half. The shape's target class occurs in no other test, so a shape left behind by
# an interrupted run refuses nothing that another test writes.
THING, PART, ONE = (f"{EX}{name}" for name in ("thing", "part", "one"))


def _shape(operation: str) -> str:
    """`INSERT DATA` or `DELETE DATA` of a shape that requires a thing to have a part.

    The store reads its shapes from this graph. SPARQL cannot match triples in it, so the
    shape is removed by its own triples, and no other shape is touched.
    """
    return f"""
PREFIX sh: <http://www.w3.org/ns/shacl#>
{operation} DATA {{ GRAPH <http://rdf4j.org/schema/rdf4j#SHACLShapeGraph> {{
    <{EX}ThingShape> a sh:NodeShape ;
        sh:targetClass <{EX}Thing> ;
        sh:property <{EX}ThingPartShape> .
    <{EX}ThingPartShape> sh:path <{PART}> ; sh:minCount 1 .
}} }}
"""


@pytest.fixture
def part_in_its_own_graph(db: GraphDB):
    """A thing that must have a part. Its type is in the default graph, its part in `PARTS`."""
    db.query(_shape("INSERT"), update=True)
    try:
        db.query(
            f"INSERT DATA {{ <{THING}> a <{EX}Thing> ."
            f" GRAPH <{PARTS}> {{ <{THING}> <{PART}> <{ONE}> . }} }}",
            update=True,
        )
        yield
    finally:
        # The type first: once the thing is no shape's target, its part can go.
        db.query(f"DELETE DATA {{ <{THING}> a <{EX}Thing> . }}", update=True)
        db.query(f"CLEAR SILENT GRAPH <{PARTS}>", update=True)
        db.query(_shape("DELETE"), update=True)


def test_a_live_refusal_raises_the_shacl_type_and_clears_nothing(
    db: GraphDB, part_in_its_own_graph
):
    with pytest.raises(ShaclValidationError) as refused:
        db.graph_clear(PARTS)

    report = refused.value.report
    assert "<http://www.w3.org/ns/shacl#ValidationReport>" in report
    assert f"<http://www.w3.org/ns/shacl#focusNode> <{THING}>" in report
    assert f"<http://www.w3.org/ns/shacl#resultPath> <{PART}>" in report
    assert str(refused.value).startswith(
        f"Failed to clear graph <{PARTS}> in repository '{db.dataset}' (500) - "
    )
    parts = db.graph_get(PARTS)
    assert parts is not None and len(parts) == 1
