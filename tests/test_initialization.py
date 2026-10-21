import pytest
from kapps_triplestore_interface import GraphDB, GraphDBCredentials
from kapps_triplestore_interface.exceptions import (
    AuthenticationError,
    InvalidDatasetError,
)


def test_credentials_valid(db: GraphDB, store_settings):
    """Test successfull initialization"""
    try:
        credentials = GraphDBCredentials(
            base_url=store_settings["base_url"],
            username=store_settings["username"],
            password=store_settings["password"],
            repository=store_settings["repository"],
        )
        GraphDB(credentials=credentials)
    except Exception as e:
        pytest.fail(f"Unexpected error raised: {e}")


def test_credentials_from_environment(db: GraphDB, store_settings, monkeypatch):
    """Test successfull initialization from the deprecated GRAPHDB_* variables"""
    monkeypatch.setenv("GRAPHDB_URL", store_settings["base_url"])
    monkeypatch.setenv("GRAPHDB_USERNAME", store_settings["username"])
    monkeypatch.setenv("GRAPHDB_PASSWORD", store_settings["password"])
    monkeypatch.setenv("GRAPHDB_REPOSITORY", store_settings["repository"])

    try:
        credentials = GraphDBCredentials.from_env()
        GraphDB(credentials=credentials)
    except Exception as e:
        pytest.fail(f"Unexpected error raised: {e}")

    try:
        GraphDB.from_env()
    except Exception as e:
        pytest.fail(f"Unexpected error raised: {e}")


def test_credentials_from_class(db: GraphDB, store_settings):
    """Test successfull initialization"""
    try:
        credentials = GraphDBCredentials(
            base_url=store_settings["base_url"],
            username=store_settings["username"],
            password=store_settings["password"],
            repository=store_settings["repository"],
        )
        GraphDB(credentials)
    except Exception as e:
        pytest.fail(f"Unexpected error raised: {e}")


def test_credentials_invalid(db: GraphDB, store_settings):
    """Test invalid credentials used"""

    credentials = GraphDBCredentials(
        base_url=store_settings["base_url"],
        username=store_settings["username"],
        password="SomeWrongPassword",
        repository=store_settings["repository"],
    )

    with pytest.raises(AuthenticationError):
        GraphDB(credentials=credentials)


def test_invalid_repository(db: GraphDB, store_settings):
    """Test an invalid selected repository"""
    credentials = GraphDBCredentials(
        base_url=store_settings["base_url"],
        username=store_settings["username"],
        password=store_settings["password"],
        repository="SomeWrongRepository",
    )

    with pytest.raises(InvalidDatasetError):
        GraphDB(credentials=credentials)
