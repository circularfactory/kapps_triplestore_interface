from kapps_triplestore_interface.utils import utils
from kapps_triplestore_interface.exceptions import (
    InvalidIRIError,
    InvalidInputError,
    InvalidQueryError,
)
from kapps_triplestore_interface.utils.iri import IRI
import pytest
from rdflib import BNode, Literal
import datetime


def test_sanitize_triple_iris():
    triple_three_iri = (
        IRI("http://example.org#subject"),
        IRI("http://example.org#predicate"),
        IRI("http://example.org#object"),
    )
    # Must not modify
    sanitized_triple = utils.sanitize_triple(triple_three_iri)
    assert sanitized_triple == triple_three_iri

    triple = (
        "http://example.org#subject",
        "http://example.org#predicate",
        "http://example.org#object",
    )
    # Must convert all three to IRI
    sanitized_triple = utils.sanitize_triple(triple)
    assert sanitized_triple == triple_three_iri


def test_sanitize_triple_bnodes():
    triple_bnode = (
        BNode("genid-123"),
        IRI("http://example.org#predicate"),
        BNode("genid-456"),
    )
    # Must not modify
    sanitized_triple = utils.sanitize_triple(triple_bnode)
    assert sanitized_triple == triple_bnode

    triple_bnode_string = (
        "_:genid-123",
        "http://example.org#predicate",
        "_:genid-456",
    )
    # Must convert to BNode, IRI
    sanitized_triple = utils.sanitize_triple(triple_bnode_string)
    assert sanitized_triple == triple_bnode

    triple = (
        IRI("http://example.org#subject"),
        BNode("genid-123"),
        IRI("http://example.org#object"),
    )
    # Predicate is BNode, is illegal
    with pytest.raises(InvalidIRIError):
        utils.sanitize_triple(triple)


def test_sanitize_triple_literals():
    triple_iri_literal_string = (
        IRI("http://example.org#subject"),
        IRI("http://example.org#predicate"),
        Literal("literal_object"),
    )
    # Must not modify
    sanitized_triple = utils.sanitize_triple(triple_iri_literal_string)
    assert sanitized_triple == triple_iri_literal_string

    triple_iri_literal_number = (
        IRI("http://example.org#subject"),
        IRI("http://example.org#predicate"),
        Literal(2.0),
    )
    # Must not modify reference triple
    sanitized_triple = utils.sanitize_triple(triple_iri_literal_number)
    assert sanitized_triple == triple_iri_literal_number

    triple = (
        IRI("http://example.org#subject"),
        IRI("http://example.org#predicate"),
        2.0,
    )
    # Must convert python type to Literal
    sanitized_triple = utils.sanitize_triple(triple)
    assert sanitized_triple == triple_iri_literal_number

    triple = (
        "http://example.org#subject",
        "http://example.org#predicate",
        "literal_object",
    )
    # Object str cannot be converted to IRI
    with pytest.raises(InvalidIRIError):
        utils.sanitize_triple(triple)

    triple = (
        IRI("http://example.org#subject"),
        "not_an_iri",
        IRI("http://example.org#object"),
    )
    # second element not convertible to IRI
    with pytest.raises(InvalidIRIError):
        utils.sanitize_triple(triple)

    triple = (
        Literal("http://example.org#subject"),
        IRI("http://example.org#predicate"),
        IRI("http://example.org#object"),
    )
    # Subject is Literal, is illegal
    with pytest.raises(TypeError):
        utils.sanitize_triple(triple)

    triple = (
        IRI("http://example.org#subject"),
        Literal("http://example.org#predicate"),
        IRI("http://example.org#object"),
    )
    # Predicate is Literal, is illegal
    with pytest.raises(TypeError):
        utils.sanitize_triple(triple)


def test_sanitize_triple_partial():
    partial_triple_two_iri = (
        IRI("http://example.org#subject"),
        None,
        IRI("http://example.org#object"),
    )
    # Must not modify
    sanitized_triple = utils.sanitize_triple(partial_triple_two_iri, allow_partial=True)
    assert sanitized_triple == partial_triple_two_iri

    partial_triple_mixed = (
        "http://example.org#subject",
        None,
        IRI("http://example.org#object"),
    )
    # Must convert second str to IRI
    sanitized_triple = utils.sanitize_triple(partial_triple_mixed, allow_partial=True)
    assert sanitized_triple == partial_triple_two_iri

    partial_triple_iri_literal = (
        IRI("http://example.org#subject"),
        None,
        Literal("literal_string"),
    )
    # Must not modify
    sanitized_triple = utils.sanitize_triple(
        partial_triple_iri_literal, allow_partial=True
    )
    assert sanitized_triple == partial_triple_iri_literal

    partial_triple_iri_literal_number = (
        IRI("http://example.org#subject"),
        None,
        Literal(2.0),
    )
    # Must not modify
    sanitized_triple = utils.sanitize_triple(
        partial_triple_iri_literal_number, allow_partial=True
    )
    assert sanitized_triple == partial_triple_iri_literal_number

    partial_triple_iri_number = (
        IRI("http://example.org#subject"),
        None,
        2.0,
    )
    # Must convert python type to Literal
    sanitized_triple = utils.sanitize_triple(
        partial_triple_iri_number, allow_partial=True
    )
    assert sanitized_triple == partial_triple_iri_literal_number

    partial_triple_mixed = (
        IRI("http://example.org#subject"),
        None,
        "literal_string",
    )
    # Object str cannot be converted to IRI
    with pytest.raises(InvalidIRIError):
        utils.sanitize_triple(partial_triple_mixed, allow_partial=True)

    partial_triple_invalid = (
        IRI("http://example.org#subject"),
        Literal("http://example.org#predicate"),
        None,
    )
    with pytest.raises(TypeError):
        utils.sanitize_triple(partial_triple_invalid, allow_partial=True)

    partial_triple_two_entries = (
        IRI("http://example.org#subject"),
        IRI("http://example.org#predicate"),
    )
    # only 2 elements
    with pytest.raises(InvalidInputError):
        utils.sanitize_triple(partial_triple_two_entries)


def test_validate_query():
    valid_query = """
    SELECT *
    WHERE {
        ?s ?p ?o .
    }
    """
    invalid_query = """
    SELECT *
    WHERE {
        ?s ?p
    }
    """
    utils.validate_query(valid_query)
    with pytest.raises(InvalidQueryError):
        utils.validate_query(invalid_query)


def test_validate_update_query():
    valid_query = """
    DELETE DATA {
        GRAPH <http://example.org/named_graph> {
            <http://example.org#subject> <http://example.org#predicate> "object" .
        }
    }
    """
    invalid_query = """
    DELETE DATA {
        GRAPH <http://example.org/named_graph> {
            <http://example.org#subject> <http://example.org#predicate>
        }
    }
    """
    utils.validate_update_query(valid_query)
    with pytest.raises(InvalidQueryError):
        utils.validate_update_query(invalid_query)


def test_to_literal():
    literal_str = utils.to_literal(42, as_string=True)
    assert literal_str == '"42"^^<http://www.w3.org/2001/XMLSchema#integer>'

    literal_str = utils.to_literal(True, as_string=True)
    assert literal_str == '"true"^^<http://www.w3.org/2001/XMLSchema#boolean>'

    literal_str = utils.to_literal(42.5, as_string=True)
    assert literal_str == '"42.5"^^<http://www.w3.org/2001/XMLSchema#double>'

    literal_str = utils.to_literal("Hello", as_string=True)
    assert literal_str == '"Hello"^^<http://www.w3.org/2001/XMLSchema#string>'

    literal_str = utils.to_literal(False, as_string=True)
    assert literal_str == '"false"^^<http://www.w3.org/2001/XMLSchema#boolean>'

    literal_str = utils.to_literal(-123, as_string=True)
    assert literal_str == '"-123"^^<http://www.w3.org/2001/XMLSchema#integer>'

    literal_str = utils.to_literal(0.0, as_string=True)
    assert literal_str == '"0.0"^^<http://www.w3.org/2001/XMLSchema#double>'


def test_from_xsd_literal():
    value = utils.from_xsd_literal("42", "http://www.w3.org/2001/XMLSchema#integer")
    assert value == 42

    value = utils.from_xsd_literal("true", "http://www.w3.org/2001/XMLSchema#boolean")
    assert value is True

    value = utils.from_xsd_literal("42.5", "http://www.w3.org/2001/XMLSchema#float")
    assert value == 42.5

    value = utils.from_xsd_literal("42.5", "http://www.w3.org/2001/XMLSchema#double")
    assert value == 42.5

    value = utils.from_xsd_literal("Hello", "http://www.w3.org/2001/XMLSchema#string")
    assert value == "Hello"

    value = utils.from_xsd_literal("-123", "http://www.w3.org/2001/XMLSchema#integer")
    assert value == -123

    value = utils.from_xsd_literal("false", "http://www.w3.org/2001/XMLSchema#boolean")
    assert value is False

    value = utils.from_xsd_literal("0.0", "http://www.w3.org/2001/XMLSchema#double")
    assert value == 0.0

    value = utils.from_xsd_literal(
        "2023-01-01", "http://www.w3.org/2001/XMLSchema#date"
    )
    assert value == datetime.date(2023, 1, 1)

    value = utils.from_xsd_literal(
        "2023-01-01T12:34:56", "http://www.w3.org/2001/XMLSchema#dateTime"
    )
    assert value == datetime.datetime(2023, 1, 1, 12, 34, 56)


def test_convert_binding_to_python_type():
    result_dict = {"type": "uri", "value": "http://example.org#object2"}
    result_dict2 = {
        "datatype": "http://www.w3.org/2001/XMLSchema#double",
        "type": "literal",
        "value": "0.5",
    }
    converted_result = utils.convert_binding_to_python_type(result_dict)
    assert converted_result == "http://example.org#object2"
    converted_result = utils.convert_binding_to_python_type(result_dict2)
    assert converted_result == 0.5
    # TODO add more test cases here to catch last modification


def test_get_local_name():
    iri = "<http://example.org#subject>"
    local_name = utils.get_local_name(iri)
    assert local_name == "subject"

    iri = "http://example.org#predicate"
    local_name = utils.get_local_name(iri)
    assert local_name == "predicate"

    iri = "<http://example.org#object"
    local_name = utils.get_local_name(iri)
    assert local_name == "object"


def test_encapsulate_named_graph():
    named_graph_str = "<http://example.org/named_graph>"
    named_graph = IRI(named_graph_str)
    content = """SELECT *
    WHERE {
        ?s ?p ?o .
    }"""
    expected_result = f"""
GRAPH {named_graph_str} {{
    SELECT *
    WHERE {{
        ?s ?p ?o .
    }}
}}
"""
    result = utils.encapsulate_named_graph(named_graph, content)
    assert expected_result.strip() == result.strip()


# A datatype the map has no converter for: RDF allows any IRI, and the map does not cover
# all of XSD either. Reading one must not raise, and must not lose the datatype.
GMM_LITERAL = "http://example.org/ontology/uncertainty#gmmLiteral"
WKT_LITERAL = "http://www.opengis.net/ont/geosparql#wktLiteral"
GMM_VALUE = '{"n_components":1,"dimensions":1,"weights":[1.0],"means":[[25.0]]}'


@pytest.mark.parametrize(
    "value, datatype",
    [
        (GMM_VALUE, GMM_LITERAL),
        ("POINT(8.41 49.01)", WKT_LITERAL),
        ("2026-09-30T12:00:00Z", "http://www.w3.org/2001/XMLSchema#dateTimeStamp"),
    ],
    ids=["custom", "geosparql", "xsd-not-in-the-map"],
)
def test_from_xsd_literal_keeps_an_unknown_datatype(value, datatype):
    converted = utils.from_xsd_literal(value, datatype)
    assert converted == Literal(value, datatype=datatype)
    assert isinstance(converted, str)
    assert str(converted) == value


def test_convert_binding_to_python_type_with_an_unknown_datatype():
    binding = {"type": "literal", "value": "POINT(8.41 49.01)", "datatype": WKT_LITERAL}
    assert utils.convert_binding_to_python_type(binding) == Literal(
        "POINT(8.41 49.01)", datatype=WKT_LITERAL
    )

    # One such literal must leave the rest of its result set readable.
    bindings = [
        {"geometry": binding},
        {
            "geometry": {
                "type": "literal",
                "value": "0.62",
                "datatype": "http://www.w3.org/2001/XMLSchema#double",
            }
        },
    ]
    converted = utils.convert_multi_bindings_to_python_type(bindings)
    assert converted[1]["geometry"] == 0.62


def test_a_literal_with_an_unknown_datatype_writes_back_unchanged():
    # A plain str in the object position is read as an IRI, so a str fallback would raise
    # here. The Literal keeps its datatype through sanitize_triple.
    value = utils.from_xsd_literal(GMM_VALUE, GMM_LITERAL)
    _, _, obj = utils.sanitize_triple(
        ("http://example.org#subject", "http://example.org#predicate", value)
    )
    assert obj.n3() == Literal(GMM_VALUE, datatype=GMM_LITERAL).n3()


def test_group_triples_by_bnode_joins_two_groups():
    """One triple that touches the blank nodes of two existing groups joins them into one.

    The shape of an OWL list: the `rdf:first` cell and the restriction it points at are
    two groups until the triple that links them arrives.
    """
    a, b = BNode("a"), BNode("b")
    s, p = IRI("http://example.org#s"), IRI("http://example.org#p")
    first = (s, p, a)
    second = (b, p, IRI("http://example.org#o"))
    link = (a, p, b)
    independent = (s, p, IRI("http://example.org#other"))

    groups = utils.group_triples_by_bnode([first, second, independent, link])

    assert groups == [[first, second, link], [independent]]


def test_group_triples_by_bnode_joins_every_member():
    """Every member of an absorbed group follows it, not only the joining triple's nodes."""
    a, b, c = BNode("a"), BNode("b"), BNode("c")
    p = IRI("http://example.org#p")
    triples = [(a, p, c), (b, p, Literal(1)), (a, p, b), (c, p, Literal(2))]

    groups = utils.group_triples_by_bnode(triples)

    assert len(groups) == 1
    assert sorted(groups[0], key=str) == sorted(triples, key=str)


def test_group_triples_by_bnode_keeps_separate_groups_apart():
    a, b = BNode("a"), BNode("b")
    p = IRI("http://example.org#p")

    groups = utils.group_triples_by_bnode([(a, p, Literal(1)), (b, p, Literal(2))])

    assert groups == [[(a, p, Literal(1))], [(b, p, Literal(2))]]
