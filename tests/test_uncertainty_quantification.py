"""The uncertainty quantification datatypes through the interface's read and write paths."""

import json
import pickle

import pytest
from rdflib import Graph, Literal, URIRef, XSD

from kapps_triplestore_interface.utils.UncertaintyQuantification import (
    UQ_PFX,
    DirichletLiteral,
    GaussianMixtureLiteral,
    HistogramLiteral,
    NonNegativeDouble,
)
from kapps_triplestore_interface.utils.utils import (
    convert_binding_to_python_type,
    from_xsd_literal,
    sanitize_triple,
    triple_to_string,
    validate_update_query,
)

GMM = (
    '{"n_components": 2, "dimensions": 1, "covariance_type": "diag", "weights": [0.4, 0.6], '
    '"means": [[5.0], [8.0]], "covariances": [[4.0], [3.2]]}'
)
HISTOGRAM = '{"dimensions": 1, "edges": [0, 10, 20], "weights": [0.3, 0.7]}'
DIRICHLET = '{"alphas": [5.0, 2.0, 3.0]}'
ONTOLOGY_EXAMPLES = [
    ("gmmLiteral", GaussianMixtureLiteral, GMM),
    ("histogramLiteral", HistogramLiteral, HISTOGRAM),
    ("dirichletLiteral", DirichletLiteral, DIRICHLET),
]
ONE_COMPONENT = {
    "n_components": 1,
    "dimensions": 1,
    "covariance_type": "diag",
    "weights": [1.0],
    "means": [[0.0]],
    "covariances": [[1.0]],
}


@pytest.mark.parametrize("local, kind, lexical", ONTOLOGY_EXAMPLES)
def test_an_ontology_example_reads_and_writes_unchanged(local, kind, lexical):
    value = from_xsd_literal(lexical, UQ_PFX + local)
    assert type(value) is kind
    assert value.to_lexical() == lexical

    literal = Literal(value)
    assert literal.datatype == URIRef(UQ_PFX + local)
    assert str(literal) == lexical


@pytest.mark.parametrize("local, kind, lexical", ONTOLOGY_EXAMPLES)
def test_a_new_value_writes_the_ontology_form(local, kind, lexical):
    fresh = kind(**json.loads(lexical))
    assert fresh.to_lexical() == lexical
    assert fresh == kind.from_lexical(lexical)
    assert hash(fresh) == hash(kind.from_lexical(lexical))


def test_a_stored_lexical_form_survives_rdflib_and_a_write():
    compact = (
        '{"n_components":1,"dimensions":1,"covariance_type":"full",'
        '"weights":[1.0],"means":[[2.0]],"covariances":[[[0.5]]]}'
    )
    literal = Literal(compact, datatype=URIRef(UQ_PFX + "gmmLiteral"))
    assert str(literal) == compact
    assert str(Literal(literal.toPython())) == compact


@pytest.mark.parametrize(
    "covariance_type, covariances",
    [
        ("full", [[[1, 0], [0, 1]]]),
        ("diag", [[1.0, 2.0]]),
        ("spherical", [1.0]),
    ],
)
def test_each_covariance_type_has_its_shape(covariance_type, covariances):
    value = GaussianMixtureLiteral(1, 2, covariance_type, [1.0], [[0, 0]], covariances)
    assert json.loads(value.to_lexical())["covariances"] == covariances


def test_a_two_dimensional_histogram_has_one_weight_per_cell():
    value = HistogramLiteral(
        2, [[0.0, 1.0, 2.0], [10.0, 20.0, 30.0]], [0.1, 0.2, 0.3, 0.4]
    )
    assert len(value.edges) == 2


def test_one_dimension_also_reads_a_nested_edge_list():
    lexical = '{"dimensions": 1, "edges": [[0.0, 1.0, 2.0]], "weights": [0.5, 0.5]}'
    assert HistogramLiteral.from_lexical(lexical).to_lexical() == lexical


def test_a_value_pickles_with_its_lexical_form():
    value = DirichletLiteral.from_lexical('{"alphas":[1,2]}')
    assert pickle.loads(pickle.dumps(value)).to_lexical() == '{"alphas":[1,2]}'


@pytest.mark.parametrize(
    "build",
    [
        lambda: GaussianMixtureLiteral(**{**ONE_COMPONENT, "weights": [0.9]}),
        lambda: GaussianMixtureLiteral(**{**ONE_COMPONENT, "covariance_type": "tied"}),
        lambda: GaussianMixtureLiteral(
            **{**ONE_COMPONENT, "covariance_type": ["diag"]}
        ),
        lambda: GaussianMixtureLiteral(**{**ONE_COMPONENT, "means": [0.0]}),
        lambda: GaussianMixtureLiteral(**{**ONE_COMPONENT, "n_components": True}),
        lambda: GaussianMixtureLiteral.from_lexical(GMM.replace("5.0", "NaN")),
        lambda: GaussianMixtureLiteral.from_lexical(
            json.dumps(dict(reversed(list(ONE_COMPONENT.items()))))
        ),
        lambda: DirichletLiteral.from_lexical('{"alphas": [1, 2], "extra": 1}'),
        lambda: DirichletLiteral.from_lexical("alphas"),
        lambda: DirichletLiteral.from_lexical("[1, 2]"),
        lambda: DirichletLiteral([0.0, 1.0]),
        lambda: DirichletLiteral([1.0]),
        lambda: HistogramLiteral(1, [2, 1], [1.0]),
        lambda: HistogramLiteral(1, [0], []),
        lambda: HistogramLiteral(2, [[0, 1, 2], [0, 1]], [1.0]),
        lambda: HistogramLiteral(1, [0, 1, 2], [1.5, -0.5]),
        lambda: NonNegativeDouble(-0.1),
        lambda: NonNegativeDouble(float("nan")),
        lambda: NonNegativeDouble("abc"),
    ],
)
def test_a_value_outside_the_datatype_is_refused(build):
    with pytest.raises(ValueError):
        build()


def test_a_non_negative_double_is_written_with_its_own_datatype():
    value = from_xsd_literal("3.5", UQ_PFX + "nonNegativeDouble")
    assert type(value) is NonNegativeDouble
    literal = Literal(value)
    assert literal.datatype == URIRef(UQ_PFX + "nonNegativeDouble")
    assert str(literal) == "3.5"
    assert Literal(NonNegativeDouble("INF")).n3().startswith('"INF"')


def test_a_non_negative_double_calculates_as_a_plain_float():
    result = NonNegativeDouble(3.5) - 10
    assert type(result) is float
    assert result == -6.5


def test_the_python_bindings_of_other_types_stay():
    assert Literal(1.5).datatype == XSD.double
    assert Literal(1).datatype == XSD.integer
    assert Literal(True).datatype == XSD.boolean
    assert Literal(NonNegativeDouble(1.5), datatype=XSD.double).datatype == XSD.double
    assert isinstance(from_xsd_literal("x", "urn:example:datatype"), Literal)


def test_a_value_goes_through_the_write_path():
    value = GaussianMixtureLiteral(**ONE_COMPONENT)
    triple = ("http://example.org/s", "http://example.org/p", value)
    assert sanitize_triple(triple)[2].datatype == URIRef(UQ_PFX + "gmmLiteral")

    text = triple_to_string(triple)
    assert validate_update_query("INSERT DATA { " + text + " . }")
    assert (
        next(Graph().parse(data=f"{text} .", format="turtle").objects()).toPython()
        == value
    )


def test_a_binding_converts_to_the_class():
    binding = {
        "type": "literal",
        "value": DIRICHLET,
        "datatype": UQ_PFX + "dirichletLiteral",
    }
    assert type(convert_binding_to_python_type(binding)) is DirichletLiteral


def test_a_domain_iri_names_the_class():
    binding = {"type": "uri", "value": UQ_PFX + "nonNegativeDouble"}
    assert convert_binding_to_python_type(binding) is NonNegativeDouble


def test_rdflib_keeps_an_ill_formed_literal_as_a_term():
    literal = Literal('{"alphas": [0]}', datatype=URIRef(UQ_PFX + "dirichletLiteral"))
    assert literal.ill_typed is True
    assert literal.value is None
