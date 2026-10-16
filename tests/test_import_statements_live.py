"""An import that violates a SHACL shape raises `ShaclValidationError` and imports nothing.

The live half of `test_import_statements_refusal.py`. It needs a repository with SHACL
validation. It uses the shape, the thing and the cleanup of `test_shacl_validation_error.py`:
a thing that may hold at most one part, and that holds one.
"""

import pytest

from kapps_triplestore_interface import GraphDB, ShaclValidationError
from tests.test_shacl_validation_error import (  # pylint: disable=unused-import
    PART,
    THING,
    TWO,
    at_most_one_part,
)


def test_a_live_refused_import_raises_the_shacl_type_and_imports_nothing(
    db: GraphDB, at_most_one_part
):
    with pytest.raises(ShaclValidationError) as refused:
        db.graph_add(f"<{THING}> <{PART}> <{TWO}> .", content_type="text/turtle")

    report = refused.value.report
    assert "<http://www.w3.org/ns/shacl#ValidationReport>" in report
    assert f"<http://www.w3.org/ns/shacl#focusNode> <{THING}>" in report
    assert f"<http://www.w3.org/ns/shacl#resultPath> <{PART}>" in report
    assert not db.query(f"ASK {{ <{THING}> <{PART}> <{TWO}> }}")["boolean"]
