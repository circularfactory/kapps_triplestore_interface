"""What the store does with a SHACL-SPARQL constraint: at commit, and in whole-dataset validation.

MEASUREMENT RECORD.

One SHACL-SPARQL node shape with a class target (a parent's child must be registered as a
child) and four cases. P1 to P3 each write something that violates the shape and record
whether the store refused the write at commit. P4 puts an admitted violation into the dataset
and validates the whole dataset against the same shape with `GraphDB.validate`. Only P4
asserts; P1 to P3 pass when the store refuses and skip, with the outcome in the message, when
it admits the write.

- Store: GraphDB 10.8.5 enterprise (RDF4J 4.3.15), SHACL validation on.
- P1, a new focus node with a violating property in one INSERT: REFUSED at commit
  (`ShaclValidationError`; the report names `ex:ParentHasChildShape` as `sh:sourceShape` and
  `ex:nobody` as `sh:value`).
- P2, a violating property added to an existing focus node: ADMITTED at commit.
- P3, the violation caused by a DELETE on another node: ADMITTED at commit.
- P4, whole-dataset validation of an admitted violation: the report has `sh:conforms false`
  with one result: focus node `ex:p1`, value `ex:nobody`, `sh:SPARQLConstraintComponent`,
  source shape `ex:ParentHasChildShape`.

What this means for a rule enforced at commit: a SHACL-SPARQL constraint on a class target
is enforced at commit only where the write creates the focus node together with the violating
data. A later change to an existing node, or a change on another node that causes the
violation, is admitted, and only whole-dataset validation finds it. A rule that must refuse
such a change cannot rely on a class-targeted SPARQL constraint; it needs a shape whose
constraint the store evaluates at commit on every change (for example SHACL Core), or a
validation of the whole dataset that the caller runs and reads.

Every outcome is also recorded with pytest's `record_property` (`-v -rs` shows the skip
messages). Every test leaves the dataset with no shapes and without the data that it wrote.
"""

# pytest passes the fixtures by name.
# pylint: disable=redefined-outer-name,unused-argument,protected-access

from __future__ import annotations

import pytest

from kapps_triplestore_interface import GraphDB, ShaclValidationError

EX = "http://example.org/probe#"

SH = "http://www.w3.org/ns/shacl#"

# Full IRIs and no prefix declaration, so that loading the shapes adds no prefix to the dataset.
SHAPES = f"""\
<{EX}ParentHasChildShape> a <{SH}NodeShape> ;
    <{SH}targetClass> <{EX}Parent> ;
    <{SH}sparql> [ a <{SH}SPARQLConstraint> ;
        <{SH}message> "A parent names a child that is not registered as a child." ;
        <{SH}select> \"\"\"SELECT $this ?value WHERE {{
            $this <{EX}hasChild> ?value .
            FILTER NOT EXISTS {{ ?value a <{EX}Child> }} }}\"\"\" ] .
"""

PREFIX = f"PREFIX ex: <{EX}>\n"
SUBJECTS = ("p1", "p2", "p3", "c3", "nobody")


def _update(db: GraphDB, body: str) -> None:
    db.query(f"{PREFIX}{body}", update=True)


def _store_version(db: GraphDB) -> str:
    """The store's version from its REST description, or 'unknown'."""
    try:
        answer = db._make_request("get", "rest/info/version")
        data = answer.json()
        return str(data.get("productVersion") or data.get("version") or data)
    except Exception:  # pylint: disable=broad-except
        return "unknown"


@pytest.fixture
def probe(db: GraphDB):
    """Set the probe shape; afterwards clear the shapes first, then the data."""
    db.shapes_set(SHAPES, "text/turtle")
    try:
        yield db
    finally:
        db.shapes_set("", "text/turtle")
        for name in SUBJECTS:
            _update(db, f"DELETE WHERE {{ ex:{name} ?p ?o }}")
            _update(db, f"DELETE WHERE {{ ?s ?p ex:{name} }}")


def _refused_or_skip(record_property, db: GraphDB, case: str, steps: list[str]) -> str:
    """Run the steps; return the refusal's report, or skip when the store admits the last one."""
    version = _store_version(db)
    record_property("store_version", version)
    for step in steps[:-1]:
        _update(db, step)
    try:
        _update(db, steps[-1])
    except ShaclValidationError as refusal:
        record_property(f"{case}_outcome", "refused")
        print(f"{case}: refused at commit on {version}")
        return refusal.report
    record_property(f"{case}_outcome", "admitted")
    print(f"{case}: admitted at commit on {version}")
    pytest.skip(
        f"admitted at commit on GraphDB {version}: the constraint is not enforced for this write"
    )
    return ""


def test_p1_new_focus_node_with_a_violating_property(probe, record_property):
    report = _refused_or_skip(
        record_property,
        probe,
        "P1",
        ["INSERT DATA { ex:p1 a ex:Parent ; ex:hasChild ex:nobody }"],
    )
    assert f"{EX}ParentHasChildShape" in report
    assert f"{EX}nobody" in report


def test_p2_violating_property_added_to_an_existing_focus_node(probe, record_property):
    _refused_or_skip(
        record_property,
        probe,
        "P2",
        [
            "INSERT DATA { ex:p2 a ex:Parent }",
            "INSERT DATA { ex:p2 ex:hasChild ex:nobody }",
        ],
    )


def test_p3_violation_caused_by_a_change_on_another_node(probe, record_property):
    _refused_or_skip(
        record_property,
        probe,
        "P3",
        [
            "INSERT DATA { ex:p3 a ex:Parent ; ex:hasChild ex:c3 . ex:c3 a ex:Child }",
            "DELETE DATA { ex:c3 a ex:Child }",
        ],
    )


def test_p4_whole_dataset_validation_reports_the_violation(
    db: GraphDB, record_property
):
    version = _store_version(db)
    record_property("store_version", version)
    # With the shapes cleared the store admits the violation whatever it does at commit.
    db.shapes_set("", "text/turtle")
    try:
        _update(db, "INSERT DATA { ex:p1 a ex:Parent ; ex:hasChild ex:nobody }")
        report = db.validate(SHAPES, "text/turtle")
    finally:
        _update(db, "DELETE WHERE { ex:p1 ?p ?o }")
    record_property("P4_report", report)
    print(f"P4 report on {version}:\n{report}")
    assert "conforms" in report and "false" in report
    assert f"{EX}ParentHasChildShape" in report
    assert f"{EX}nobody" in report
