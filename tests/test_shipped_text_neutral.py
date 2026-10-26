"""The shipped text describes the interface on its own terms.

The README, the CHANGELOG's Unreleased section, the source package, the tests and the docs site
name no consumer that is built with the library. The pattern is assembled from pieces, so that
no banned term ships in this file's own text.
"""

import re
from collections.abc import Iterator
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_BANNED = re.compile(
    "|".join(["use[\\s_-]*" + "cases?", "j" + "ms", "U" + "C[12]"]),
    re.IGNORECASE,
)
_SUFFIXES = {".py", ".md", ".rst", ".toml", ".txt", ".html", ".css", ".js", ".yml"}
_SKIPPED_PARTS = {"__pycache__", "_build"}


def _unreleased_changelog() -> str:
    text = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = text.split("## Unreleased", 1)[1]
    return re.split(r"^## ", section, maxsplit=1, flags=re.MULTILINE)[0]


def _shipped_texts() -> Iterator[tuple[str, str]]:
    yield "README.md", (_ROOT / "README.md").read_text(encoding="utf-8")
    yield "CHANGELOG.md (Unreleased)", _unreleased_changelog()
    for area in ("src", "tests", "docs/site"):
        for path in sorted((_ROOT / area).rglob("*")):
            if (
                path.is_file()
                and path.suffix in _SUFFIXES
                and not _SKIPPED_PARTS & set(path.parts)
            ):
                yield str(path.relative_to(_ROOT)), path.read_text(encoding="utf-8")


def test_no_shipped_text_names_a_consumer() -> None:
    hits = [
        f"{name}: {match.group(0)!r}"
        for name, text in _shipped_texts()
        for match in _BANNED.finditer(text)
    ]
    assert hits == []
