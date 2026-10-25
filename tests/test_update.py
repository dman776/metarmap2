"""
Tests for the self-update (lib/utils.update): pulls new code, keeps the config files, and runs git as the owner
of the folder rather than root.
"""
import json
import subprocess
from types import SimpleNamespace

import pytest

from metarmap.lib import utils


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args], cwd=cwd,
                   check=True, capture_output=True)


@pytest.fixture
def repos(tmp_path):
    """A bare "GitHub" repo, a developer clone that pushes to it, and the map's clone that updates from it."""
    origin, dev, pi = tmp_path / "origin.git", tmp_path / "dev", tmp_path / "map"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", str(origin), str(dev))
    git(dev, "checkout", "-B", "main")
    (dev / "code.py").write_text("VERSION = 1\n")
    (dev / "config.json").write_text(json.dumps({"from": "repo"}))
    (dev / "airports.json").write_text(json.dumps({"KHOU": {"display": True}}))
    git(dev, "add", "-A")
    git(dev, "commit", "-m", "first")
    git(dev, "push", "-u", "origin", "main")
    git(tmp_path, "clone", str(origin), str(pi))
    return SimpleNamespace(origin=origin, dev=dev, pi=pi)


def test_pulls_new_code_and_keeps_config(repos):
    # the user's own settings on the map
    (repos.pi / "config.json").write_text(json.dumps({"from": "user"}))
    (repos.pi / "airports.json").write_text(json.dumps({"KGLS": {"display": True}}))
    # a new release changes the code and the default config
    (repos.dev / "code.py").write_text("VERSION = 2\n")
    (repos.dev / "config.json").write_text(json.dumps({"from": "new release"}))
    git(repos.dev, "commit", "-am", "second")
    git(repos.dev, "push")

    log = utils.update(str(repos.pi))

    assert (repos.pi / "code.py").read_text() == "VERSION = 2\n"
    assert json.loads((repos.pi / "config.json").read_text()) == {"from": "user"}
    assert json.loads((repos.pi / "airports.json").read_text()) == {"KGLS": {"display": True}}
    assert "update complete" in log


def test_progress_and_result(repos):
    (repos.dev / "code.py").write_text("VERSION = 2\n")
    git(repos.dev, "commit", "-am", "second")
    git(repos.dev, "push")
    steps = []
    result = utils.run_update(str(repos.pi), progress=lambda fraction, label: steps.append((fraction, label)))
    assert result.ok and result.changed
    assert result.errors == []
    fractions = [f for f, _ in steps]
    assert fractions == sorted(fractions)  # the bar only moves forward
    assert steps[0] == (0.0, "Starting") and steps[-1] == (1.0, "Done")
    assert "Downloading the update" in [label for _, label in steps]


def test_already_up_to_date(repos):
    result = utils.run_update(str(repos.pi))
    assert result.ok and not result.changed


def test_failed_pull_is_reported_and_config_kept(repos):
    (repos.pi / "config.json").write_text(json.dumps({"from": "user"}))
    git(repos.pi, "remote", "set-url", "origin", str(repos.origin) + "-missing")

    log = utils.update(str(repos.pi))

    assert "update FAILED" in log
    assert "git pull failed" in log
    assert json.loads((repos.pi / "config.json").read_text()) == {"from": "user"}
    result = utils.run_update(str(repos.pi))
    assert not result.ok and not result.changed
    assert result.errors  # git's own error message, shown in the web UI


# ---- running as root (the map's service) ------------------------------------------------------------------------

@pytest.fixture
def as_root(monkeypatch, tmp_path):
    """Pretend the map runs as root in a folder owned by pi (uid 1000); record what would be run and chown'd."""
    calls = SimpleNamespace(run=[], lchown=[], chown=[])
    monkeypatch.setattr(utils.os, "geteuid", lambda: 0)
    monkeypatch.setattr(utils, "_repo_owner", lambda repo: (1000, 1000))
    import pwd
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir="/home/pi", pw_name="pi"))
    monkeypatch.setattr(utils.os, "lchown", lambda path, uid, gid: calls.lchown.append((path, uid, gid)))
    monkeypatch.setattr(utils.os, "chown", lambda path, uid, gid: calls.chown.append((path, uid, gid)))

    def fake_run(cmd, **kwargs):
        calls.run.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")
    monkeypatch.setattr(utils.subprocess, "run", fake_run)

    repo = tmp_path / "map"
    (repo / "sub").mkdir(parents=True)
    (repo / "config.json").write_text("{}")
    (repo / "airports.json").write_text("{}")
    (repo / "sub" / "file.py").write_text("")
    calls.repo = repo
    return calls


def test_git_runs_as_the_folder_owner(as_root):
    log = utils.update(str(as_root.repo))
    commands = [cmd[3:] for cmd, _ in as_root.run]
    assert [c for c in commands if c[0] != "rev-parse"] == [["reset", "--hard"], ["pull"]]
    for cmd, kwargs in as_root.run:
        assert kwargs["user"] == 1000 and kwargs["group"] == 1000
        assert kwargs["env"]["HOME"] == "/home/pi"
    assert "running git as pi" in log


def test_root_owned_files_are_given_back(as_root):
    utils.update(str(as_root.repo))
    changed = {path for path, uid, gid in as_root.lchown}
    # every path in the folder belongs to the test user, not uid 1000, so all of them are handed over
    assert str(as_root.repo / "sub" / "file.py") in changed
    assert str(as_root.repo) in changed
    restored = {path for path, uid, gid in as_root.chown}
    assert restored == {str(as_root.repo / "config.json"), str(as_root.repo / "airports.json")}


def test_no_user_switch_when_not_root(monkeypatch, tmp_path):
    runs = []
    monkeypatch.setattr(utils.subprocess, "run",
                        lambda cmd, **kw: runs.append(kw) or subprocess.CompletedProcess(cmd, 0, "", ""))
    utils.update(str(tmp_path))
    assert runs and all("user" not in kw for kw in runs)
