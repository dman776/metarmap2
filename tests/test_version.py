"""Tests for where metarmap.__version__ comes from: the git release tag, else the package's metadata."""

import subprocess
from importlib import metadata
from types import SimpleNamespace

import pytest

import metarmap
from metarmap import update


def git_says(monkeypatch, stdout="", returncode=0, raises=None):
    calls = []

    def fake(repo, *args, timeout=None):
        calls.append(args)
        if raises:
            raise raises
        return SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(update, "run_git", fake)
    return calls


def metadata_says(monkeypatch, value=None):
    def fake(name):
        if value is None:
            raise metadata.PackageNotFoundError(name)
        assert name == "metarmap2"  # the distribution's name in pyproject.toml
        return value

    monkeypatch.setattr(metadata, "version", fake)


def test_the_version_is_the_newest_release_tag_without_its_v(monkeypatch):
    calls = git_says(monkeypatch, "v26.11.12\n")
    assert metarmap._read_version() == "26.11.12"
    assert "--exclude" in calls[0] and "*-*" in calls[0]  # a pre-release tag isn't a version


@pytest.mark.parametrize(
    "failure",
    [
        {"returncode": 128},  # not a checkout, no tags, or git refusing the folder
        {"raises": OSError("no git")},
        {"raises": subprocess.TimeoutExpired("git", 5)},
        {"stdout": "26.11.12\n"},  # not a v tag
    ],
)
def test_without_a_tag_the_installed_metadata_is_used(monkeypatch, failure):
    git_says(monkeypatch, **failure)
    metadata_says(monkeypatch, "26.11.4")
    assert metarmap._read_version() == "26.11.4"


def test_without_git_or_metadata_the_version_is_unknown(monkeypatch):
    git_says(monkeypatch, returncode=128)
    metadata_says(monkeypatch, None)
    assert metarmap._read_version() == "0+unknown"


def test_this_checkout_has_a_version():
    assert metarmap.__version__ and metarmap.USER_AGENT.startswith(f"metarmap2/{metarmap.__version__} ")
