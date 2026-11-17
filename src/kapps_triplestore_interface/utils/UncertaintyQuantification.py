"""The datatypes of the Circular Factory Uncertainty Quantification ontology as Python classes.

Importing this module binds each datatype in rdflib, so `rdflib.Literal(value)` gives a literal
of the right datatype and a literal of the datatype converts to its class.
"""

from dataclasses import dataclass, fields
from typing import Any, ClassVar, Dict, Optional, Self, Tuple, Union
import json
import math
from rdflib import URIRef
from rdflib.term import _GenericPythonToXSDRules, bind

UQ_PFX = "https://w3id.org/circularfactory/UncertaintyQuantification#"


def _plain(value: Any) -> Any:
    """A numpy array or scalar as the Python list or number it holds; anything else unchanged."""
    return value.tolist() if hasattr(value, "tolist") else value


def _positive_integer(value: Any, name: str) -> int:
    value = _plain(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return value


def _numbers(value: Any, shape: Tuple[Optional[int], ...], name: str) -> Any:
    """`value` as nested tuples of finite numbers of exactly `shape`; `None` allows any length.

    An integer stays an integer, so that a lexical form made from the value keeps it.
    """
    value = _plain(value)
    if not shape:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            raise ValueError(f"{name} must hold finite numbers, got {value!r}")
        return value
    if not isinstance(value, (list, tuple)) or shape[0] not in (None, len(value)):
        raise ValueError(f"{name} must have the shape {shape}, got {value!r}")
    return tuple(_numbers(item, shape[1:], name) for item in value)


def _weights(value: Any, count: int, tolerance: float) -> Tuple[float, ...]:
    weights = _numbers(value, (count,), "weights")
    if any(weight < 0 for weight in weights) or abs(sum(weights) - 1) > tolerance:
        raise ValueError(
            f"weights must not be negative and must sum to 1, got {weights}"
        )
    return weights


def _set_fields(instance: Any, **values: Any) -> None:
    """Replace fields of a frozen dataclass from its `__post_init__`."""
    for name, value in values.items():
        object.__setattr__(instance, name, value)


class _JsonLiteral:
    """A datatype whose lexical form is a JSON object with the dataclass fields, in their order.

    A value read from a lexical form writes that same form back, so that a write names the
    stored literal again: two lexical forms of one value are two different RDF terms. Any other
    value writes the form of `json.dumps`.
    """

    _lexical: ClassVar[Optional[str]] = None

    @classmethod
    def from_lexical(cls, lexical: str) -> Self:
        """Parse and validate a lexical form.

        Raises:
            ValueError: If the form is not a JSON object with exactly the fields in their
                order, or a field breaks a rule of the datatype.
        """
        names = [field.name for field in fields(cls)]
        data = json.loads(lexical)
        if not isinstance(data, dict) or list(data) != names:
            raise ValueError(
                f"{cls.__name__} needs exactly the fields {names}, in this order, got {lexical}"
            )
        instance = cls(**data)
        object.__setattr__(instance, "_lexical", lexical)
        return instance

    def to_lexical(self) -> str:
        if self._lexical is not None:
            return self._lexical
        return json.dumps(
            {field.name: getattr(self, field.name) for field in fields(self)}
        )

    def __str__(self) -> str:
        return self.to_lexical()


@dataclass(frozen=True)
class GaussianMixtureLiteral(_JsonLiteral):
    """A value of `uq:gmmLiteral`.

    `covariances` holds one entry per component: a D by D matrix (`full`), D numbers (`diag`)
    or one number (`spherical`). Its shape is checked, its values are not.
    """

    n_components: int
    dimensions: int
    covariance_type: str
    weights: Tuple[float, ...]
    means: Tuple[Tuple[float, ...], ...]
    covariances: Tuple[Any, ...]

    def __post_init__(self) -> None:
        components = _positive_integer(self.n_components, "n_components")
        dimensions = _positive_integer(self.dimensions, "dimensions")
        shapes = {
            "full": (components, dimensions, dimensions),
            "diag": (components, dimensions),
            "spherical": (components,),
        }
        if (
            not isinstance(self.covariance_type, str)
            or self.covariance_type not in shapes
        ):
            raise ValueError(
                f"covariance_type must be one of {list(shapes)}, got {self.covariance_type!r}"
            )
        _set_fields(
            self,
            n_components=components,
            dimensions=dimensions,
            weights=_weights(self.weights, components, tolerance=1e-4),
            means=_numbers(self.means, (components, dimensions), "means"),
            covariances=_numbers(
                self.covariances, shapes[self.covariance_type], "covariances"
            ),
        )


@dataclass(frozen=True)
class HistogramLiteral(_JsonLiteral):
    """A value of `uq:histogramLiteral`.

    `edges` holds the strictly increasing bin boundaries: one list per dimension, or a flat
    list for one dimension. `weights` is flat, one number per cell, the last dimension changing
    fastest.
    """

    dimensions: int
    edges: Tuple[Any, ...]
    weights: Tuple[float, ...]

    def __post_init__(self) -> None:
        dimensions = _positive_integer(self.dimensions, "dimensions")
        edges = _plain(self.edges)
        one_flat_list = (
            dimensions == 1
            and isinstance(edges, (list, tuple))
            and not (edges and isinstance(_plain(edges[0]), (list, tuple)))
        )
        if one_flat_list:
            edges = _numbers(edges, (None,), "edges")
            axes = (edges,)
        else:
            edges = _numbers(edges, (dimensions, None), "edges")
            axes = edges
        for axis in axes:
            if len(axis) < 2 or any(low >= high for low, high in zip(axis, axis[1:])):
                raise ValueError(
                    f"edges must be at least 2 strictly increasing numbers, got {axis}"
                )
        cells = math.prod(len(axis) - 1 for axis in axes)
        _set_fields(
            self,
            dimensions=dimensions,
            edges=edges,
            weights=_weights(self.weights, cells, tolerance=1e-6),
        )


@dataclass(frozen=True)
class DirichletLiteral(_JsonLiteral):
    """A value of `uq:dirichletLiteral`: at least two positive concentration parameters."""

    alphas: Tuple[float, ...]

    def __post_init__(self) -> None:
        alphas = _numbers(self.alphas, (None,), "alphas")
        if len(alphas) < 2 or any(alpha <= 0 for alpha in alphas):
            raise ValueError(
                f"alphas must be at least 2 positive numbers, got {alphas}"
            )
        _set_fields(self, alphas=alphas)


class NonNegativeDouble(float):
    """A value of `uq:nonNegativeDouble`. Arithmetic gives a plain `float`, which may be negative."""

    def __new__(cls, value: Union[float, str]) -> Self:
        instance = super().__new__(cls, value)
        # Written this way round so that NaN is refused as well.
        if not instance >= 0:
            raise ValueError(f"a non-negative double must be at least 0, got {value!r}")
        return instance

    @classmethod
    def from_lexical(cls, lexical: str) -> Self:
        return cls(lexical)

    def to_lexical(self) -> str:
        return "INF" if math.isinf(self) else float.__repr__(self)


UQ_DATATYPES: Dict[str, Any] = {
    "gmmLiteral": GaussianMixtureLiteral,
    "histogramLiteral": HistogramLiteral,
    "dirichletLiteral": DirichletLiteral,
    "nonNegativeDouble": NonNegativeDouble,
}

# rdflib takes the first rule that matches and a float subclass matches the float rule, so each
# new rule moves to the front.
for _name, _kind in UQ_DATATYPES.items():
    bind(URIRef(UQ_PFX + _name), _kind, _kind.from_lexical, _kind.to_lexical)
    _GenericPythonToXSDRules.insert(0, _GenericPythonToXSDRules.pop())
