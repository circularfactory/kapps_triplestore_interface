"""Every ontology namespace in the shipped files and tests uses `http://`.

An ontology namespace is an identifier, not a link, and every W3C ontology spells it with
`http://`. The guard refuses an `https://` namespace of the project's closed list (the CRC
ontologies and the example namespaces) anywhere in the shipped files, and any `https://` IRI
inside a `@prefix` or `PREFIX` declaration. The pattern is assembled from pieces, so that the
refused spelling does not ship in this file's own text.

Exceptions, by design: web links (for example the CRC home page), external vocabularies whose
own namespace is `https`, web URLs in test data (the `graphdb.example.org` host), the IRI test
module, whose syntax cases must cover the `https` scheme, and released CHANGELOG sections.
"""

import re
from collections.abc import Iterator
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_SCHEME = "https" + ":" + "//"
# The closed list of refused hosts. The lookahead on the example hosts lets a subdomain such as
# `graphdb.example.org` (a web URL in test data) through; `www` is split off like the scheme, so
# that the refused spelling does not ship here.
_NAMESPACES = re.compile(
    re.escape(_SCHEME)
    + "(?:"
    + "|".join(
        [
            "www" + r"\.sfb1574\.kit\.edu/ontologies",
            r"example\.org(?![\w.-])",
            r"example\.com(?![\w.-])",
        ]
    )
    + ")"
)
_DECLARATION = re.compile(
    "(?:@prefix|PREFIX)" + r"\s+[\w-]*:\s*<" + re.escape(_SCHEME),
    re.IGNORECASE,
)
_SUFFIXES = {".py", ".md", ".rst", ".toml", ".txt", ".ttl", ".yml"}
_SKIPPED_PARTS = {"__pycache__", "_build"}
_IRI_SYNTAX_MODULE = "tests/test_iri.py"


def _unreleased_changelog() -> str:
    text = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = text.split("## Unreleased", 1)[1]
    return re.split(r"^## ", section, maxsplit=1, flags=re.MULTILINE)[0]


def _shipped_texts() -> Iterator[tuple[str, str]]:
    yield "README.md", (_ROOT / "README.md").read_text(encoding="utf-8")
    yield "CHANGELOG.md (Unreleased)", _unreleased_changelog()
    for area in (
        "src",
        "tests",
        "tests_release",
        "docs/site",
        "release/probes",
        "examples",
    ):
        for path in sorted((_ROOT / area).rglob("*")):
            name = str(path.relative_to(_ROOT))
            if (
                path.is_file()
                and path.suffix in _SUFFIXES
                and not _SKIPPED_PARTS & set(path.parts)
                and name != _IRI_SYNTAX_MODULE
            ):
                yield name, path.read_text(encoding="utf-8")


def test_no_ontology_namespace_uses_https() -> None:
    hits = [
        f"{name}: {match.group(0)!r}"
        for name, text in _shipped_texts()
        for pattern in (_NAMESPACES, _DECLARATION)
        for match in pattern.finditer(text)
    ]
    assert hits == []


def test_the_guard_recognises_an_https_namespace() -> None:
    refused = [
        _SCHEME + "example.org/s",
        _SCHEME + "www.sfb1574.kit.edu/ontologies/TransferUnit#x",
        "PREFIX ex: <" + _SCHEME + "vocab.example/>",
        "@prefix ex: <" + _SCHEME + "vocab.example/> .",
    ]
    allowed = [
        _SCHEME + "graphdb.example.org/",
        _SCHEME + "www.sfb1574.kit.edu/english/index.php",
        "http://example.org/s",
    ]
    for text in refused:
        assert _NAMESPACES.search(text) or _DECLARATION.search(text), text
    for text in allowed:
        assert not (_NAMESPACES.search(text) or _DECLARATION.search(text)), text
