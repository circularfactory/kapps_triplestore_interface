"""Offline tests for the examples: the copy-out command, and the wheel that carries the payload.

None of these tests reaches a triple store. Running the examples against a GraphDB is a
separate check: it needs the compose stack that the payload itself ships.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from kapps_triplestore_interface import examples_cli

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_SCRIPTS = (
    "select_query.py",
    "atomic_update.py",
    "blank_node_identity.py",
)
TOTAL_EXPECTED_FILES = len(examples_cli.PAYLOAD_FILES) + 1  # the payload plus README.md


class TestCopyExamples:
    def test_copy_writes_exactly_payload_plus_readme(self, tmp_path: Path) -> None:
        written = examples_cli.copy_examples(tmp_path)

        assert len(written) == TOTAL_EXPECTED_FILES
        assert (tmp_path / "README.md").is_file()
        for name in examples_cli.PAYLOAD_FILES:
            assert (tmp_path / name).is_file(), f"{name} should have been copied"

    def test_the_three_examples_and_their_helper_are_in_the_payload(self) -> None:
        for name in (*EXAMPLE_SCRIPTS, "_store.py"):
            assert name in examples_cli.PAYLOAD_FILES

    def test_the_compose_files_arrive_together_in_a_docker_subdirectory(
        self, tmp_path: Path
    ) -> None:
        """The compose file mounts the repository config as a sibling path."""
        examples_cli.copy_examples(tmp_path)

        compose = tmp_path / "docker" / "docker-compose.yml"
        config = tmp_path / "docker" / "graphdb-repo-config.ttl"
        assert compose.is_file()
        assert config.is_file()
        assert "graphdb-repo-config.ttl" in compose.read_text(encoding="utf-8")

    def test_the_repository_runs_the_one_ruleset(self, tmp_path: Path) -> None:
        examples_cli.copy_examples(tmp_path)
        config = (tmp_path / "docker" / "graphdb-repo-config.ttl").read_text(
            encoding="utf-8"
        )

        assert 'graphdb:ruleset "rdfsplus-optimized"' in config
        assert "owl-max" not in config

    def test_the_package_internals_are_not_copied(self, tmp_path: Path) -> None:
        examples_cli.copy_examples(tmp_path)

        assert not (tmp_path / "__init__.py").exists()
        assert not (tmp_path / "__pycache__").exists()

    def test_a_second_run_leaves_an_edited_file_untouched(self, tmp_path: Path) -> None:
        examples_cli.copy_examples(tmp_path)
        edited = tmp_path / "select_query.py"
        edited.write_bytes(b"# my edit\n")

        written = examples_cli.copy_examples(tmp_path)

        assert edited not in written
        assert edited.read_bytes() == b"# my edit\n"

    def test_a_second_run_reports_what_it_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        examples_cli.copy_examples(tmp_path)
        capsys.readouterr()

        written = examples_cli.copy_examples(tmp_path)

        assert written == []
        assert (
            "Skipping select_query.py (already exists; use --force to overwrite)"
            in (capsys.readouterr().out)
        )

    def test_force_overwrites_an_edited_file(self, tmp_path: Path) -> None:
        edited = tmp_path / "select_query.py"
        tmp_path.mkdir(exist_ok=True)
        edited.write_bytes(b"# my edit\n")

        written = examples_cli.copy_examples(tmp_path, force=True)

        assert edited in written
        assert edited.read_bytes() != b"# my edit\n"

    def test_the_readme_names_the_command_and_every_example(
        self, tmp_path: Path
    ) -> None:
        examples_cli.copy_examples(tmp_path)
        readme = (tmp_path / "README.md").read_text(encoding="utf-8")

        for name in EXAMPLE_SCRIPTS:
            assert name in readme
        assert "docker compose" in readme


class TestMain:
    def test_main_returns_zero_and_populates_directory(self, tmp_path: Path) -> None:
        dest = tmp_path / "my_examples"

        assert examples_cli.main([str(dest)]) == 0
        assert (dest / "README.md").is_file()
        assert (dest / "select_query.py").is_file()
        assert (dest / "docker" / "docker-compose.yml").is_file()

    def test_main_with_force_flag(self, tmp_path: Path) -> None:
        dest = tmp_path / "forced"
        dest.mkdir()
        (dest / "_store.py").write_bytes(b"# sentinel\n")

        assert examples_cli.main([str(dest), "--force"]) == 0
        assert (dest / "_store.py").read_bytes() != b"# sentinel\n"


class TestTheExamplesThemselves:
    """What can be said of the examples without a store."""

    @pytest.fixture
    def copied(self, tmp_path: Path) -> Path:
        examples_cli.copy_examples(tmp_path)
        return tmp_path

    @pytest.mark.parametrize("name", EXAMPLE_SCRIPTS)
    def test_each_example_parses_and_runs_only_as_a_script(
        self, copied: Path, name: str
    ) -> None:
        """Importing an example must not reach a store: the release probe imports every module."""
        source = (copied / name).read_text(encoding="utf-8")
        tree = ast.parse(source)

        assert ast.get_docstring(tree), f"{name} has no module docstring"
        guarded = any(
            isinstance(node, ast.If) and "__main__" in ast.unparse(node.test)
            for node in tree.body
        )
        assert guarded, f"{name} has no __main__ guard"

    @pytest.mark.parametrize("name", EXAMPLE_SCRIPTS)
    def test_each_example_gets_its_connection_from_the_one_helper(
        self, copied: Path, name: str
    ) -> None:
        source = (copied / name).read_text(encoding="utf-8")

        assert "from _store import" in source
        for deprecated in ("GraphDBCredentials", "GraphDB(", "GRAPHDB_"):
            assert deprecated not in source

    def test_the_helper_connects_with_the_current_public_names(
        self, copied: Path
    ) -> None:
        source = (copied / "_store.py").read_text(encoding="utf-8")

        assert "connect(" in source
        assert "TripleStoreEndpoint" in source
        assert "GDBTokenAuth" in source
        assert "GRAPHDB_" not in source
        assert "GraphDBCredentials" not in source

    def test_the_helper_defaults_match_the_shipped_compose_file(
        self, copied: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for variable in (
            "TRIPLESTORE_URL",
            "TRIPLESTORE_DATASET",
            "TRIPLESTORE_USERNAME",
            "TRIPLESTORE_PASSWORD",
        ):
            monkeypatch.delenv(variable, raising=False)
        monkeypatch.syspath_prepend(str(copied))
        sys.modules.pop("_store", None)
        try:
            import _store  # pylint: disable=import-outside-toplevel,import-error

            endpoint = _store.endpoint_from_environment()
        finally:
            sys.modules.pop("_store", None)

        compose = (copied / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
        assert endpoint.url == "http://localhost:7200"
        assert '"7200:7200"' in compose
        assert f"repositories/{endpoint.dataset}/size" in compose

    def test_the_helper_reads_the_environment(
        self, copied: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRIPLESTORE_URL", "http://localhost:17200")
        monkeypatch.setenv("TRIPLESTORE_DATASET", "mine")
        monkeypatch.syspath_prepend(str(copied))
        sys.modules.pop("_store", None)
        try:
            import _store  # pylint: disable=import-outside-toplevel,import-error

            endpoint = _store.endpoint_from_environment()
        finally:
            sys.modules.pop("_store", None)

        assert endpoint.url == "http://localhost:17200"
        assert endpoint.dataset == "mine"

    def test_the_examples_name_no_private_host(self, copied: Path) -> None:
        private = re.compile(
            "|".join(["ki" + r"t\.edu", "iam" + "-mms", r"\bK" + "IT" + r"\b"]),
            re.IGNORECASE,
        )
        for path in copied.rglob("*"):
            if path.is_file():
                assert not private.search(path.read_text(encoding="utf-8")), path.name


@pytest.mark.skipif(shutil.which("uv") is None, reason="building the wheel needs uv")
class TestTheWheel:
    def test_the_wheel_built_from_this_tree_contains_the_payload(
        self, tmp_path: Path
    ) -> None:
        """The wheel, built as the release builds it, carries every file the command copies."""
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        )
        (wheel,) = tmp_path.glob("*.whl")
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())

        package = "kapps_triplestore_interface"
        assert f"{package}/examples_cli.py" in names
        for name in examples_cli.PAYLOAD_FILES:
            assert (
                f"{package}/examples/{name}" in names
            ), f"{name} is missing from the wheel"

    def test_the_console_command_is_declared_once_in_the_manifest(self) -> None:
        manifest = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

        scripts = re.findall(
            r'^([\w-]+)\s*=\s*"kapps_triplestore_interface\.examples_cli:main"',
            manifest,
            re.MULTILINE,
        )
        assert scripts == ["kapps-triplestore-examples"]
