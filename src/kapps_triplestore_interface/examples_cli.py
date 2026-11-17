"""CLI tool to copy the bundled examples into a user-writable directory.

This module provides the ``kapps-triplestore-examples`` console script. It locates the example
files that ship with the package and copies them, with the compose files that start the GraphDB
they need, to a destination the user owns. The examples are meant to be edited and re-run
locally, not executed from within site-packages.
"""

from __future__ import annotations

import argparse
import importlib.resources as ir
import sys
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

# The exact payload files to copy. Do not add __init__.py or __pycache__ here.
#
# A name may contain a forward slash, and two do. `docker/` is copied out with the examples
# because the examples need a GraphDB and this is how a pip-installing user obtains one.
# Forward slashes regardless of platform: these are `importlib.resources` traversal keys, not
# filesystem paths, and the destination side is built with pathlib.
PAYLOAD_FILES: Final[tuple[str, ...]] = (
    "_store.py",
    "select_query.py",
    "atomic_update.py",
    "blank_node_identity.py",
    "docker/docker-compose.yml",
    "docker/graphdb-repo-config.ttl",
)

COPIED_README: Final[str] = """# kapps-triplestore-interface examples

This folder holds copies of the examples that ship with kapps-triplestore-interface. You own
these files: edit and re-run them freely. Running ``kapps-triplestore-examples`` again does not
overwrite them unless you pass ``--force``.

## What is here

- ``select_query.py``: connect, write two facts, read them back with one SELECT.
- ``atomic_update.py``: replace a property in one atomic update, and why that is not two
  operations.
- ``blank_node_identity.py``: what a blank node is in the store, and the update that keeps it.
- ``_store.py``: the one place where the examples connect to the GraphDB.
- ``docker/``: a ``docker compose`` file that starts the GraphDB the examples need, and the
  repository configuration that it posts.

## Start the GraphDB

```bash
cd docker
docker compose up -d
```

That serves GraphDB on http://localhost:7200 and creates the ``kapps-demo`` repository. The
repository has no access control, and the examples log in as ``admin`` with the password
``root``, the defaults of the compose file. Wait until ``docker compose ps`` shows the ``graphdb-init`` service as exited.

To use another store, set ``TRIPLESTORE_URL``, ``TRIPLESTORE_DATASET``, ``TRIPLESTORE_USERNAME`` and
``TRIPLESTORE_PASSWORD`` (see ``_store.py``).

**Each example clears the graph that it uses when it starts.** Never point the examples at a
repository whose data you care about.

## Run an example

```bash
python select_query.py
python atomic_update.py
python blank_node_identity.py
```

Each example prints what it shows. Stop the GraphDB with ``docker compose down`` in ``docker/``.
"""


def _locate_examples_root() -> Traversable:
    """Find the bundled examples directory inside the installed package."""
    root = ir.files("kapps_triplestore_interface") / "examples"
    if not root.joinpath("_store.py").is_file():
        raise RuntimeError("could not locate the bundled examples")
    return root


def copy_examples(dest: Path, *, force: bool = False) -> list[Path]:
    """Copy the bundled example files into a user-writable directory.

    Creates ``dest`` if it does not exist. For each file, an existing target is skipped with a
    message unless ``force`` is set, so a user's own edits are never clobbered by accident.
    Returns the files actually written (the payload plus the generated ``README.md``); skipped
    files are not included.
    """
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    root = _locate_examples_root()
    written: list[Path] = []

    for name in PAYLOAD_FILES:
        # `*name.split("/")` rather than `dest / name`: a name may carry a subdirectory, and
        # splitting makes the destination explicit on every platform.
        target = dest.joinpath(*name.split("/"))
        if target.exists() and not force:
            print(f"Skipping {name} (already exists; use --force to overwrite)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source: Traversable = root
        for segment in name.split("/"):
            source = source.joinpath(segment)
        target.write_bytes(source.read_bytes())
        written.append(target)

    readme = dest / "README.md"
    if readme.exists() and not force:
        print("Skipping README.md (already exists; use --force to overwrite)")
    else:
        readme.write_text(COPIED_README, encoding="utf-8")
        written.append(readme)

    return written


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``kapps-triplestore-examples`` console script. Returns an exit code."""
    parser = argparse.ArgumentParser(
        prog="kapps-triplestore-examples",
        description="Copy the bundled examples into a local directory you can edit and run.",
    )
    parser.add_argument(
        "dest",
        nargs="?",
        default="./kapps-triplestore-examples",
        help="Destination directory (default: ./kapps-triplestore-examples)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files that already exist in the destination",
    )

    args = parser.parse_args(argv)
    dest = Path(args.dest).resolve()

    written = copy_examples(dest, force=args.force)

    print(f"\nCopied {len(written)} file(s) to {dest}")
    print("\nNext steps:")
    print(
        f"  cd {dest}/docker && docker compose up -d   # starts a local GraphDB on port 7200"
    )
    print(f"  cd {dest}")
    print("  python select_query.py")
    print("  python atomic_update.py")
    print("  python blank_node_identity.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
