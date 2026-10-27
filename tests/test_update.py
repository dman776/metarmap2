"""
Tests for the self-update (lib/utils.run_update): installs the newest release tag (or, on the latest channel, the
newest commit), or a release picked by hand, keeps the config files, and runs git as the owner of the folder rather
than root. Also the check behind "Update available" (metarmap.releases) and release versions (lib/versions).
"""
import json
import subprocess
from types import SimpleNamespace

import pytest

from metarmap.lib import utils, versions
from metarmap.releases import ReleaseCheck, github_url, read_build


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args], cwd=cwd,
                   check=True, capture_output=True)


def head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repos(tmp_path):
    """
    A bare "GitHub" repo, a developer clone that pushes to it, and the map's clone that updates from it.
    GitHub has release v1.0.0; the map runs it.
    """
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
    repos = SimpleNamespace(origin=origin, dev=dev, pi=pi)
    release(repos, "v1.0.0", code=None)
    return repos


def commit(repos, code, message="change", config=None):
    (repos.dev / "code.py").write_text(f"VERSION = {code!r}\n")
    if config is not None:
        (repos.dev / "config.json").write_text(json.dumps(config))
    git(repos.dev, "commit", "-am", message)
    git(repos.dev, "push")


def release(repos, tag, code="new"):
    """Commits (unless code is None), tags it and pushes both, like a release."""
    if code is not None:
        commit(repos, code, f"Release {tag}")
    git(repos.dev, "tag", "-a", tag, "-m", f"Release {tag}")
    git(repos.dev, "push", "origin", tag)


def code(repos):
    return (repos.pi / "code.py").read_text()


# ---- the releases channel ---------------------------------------------------------------------------------------

def test_installs_the_newest_release_and_keeps_config(repos):
    # the user's own settings on the map
    (repos.pi / "config.json").write_text(json.dumps({"from": "user"}))
    (repos.pi / "airports.json").write_text(json.dumps({"KGLS": {"display": True}}))
    # a new release changes the code and the default config
    commit(repos, "1.1", "Release v1.1.0", config={"from": "new release"})
    release(repos, "v1.1.0", code=None)

    log = utils.update(str(repos.pi), current="1.0.0")

    assert code(repos) == "VERSION = '1.1'\n"
    assert json.loads((repos.pi / "config.json").read_text()) == {"from": "user"}
    assert json.loads((repos.pi / "airports.json").read_text()) == {"KGLS": {"display": True}}
    assert "update complete" in log


def test_a_newer_commit_that_isnt_released_isnt_installed(repos):
    release(repos, "v1.1.0", code="1.1")
    commit(repos, "work in progress")
    result = utils.run_update(str(repos.pi), current="1.0.0")
    assert result.ok and result.changed and result.target == "v1.1.0"
    assert code(repos) == "VERSION = '1.1'\n"
    assert result.message == "Installed v1.1.0"


def test_newest_by_version_not_by_date(repos):
    release(repos, "v1.10.0", code="1.10")
    release(repos, "v1.9.0", code="1.9")  # a fix to an older line, made later
    assert utils.run_update(str(repos.pi), current="1.0.0").target == "v1.10.0"


def test_pre_releases_and_other_tags_are_skipped(repos):
    release(repos, "v1.1.0", code="1.1")
    release(repos, "v2.0.0-rc1", code="2.0 rc")
    release(repos, "nightly", code="nightly")
    result = utils.run_update(str(repos.pi), current="1.0.0")
    assert result.target == "v1.1.0" and code(repos) == "VERSION = '1.1'\n"


def test_tags_without_the_v_are_releases_too(repos):
    release(repos, "1.1.0", code="1.1")
    assert utils.run_update(str(repos.pi), current="1.0.0").target == "1.1.0"


def test_already_on_the_newest_release(repos):
    result = utils.run_update(str(repos.pi), current="1.0.0")
    assert result.ok and not result.changed
    assert result.message == "Already on the newest release (v1.0.0)"


def test_never_goes_backwards(repos):
    """A map running unreleased code newer than the newest release (the latest channel, or a developer) stays."""
    commit(repos, "1.1 work")
    git(repos.pi, "pull")
    before = head(repos.pi)
    result = utils.run_update(str(repos.pi), current="1.1.0")
    assert result.ok and not result.changed and head(repos.pi) == before
    assert result.message == "Already on the newest release (v1.0.0)"


def test_no_releases_yet(tmp_path):
    origin, pi = tmp_path / "origin.git", tmp_path / "map"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", str(origin), str(pi))
    (pi / "code.py").write_text("x")
    git(pi, "add", "-A")
    git(pi, "commit", "-m", "first")
    git(pi, "push", "-u", "origin", "main")
    result = utils.run_update(str(pi), current="1.0.0")
    assert not result.ok and result.errors == ["There are no releases on GitHub yet"]


def test_progress_and_result(repos):
    release(repos, "v1.1.0", code="1.1")
    steps = []
    result = utils.run_update(str(repos.pi), progress=lambda fraction, label: steps.append((fraction, label)),
                              current="1.0.0")
    assert result.ok and result.changed
    assert result.errors == []
    fractions = [f for f, _ in steps]
    assert fractions == sorted(fractions)  # the bar only moves forward
    assert steps[0] == (0.0, "Starting") and steps[-1] == (1.0, "Done")
    labels = [label for _, label in steps]
    assert "Downloading the update" in labels and "Installing v1.1.0" in labels


def test_failed_download_is_reported_and_config_kept(repos):
    (repos.pi / "config.json").write_text(json.dumps({"from": "user"}))
    git(repos.pi, "remote", "set-url", "origin", str(repos.origin) + "-missing")

    log = utils.update(str(repos.pi), current="1.0.0")

    assert "update FAILED" in log
    assert "git fetch --tags --force origin failed" in log
    assert json.loads((repos.pi / "config.json").read_text()) == {"from": "user"}
    result = utils.run_update(str(repos.pi), current="1.0.0")
    assert not result.ok and not result.changed
    assert result.errors  # git's own error message, shown in the web UI


# ---- picking a release ------------------------------------------------------------------------------------------

def test_pick_an_older_release(repos):
    release(repos, "v1.1.0", code="1.1")
    utils.run_update(str(repos.pi), current="1.0.0")
    (repos.pi / "config.json").write_text(json.dumps({"from": "user"}))

    result = utils.run_update(str(repos.pi), version="v1.0.0", current="1.1.0")

    assert result.ok and result.changed and result.target == "v1.0.0"
    assert code(repos) == "VERSION = 1\n"
    assert json.loads((repos.pi / "config.json").read_text()) == {"from": "user"}
    assert result.message == "Installed v1.0.0"
    # and forward again
    assert utils.run_update(str(repos.pi), current="1.0.0").target == "v1.1.0"
    assert code(repos) == "VERSION = '1.1'\n"


def test_pick_a_release_on_the_latest_channel(repos):
    release(repos, "v1.1.0", code="1.1")
    commit(repos, "newer")
    result = utils.run_update(str(repos.pi), channel="latest", version="v1.1.0")
    assert result.target == "v1.1.0" and code(repos) == "VERSION = '1.1'\n"


def test_pick_the_release_already_running(repos):
    utils.run_update(str(repos.pi), version="v1.0.0")
    result = utils.run_update(str(repos.pi), version="v1.0.0")
    assert result.ok and not result.changed and result.message == "Already on v1.0.0"


def test_pick_a_release_that_isnt_on_github(repos):
    before = head(repos.pi)
    result = utils.run_update(str(repos.pi), version="v9.9.9")
    assert not result.ok and result.errors == ["v9.9.9 isn't a release on GitHub"] and head(repos.pi) == before


# ---- the latest channel -----------------------------------------------------------------------------------------

def test_latest_installs_the_newest_commit(repos):
    commit(repos, "unreleased")
    result = utils.run_update(str(repos.pi), channel="latest")
    assert result.ok and result.changed and code(repos) == "VERSION = 'unreleased'\n"
    assert result.target == head(repos.pi)[:7]
    assert result.message == f"Installed the newest commit ({head(repos.pi)[:7]})"
    assert utils.run_update(str(repos.pi), channel="latest").message == \
        f"Already on the newest commit ({head(repos.pi)[:7]})"


def test_latest_after_a_release_was_installed(repos):
    """A release leaves the map on a tag, not a branch; the latest channel goes back to the branch."""
    release(repos, "v1.1.0", code="1.1")
    utils.run_update(str(repos.pi), current="1.0.0")
    commit(repos, "after 1.1")
    result = utils.run_update(str(repos.pi), channel="latest")
    assert result.ok and code(repos) == "VERSION = 'after 1.1'\n"
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=repos.pi, capture_output=True, text=True)
    assert branch.stdout.strip() == "main"


def test_unknown_channel(repos):
    result = utils.run_update(str(repos.pi), channel="nightly")
    assert not result.ok and result.errors == ["Unknown update channel 'nightly'"]


# ---- install.sh: a fresh clone goes to the newest release --------------------------------------------------------

def test_a_fresh_clone_goes_to_the_newest_release(repos):
    release(repos, "v1.1.0", code="1.1")
    commit(repos, "unfinished work")
    git(repos.pi, "pull")  # what `git clone` gives: the newest commit of the branch
    assert code(repos) == "VERSION = 'unfinished work'\n"

    ok, message, changed = utils.install_newest_release(str(repos.pi))

    assert (ok, message, changed) == (True, "Installed v1.1.0", True)
    assert code(repos) == "VERSION = '1.1'\n"
    assert subprocess.run(["git", "describe", "--tags", "--exact-match"], cwd=repos.pi, capture_output=True,
                          text=True).stdout.strip() == "v1.1.0"


def test_a_clone_that_is_already_at_the_newest_release(repos):
    ok, message, changed = utils.install_newest_release(str(repos.pi))  # the clone is at v1.0.0's commit
    assert ok and not changed and message == "Already on v1.0.0"


def test_a_release_picked_by_hand_stays(repos):
    """`git checkout v1.0.0` over SSH, or an older release picked on the web UI, isn't undone by install.sh."""
    release(repos, "v1.1.0", code="1.1")
    git(repos.pi, "fetch", "--tags")
    git(repos.pi, "checkout", "v1.0.0")
    assert utils.install_newest_release(str(repos.pi)) == (True, "Already on release v1.0.0", False)
    assert code(repos) == "VERSION = 1\n"


def test_a_map_on_the_latest_channel_stays_on_the_newest_commit(repos):
    release(repos, "v1.1.0", code="1.1")
    commit(repos, "unfinished work")
    git(repos.pi, "pull")
    (repos.pi / "config.json").write_text(json.dumps({"update": {"channel": "latest"}}))
    ok, message, changed = utils.install_newest_release(str(repos.pi))
    assert (ok, changed) == (True, False) and "Latest commit" in message
    assert code(repos) == "VERSION = 'unfinished work'\n"


def test_changes_to_the_code_are_not_thrown_away(repos):
    release(repos, "v1.1.0", code="1.1")
    git(repos.pi, "pull")
    git(repos.pi, "fetch", "--tags")
    commit(repos, "unfinished work")
    git(repos.pi, "pull")
    (repos.pi / "code.py").write_text("my own edit")
    ok, message, changed = utils.install_newest_release(str(repos.pi))
    assert (ok, changed) == (True, False) and "changes to the code" in message
    assert code(repos) == "my own edit"


def test_a_changed_config_doesnt_stop_it_and_is_kept(repos):
    release(repos, "v1.1.0", code="1.1")
    commit(repos, "unfinished work")
    git(repos.pi, "pull")
    (repos.pi / "config.json").write_text(json.dumps({"from": "user"}))
    assert utils.install_newest_release(str(repos.pi)) == (True, "Installed v1.1.0", True)
    assert json.loads((repos.pi / "config.json").read_text()) == {"from": "user"}


def test_no_releases_yet_is_not_ok(tmp_path):
    origin, pi = tmp_path / "origin.git", tmp_path / "map"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", str(origin), str(pi))
    (pi / "code.py").write_text("x")
    git(pi, "add", "-A")
    git(pi, "commit", "-m", "first")
    git(pi, "push", "-u", "origin", "main")
    assert utils.install_newest_release(str(pi)) == (False, "There are no releases on GitHub yet", False)


def test_a_folder_that_is_not_a_git_clone_is_not_ok(tmp_path):
    ok, message, changed = utils.install_newest_release(str(tmp_path))
    assert not ok and not changed and message


def test_github_cant_be_reached_is_not_ok(repos):
    git(repos.pi, "remote", "set-url", "origin", str(repos.origin) + "-missing")
    ok, message, changed = utils.install_newest_release(str(repos.pi))
    assert not ok and not changed and message


def test_install_sh_is_valid_bash():
    from pathlib import Path
    script = Path(__file__).parent.parent / "install.sh"
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    helped = subprocess.run(["bash", str(script), "--help"], capture_output=True, text=True)
    assert helped.returncode == 0 and "--latest" in helped.stdout
    bad = subprocess.run(["bash", str(script), "--nope"], capture_output=True, text=True)
    assert bad.returncode == 1 and "unknown option" in bad.stderr


# ---- versions ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, version", [("v2.8.4", (2, 8, 4)), ("2.8.4", (2, 8, 4)), ("v10.0.12", (10, 0, 12)),
                                           ("v2.9.0-rc1", None), ("nightly", None), ("v2.8", None), ("", None),
                                           (None, None)])
def test_parse_version(text, version):
    assert versions.parse(text) == version


def test_releases_newest_first():
    assert versions.releases(["v1.9.0", "nightly", "v1.10.0", "2.0.0", "v2.1.0-rc1"]) == ["2.0.0", "v1.10.0",
                                                                                       "v1.9.0"]


def test_is_newer():
    assert versions.is_newer("v2.8.5", "2.8.4") and not versions.is_newer("v2.8.4", "2.8.4")
    assert not versions.is_newer("v2.8.3", "2.8.4") and not versions.is_newer("nightly", "2.8.4")


# ---- the "update available" check -----------------------------------------------------------------------------

def check(repos, channel="releases", current="1.0.0"):
    return ReleaseCheck(str(repos.pi), channel=lambda: channel, current=current, clock=lambda: 0).check()


def test_check_finds_a_newer_release(repos):
    release(repos, "v1.1.0", code="1.1")
    release(repos, "v1.2.0-rc1", code="1.2 rc")
    releases = ReleaseCheck(str(repos.pi), channel=lambda: "releases", current="1.0.0", clock=lambda: 0)
    releases.load_build()
    state = releases.check()
    assert state["available"] == "v1.1.0" and state["error"] is None
    assert [r["tag"] for r in state["releases"]] == ["v1.1.0", "v1.0.0"]
    assert state["releases"][1] == {"tag": "v1.0.0", "running": True, "older": False}
    assert state["badge"] == "Update available: v1.1.0"
    assert state["commit"] == head(repos.pi)[:7]
    assert state["checked"] == "1970-01-01T00:00:00+00:00"


def test_check_up_to_date(repos):
    state = check(repos)
    assert state["available"] is None and state["badge"] is None


def test_check_lists_older_releases(repos):
    release(repos, "v1.1.0", code="1.1")
    state = check(repos, current="1.1.0")
    assert state["available"] is None
    assert state["releases"] == [{"tag": "v1.1.0", "running": True, "older": False},
                                 {"tag": "v1.0.0", "running": False, "older": True}]


def test_check_latest_channel(repos):
    assert check(repos, channel="latest")["available"] is None  # the map has GitHub's newest commit
    commit(repos, "unreleased")
    state = check(repos, channel="latest")
    assert state["available"] == head(repos.dev)[:7] and state["badge"] == "New commit available"


def test_check_latest_channel_ahead_of_github(repos):
    """A developer's copy with its own commits isn't behind."""
    (repos.pi / "code.py").write_text("mine")
    git(repos.pi, "commit", "-am", "local work")
    assert check(repos, channel="latest")["available"] is None


def test_check_failure_is_kept_not_raised(repos):
    git(repos.pi, "remote", "set-url", "origin", str(repos.origin) + "-missing")
    state = check(repos)
    assert state["error"] and state["available"] is None and state["checked"] is not None


def test_after_an_update_the_badge_says_restart():
    releases = ReleaseCheck(channel=lambda: "releases", git=lambda *args: None)
    releases.installed = "v1.1.0"
    assert releases.badge() == "Restart to use v1.1.0"


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
        return subprocess.CompletedProcess(cmd, 0, stdout="origin/main" if "symbolic-ref" in cmd else "ok", stderr="")
    monkeypatch.setattr(utils.subprocess, "run", fake_run)

    repo = tmp_path / "map"
    (repo / "sub").mkdir(parents=True)
    (repo / "config.json").write_text("{}")
    (repo / "airports.json").write_text("{}")
    (repo / "sub" / "file.py").write_text("")
    calls.repo = repo
    return calls


def test_git_runs_as_the_folder_owner(as_root):
    log = utils.update(str(as_root.repo), channel="latest")
    commands = [cmd[3:] for cmd, _ in as_root.run]
    assert [c for c in commands if c[0] != "rev-parse"] == [
        ["fetch", "origin"], ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], ["reset", "--hard"],
        ["checkout", "-B", "main", "origin/main"]]
    for cmd, kwargs in as_root.run:
        assert kwargs["user"] == 1000 and kwargs["group"] == 1000
        assert kwargs["env"]["HOME"] == "/home/pi"
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"  # never waits for a password
    assert "running git as pi" in log


def test_root_owned_files_are_given_back(as_root):
    utils.update(str(as_root.repo), channel="latest")
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


# ---- what's running (the header's version and "Unreleased" pill) -------------------------------------------------

def build(repos, version="1.0.0"):
    git(repos.pi, "fetch", "--tags")  # the map's clone was made before the fixture tagged v1.0.0
    return read_build(lambda *args: utils.run_git(str(repos.pi), *args), version)


def test_on_a_release(repos):
    b = build(repos)
    assert b["release"] and b["pill"] is None and b["tag"] == "v1.0.0" and b["ahead"] == 0
    assert b["chip"] == "v1.0.0" and b["describe"] == "v1.0.0" and b["commit"] == head(repos.pi)[:7]
    assert b["sha"] == head(repos.pi) and b["url"] is None  # the test "GitHub" is a folder


def test_commits_after_a_release(repos):
    commit(repos, "unreleased 1")
    commit(repos, "unreleased 2")
    git(repos.pi, "pull")
    b = build(repos)
    assert not b["release"] and b["ahead"] == 2
    assert b["pill"] == "Unreleased: 2 commits after v1.0.0"
    assert b["chip"] == f"v1.0.0 +2 · {head(repos.pi)[:7]}" and b["describe"] == "v1.0.0+2"


def test_settings_changes_dont_count_as_modified(repos):
    (repos.pi / "config.json").write_text(json.dumps({"from": "user"}))
    (repos.pi / "airports.json").write_text("{}")
    assert build(repos)["release"] and not build(repos)["modified"]


def test_local_code_changes(repos):
    (repos.pi / "code.py").write_text("copied over by hand")
    b = build(repos)
    assert b["modified"] and not b["release"]
    assert b["pill"] == "Modified: local changes to v1.0.0" and b["chip"].endswith("*")
    git(repos.pi, "checkout", "code.py")
    commit(repos, "next")
    git(repos.pi, "pull")
    (repos.pi / "code.py").write_text("copied over by hand, again")
    assert build(repos)["pill"] == "Unreleased: 1 commit after v1.0.0, with local changes"


def test_a_version_bump_that_isnt_tagged(repos):
    commit(repos, "Release 1.1.0")  # bumped and pushed, but not tagged
    git(repos.pi, "pull")
    assert build(repos, version="1.1.0")["pill"] == "Not tagged: v1.1.0 (1 commit after v1.0.0)"


def test_a_pre_release(repos):
    release(repos, "v1.1.0-rc1", code="rc")
    git(repos.pi, "pull")
    git(repos.pi, "fetch", "--tags")
    b = build(repos, version="1.1.0")
    assert not b["release"] and b["pill"] == "Pre-release: v1.1.0-rc1"


def test_no_release_tags(tmp_path):
    git(tmp_path, "init", "-b", "main", str(tmp_path / "map"))
    (tmp_path / "map" / "code.py").write_text("x")
    git(tmp_path / "map", "add", "-A")
    git(tmp_path / "map", "commit", "-m", "first")
    b = read_build(lambda *args: utils.run_git(str(tmp_path / "map"), *args), "1.0.0")
    assert b["tag"] is None and b["pill"] == "Unreleased: no release tag"
    assert b["describe"] == b["commit"] and b["chip"] == f"v1.0.0 · {b['commit']}"


def test_not_a_git_checkout(tmp_path):
    assert read_build(lambda *args: utils.run_git(str(tmp_path), *args), "1.0.0") is None
    assert read_build(lambda *args: None, "1.0.0") is None  # a git that can't run


def test_the_build_is_whats_running_not_whats_on_disk(repos):
    """An update changes the files before the restart; the header keeps saying what's running."""
    git(repos.pi, "fetch", "--tags")
    releases = ReleaseCheck(str(repos.pi), current="1.0.0")
    running = releases.load_build()["commit"]
    commit(repos, "newer")
    git(repos.pi, "pull")
    assert releases.state()["build"]["commit"] == running and releases.state()["commit"] == running
    assert head(repos.pi)[:7] != running


@pytest.mark.parametrize("remote, url", [
    ("https://github.com/dman776/metarmap2", "https://github.com/dman776/metarmap2"),
    ("https://github.com/dman776/metarmap2.git", "https://github.com/dman776/metarmap2"),
    ("git@github.com:dman776/metarmap2.git", "https://github.com/dman776/metarmap2"),
    ("ssh://git@github.com/dman776/metarmap2.git", "https://github.com/dman776/metarmap2"),
    ("/srv/git/metarmap2.git", None), ("https://gitlab.com/x/y.git", None), (None, None),
])
def test_github_url(remote, url):
    assert github_url(remote) == url
