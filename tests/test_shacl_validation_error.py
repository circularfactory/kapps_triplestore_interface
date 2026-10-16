"""A write that the store's SHACL shapes refuse raises `ShaclValidationError`, with the report.

Two halves. The first sends a recorded answer through the client, so it runs without a store:
the answer is the one GraphDB 10.8.1 gave to a refused update, byte for byte. The second loads
a shape into a live store and makes the store refuse a write. That needs a repository with
SHACL validation. The development CI provisions one.
"""

import logging

import pytest
import requests

from kapps_triplestore_interface import GraphDB, GraphDBCredentials, ShaclValidationError
from kapps_triplestore_interface.exceptions import (
    TripleStoreInterfaceError,
    TripleStoreResponseError,
)
from kapps_triplestore_interface.queries.checked_write import RECEIPT_GRAPH

# GraphDB 10.8.1's answer to an update that a `sh:maxCount 1` shape refused.
RECORDED_MEDIA_TYPE = "application/shacl-validation-report+n-quads;charset=UTF-8"
RECORDED_REPORT = """\
_:987cde96ac59436c9b9161a1bcf448af1236 <http://www.w3.org/ns/shacl#conforms> "false"^^<http://www.w3.org/2001/XMLSchema#boolean> .
_:987cde96ac59436c9b9161a1bcf448af1236 <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/ns/shacl#ValidationReport> .
_:987cde96ac59436c9b9161a1bcf448af1236 <http://rdf4j.org/schema/rdf4j#truncated> "false"^^<http://www.w3.org/2001/XMLSchema#boolean> .
_:987cde96ac59436c9b9161a1bcf448af1236 <http://www.w3.org/ns/shacl#result> _:987cde96ac59436c9b9161a1bcf448af1237 .
_:987cde96ac59436c9b9161a1bcf448af1237 <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/ns/shacl#ValidationResult> .
_:987cde96ac59436c9b9161a1bcf448af1237 <http://www.w3.org/ns/shacl#focusNode> <http://example.org/shacl-refusal#thing> .
_:987cde96ac59436c9b9161a1bcf448af1237 <http://rdf4j.org/shacl-extensions#shapesGraph> <http://rdf4j.org/schema/rdf4j#SHACLShapeGraph> .
_:987cde96ac59436c9b9161a1bcf448af1237 <http://www.w3.org/ns/shacl#resultPath> <http://example.org/shacl-refusal#part> .
_:987cde96ac59436c9b9161a1bcf448af1237 <http://www.w3.org/ns/shacl#sourceConstraintComponent> <http://www.w3.org/ns/shacl#MaxCountConstraintComponent> .
_:987cde96ac59436c9b9161a1bcf448af1237 <http://www.w3.org/ns/shacl#resultSeverity> <http://www.w3.org/ns/shacl#Violation> .
<http://example.org/shacl-refusal#ThingPartShape> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/ns/shacl#PropertyShape> .
_:987cde96ac59436c9b9161a1bcf448af1237 <http://www.w3.org/ns/shacl#sourceShape> <http://example.org/shacl-refusal#ThingPartShape> .
<http://example.org/shacl-refusal#ThingPartShape> <http://www.w3.org/ns/shacl#path> <http://example.org/shacl-refusal#part> .
<http://example.org/shacl-refusal#ThingPartShape> <http://www.w3.org/ns/shacl#maxCount> "1"^^<http://www.w3.org/2001/XMLSchema#integer> .
"""

UPDATE = "INSERT DATA { <http://example.org/shacl-refusal#thing> <http://example.org/shacl-refusal#part> <http://example.org/shacl-refusal#two> . }"


def _response(status: int, media_type: str, body: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = media_type
    response._content = body.encode("utf-8")
    response.encoding = "utf-8"
    return response


@pytest.fixture
def answering(monkeypatch):
    """A client whose store answers every update with the response passed to the fixture.

    The login and the list of repositories answer as GraphDB does. Nothing reaches a network.
    """

    def client(update_answer: requests.Response) -> GraphDB:
        def make_request(self, method, endpoint, timeout=None, **kwargs):
            if endpoint == "rest/login":
                answer = _response(200, "application/json", "")
                answer.headers["Authorization"] = "GDB token"
                return answer
            if endpoint == "rest/repositories":
                return _response(200, "application/json", '[{"id": "repo"}]')
            if endpoint == "repositories/repo/statements":
                return update_answer
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


def test_a_recorded_refusal_raises_the_type_with_the_report_verbatim(answering):
    db = answering(_response(500, RECORDED_MEDIA_TYPE, RECORDED_REPORT))

    with pytest.raises(ShaclValidationError) as refused:
        db.query(UPDATE, update=True)

    assert refused.value.report == RECORDED_REPORT
    # The message keeps the form that every other store error has, so a caller that reads
    # the text keeps working.
    assert str(refused.value) == f"Error while querying GraphDB (500) - {RECORDED_REPORT}"
    assert isinstance(refused.value, TripleStoreResponseError)
    assert isinstance(refused.value, TripleStoreInterfaceError)


def test_a_refusal_logs_the_report_at_debug_and_nothing_louder(answering, caplog):
    db = answering(_response(500, RECORDED_MEDIA_TYPE, RECORDED_REPORT))
    # The client logs at INFO when it is built. Only the records of the query count.
    caplog.clear()

    with caplog.at_level(logging.DEBUG), pytest.raises(ShaclValidationError):
        db.query(UPDATE, update=True)

    assert [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.levelno >= logging.INFO
    ] == []
    assert [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG and RECORDED_REPORT in record.getMessage()
    ] == [f"Error while querying GraphDB (500) - {RECORDED_REPORT}"]


# Each error answer that is not a refusal.
EACH_OTHER_ERROR_STATUS = pytest.mark.parametrize(
    ("status", "media_type", "body"),
    [
        (
            400,
            "text/plain;charset=UTF-8",
            "MALFORMED QUERY: Lexical error at line 1, column 63.  Encountered: <EOF>",
        ),
        (500, "text/plain;charset=UTF-8", "Unknown error"),
        (503, "text/html", "<html>Service Unavailable</html>"),
    ],
    ids=["malformed-update", "server-error", "unavailable"],
)


@EACH_OTHER_ERROR_STATUS
def test_every_other_error_status_raises_the_general_type(
    answering, status, media_type, body
):
    db = answering(_response(status, media_type, body))

    with pytest.raises(TripleStoreResponseError) as failed:
        db.query(UPDATE, update=True)

    assert type(failed.value) is TripleStoreResponseError
    assert failed.value.status == status
    assert str(failed.value) == f"Error while querying GraphDB ({status}) - {body}"


@EACH_OTHER_ERROR_STATUS
def test_every_other_error_status_still_logs_at_error(
    answering, caplog, status, media_type, body
):
    db = answering(_response(status, media_type, body))
    # The client logs at INFO when it is built. Only the records of the query count.
    caplog.clear()

    with caplog.at_level(logging.DEBUG), pytest.raises(TripleStoreResponseError):
        db.query(UPDATE, update=True)

    assert [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.levelno >= logging.INFO
    ] == [("ERROR", f"Error while querying GraphDB ({status}) - {body}")]


# The live half. The shape's target class occurs in no other test, so a shape left behind by
# an interrupted run refuses nothing that another test writes.
EX = "http://example.org/shacl-refusal#"
THING, PART, ONE, TWO = (f"{EX}{name}" for name in ("thing", "part", "one", "two"))
def _shape(operation: str) -> str:
    """`INSERT DATA` or `DELETE DATA` of the shape.

    The store reads its shapes from this graph. SPARQL cannot match triples in it, so the
    shape is removed by its own triples, and no other shape is touched.
    """
    return f"""
PREFIX sh: <http://www.w3.org/ns/shacl#>
{operation} DATA {{ GRAPH <http://rdf4j.org/schema/rdf4j#SHACLShapeGraph> {{
    <{EX}ThingShape> a sh:NodeShape ;
        sh:targetClass <{EX}Thing> ;
        sh:property <{EX}ThingPartShape> .
    <{EX}ThingPartShape> sh:path <{PART}> ; sh:maxCount 1 .
}} }}
"""


@pytest.fixture
def at_most_one_part(db: GraphDB):
    """A shape that lets a thing hold at most one part, and a thing that holds one."""
    db.query(_shape("INSERT"), update=True)
    try:
        db.query(
            f"INSERT DATA {{ <{THING}> a <{EX}Thing> ; <{PART}> <{ONE}> . }}",
            update=True,
        )
        yield
    finally:
        db.query(f"DELETE WHERE {{ <{THING}> ?p ?o . }}", update=True)
        db.query(_shape("DELETE"), update=True)


def test_a_live_refusal_raises_the_type_and_writes_nothing(db: GraphDB, at_most_one_part):
    with pytest.raises(ShaclValidationError) as refused:
        db.query(f"INSERT DATA {{ <{THING}> <{PART}> <{TWO}> . }}", update=True)

    report = refused.value.report
    assert "<http://www.w3.org/ns/shacl#ValidationReport>" in report
    assert f"<http://www.w3.org/ns/shacl#focusNode> <{THING}>" in report
    assert f"<http://www.w3.org/ns/shacl#resultPath> <{PART}>" in report
    assert str(refused.value).endswith(report)
    assert not db.query(f"ASK {{ <{THING}> <{PART}> <{TWO}> }}")["boolean"]


def test_a_live_write_that_conforms_is_not_refused(db: GraphDB, at_most_one_part):
    assert db.query(
        f"INSERT DATA {{ <{EX}other> a <{EX}Thing> ; <{PART}> <{TWO}> . }}",
        update=True,
    )
    db.query(f"DELETE WHERE {{ <{EX}other> ?p ?o . }}", update=True)


def _receipts(db: GraphDB) -> int:
    answer = db.query(
        f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{RECEIPT_GRAPH}> {{ ?s ?p ?o }} }}"
    )
    return int(answer["results"]["bindings"][0]["n"]["value"])


def test_a_live_refusal_of_a_checked_write_raises_the_type_and_leaves_no_receipt(
    db: GraphDB, at_most_one_part
):
    """The receipt travels in the refused update, so the store commits neither."""
    receipts_before = _receipts(db)

    with pytest.raises(ShaclValidationError):
        db.triples_add([(THING, PART, TWO)], check_exist=True)

    assert not db.query(f"ASK {{ <{THING}> <{PART}> <{TWO}> }}")["boolean"]
    assert _receipts(db) == receipts_before
