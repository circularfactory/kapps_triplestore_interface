"""Every source file in the library must compile without a `SyntaxWarning`.

The warning this guards against is the one 2.1.0 shipped with: a non-raw docstring
containing `\\` produced

    SyntaxWarning: invalid escape sequence '\\`'

and because the *compiler* emits it, the user saw it once, on installing the package --
pointing at a line inside `site-packages`, which reads as "this package is broken" to
somebody who has no reason to think otherwise. PyPI does not allow re-uploading a version,
so the fix could only ship in the next one. That is the cost this test exists to avoid
paying again.

It compiles rather than imports, for two reasons. The warning comes out of compilation, so
an import whose `__pycache__` entry is already warm raises nothing -- the check would pass
locally and on every CI run after the first while the defect sat in the tree. And
`compile()` needs no GraphDB, so this is the one test here that runs without the fixture in
`conftest.py`.

Under `simplefilter("error", SyntaxWarning)` the compiler does not raise the warning class:
it raises `SyntaxError`, carrying the warning's message. A file with a genuine syntax error
therefore lands in the same list, which is correct -- an unparseable file in a release is
the same defect, further along.
"""

import warnings

from pathlib import Path

import kapps_triplestore_interface

PACKAGE_ROOT = Path(kapps_triplestore_interface.__file__).parent
"""Resolved from the imported package, so the test reads whichever copy is under test --
the source tree in CI, an installed wheel when run against one."""


def test_no_source_file_compiles_with_a_syntax_warning():
    offenders: list[str] = []

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            try:
                compile(source, str(path), "exec")
            except SyntaxError as escalated:
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}: {escalated.msg}")

    assert not offenders, (
        "Python does not compile these files cleanly, and every user installing the "
        "package sees it:\n  " + "\n  ".join(offenders)
    )
