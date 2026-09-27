"""The reported version must equal the packaged version (audit 2026-09-27).

/health hardcoded "3.2.0" while pyproject.toml said 3.1.3, so the version the
product reported to operators and monitoring did not match the version it was
built from. These tests fail if the two ever drift again.
"""
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

PYPROJECT = Path(main.__file__).parent / "pyproject.toml"


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_pyproject_is_readable_and_has_a_version():
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["project"]["version"], "pyproject has no version"


def test_health_reports_the_packaged_version(client):
    with PYPROJECT.open("rb") as fh:
        packaged = tomllib.load(fh)["project"]["version"]
    reported = client.get("/health").json()["version"]
    assert reported == packaged, (
        f"/health reports {reported!r} but pyproject.toml declares {packaged!r}. "
        "The version must be single-sourced from pyproject."
    )


def test_health_version_is_not_the_unknown_fallback(client):
    """A silent fallback would mask a packaging error as a valid build."""
    assert client.get("/health").json()["version"] != "0.0.0+unknown", (
        "pyproject.toml could not be read at runtime -- the installed package "
        "is missing its metadata, which is a packaging bug, not a version."
    )


def test_version_is_valid_semver():
    with PYPROJECT.open("rb") as fb:
        version = tomllib.load(fb)["project"]["version"]
    major, minor, patch = version.split(".")
    assert major.isdigit() and minor.isdigit() and patch.isdigit(), version
