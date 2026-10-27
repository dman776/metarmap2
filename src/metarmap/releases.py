"""
What's newest on GitHub, for the web UI's "Update available" badge and the Config page's list of releases.

Updates install release tags (v2.8.4); the "latest" channel follows the newest commit instead, for testing. The
check only asks GitHub which tags and commits exist (git ls-remote): it downloads no code and changes no files.

Also what's running (read_build): a release, or commits after one, so a map running unreleased code says so.
"""
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone

from metarmap import __version__
from metarmap.lib import utils, versions
from metarmap.lib.safe_logging import safe_log

CHECK_HOURS = 6  # how often the map asks GitHub
CHECK_TIMEOUT = 30  # seconds


class CheckFailed(Exception):
    pass


# the files every map changes; edits to them aren't changes to the code
SETTINGS_FILES = ("config.json", "airports.json")


def github_url(remote):
    """https://github.com/owner/repo for a GitHub remote (https or ssh), else None."""
    match = re.match(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/\s]+/[^/\s]+?)(?:\.git)?/?$",
                     str(remote or "").strip())
    return f"https://github.com/{match.group(1)}" if match else None


def read_build(git, version):
    """
    What's running, from git: the release tag it's at or after, how many commits after it, the commit, and whether
    the code was changed locally (config.json and airports.json don't count). None outside a git checkout.
    git: runs a git command and returns the CompletedProcess. version: the running version (2.9.2).
    """
    def out(*args):
        try:
            done = git(*args)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done is not None and done.returncode == 0 else None

    sha = out("rev-parse", "HEAD")
    described = out("describe", "--tags", "--long", "--always", "--abbrev=7", "--match", "v[0-9]*", "--match", "[0-9]*")
    if not sha or not described:
        return None
    match = re.match(r"^(.+)-(\d+)-g[0-9a-f]+$", described)  # v2.9.2-3-g5c3e5a5; just the commit if no tag
    tag, ahead = (match.group(1), int(match.group(2))) if match else (None, 0)
    try:
        diff = git("diff", "--quiet", "HEAD", "--", ".", *(f":!{name}" for name in SETTINGS_FILES))
        modified = diff is not None and diff.returncode == 1
    except (OSError, subprocess.SubprocessError):
        modified = False
    base = github_url(out("remote", "get-url", "origin"))
    commit = sha[:7]
    prerelease = tag is not None and versions.parse(tag) is None  # v2.9.0-rc1
    release = tag is not None and not prerelease and ahead == 0 and not modified
    # the version was bumped (and maybe committed) but that version has no tag yet
    untagged = (tag is not None and not prerelease and versions.parse(version) is not None
                and not versions.same(tag, version))

    if release:
        pill = None
    elif prerelease:
        pill = f"Pre-release: {tag}" + (f" +{ahead}" if ahead else "")
    elif untagged:
        after = f" ({ahead} commit{'' if ahead == 1 else 's'} after {tag})" if ahead else ""
        pill = f"Not tagged: v{version}{after}"
    elif tag is None:
        pill = "Unreleased: no release tag"
    elif ahead:
        pill = f"Unreleased: {ahead} commit{'' if ahead == 1 else 's'} after {tag}"
    else:
        pill = f"Modified: local changes to {tag}"
    if pill and modified and not pill.startswith("Modified"):
        pill += ", with local changes"
    return {
        "tag": tag,
        "ahead": ahead,
        "commit": commit,
        "sha": sha,
        "modified": modified,
        "release": release,
        "untagged": untagged,
        "describe": (tag if not ahead else f"{tag}+{ahead}") if tag else commit,
        "chip": f"v{version}" if release else f"v{version}{f' +{ahead}' if ahead else ''} · {commit}"
                                              f"{'*' if modified else ''}",
        "pill": pill,
        "url": f"{base}/commit/{sha}" if base else None,
    }


class ReleaseCheck:
    """
    channel: returns the update channel now ("releases" or "latest"), so a change in Config applies at once.
    git: runs a git command in the map's folder and returns the CompletedProcess (tests pass their own).
    """

    def __init__(self, repo=None, channel=lambda: "releases", current=__version__, git=None, clock=time.time):
        self._repo = repo or os.getcwd()
        self._channel = channel
        self.current = current
        self._git = git or (lambda *args: utils.run_git(self._repo, *args, timeout=CHECK_TIMEOUT))
        self._clock = clock
        self._lock = threading.Lock()
        self._found = {"releases": [], "available": None, "checked": None, "error": None}
        self.installed = None  # what an update installed: it runs after the next restart
        self.build = None  # what's running: load_build() reads it once, when the map starts

    def load_build(self):
        """
        Reads what's running (see read_build). Called once when the map starts: an update changes the files on disk
        before the restart, and the header should keep saying what's actually running.
        """
        self.build = read_build(self._git, self.current)
        return self.build

    def check(self):
        """Asks GitHub what's newest. Never raises: a failure is kept as state()["error"]. Returns state()."""
        channel = self._channel()
        try:
            tags = [line.split("refs/tags/", 1)[1] for line in self._run("ls-remote", "--tags", "--refs", "origin")
                    .splitlines() if "refs/tags/" in line]
            releases = versions.releases(tags)
            if channel == "latest":
                newest = (self._run("ls-remote", "origin", "HEAD").split() or [""])[0]
                # a commit this copy doesn't have, or doesn't include, is new
                have = newest and self._git("merge-base", "--is-ancestor", newest, "HEAD").returncode == 0
                available = newest[:7] if newest and not have else None
            else:
                available = releases[0] if releases and versions.is_newer(releases[0], self.current) else None
            found = {"releases": releases, "available": available, "error": None}
        except CheckFailed as e:
            safe_log(f"couldn't check GitHub for updates: {e}")
            found = {**self._found, "error": str(e)}
        found["checked"] = self._clock()
        with self._lock:
            self._found = found
        return self.state()

    def check_soon(self):
        """Checks in the background (GitHub can be slow; the LEDs and the web UI don't wait)."""
        threading.Thread(target=self.check, name="release-check", daemon=True).start()

    def _run(self, *args):
        try:
            done = self._git(*args)
        except (OSError, subprocess.SubprocessError) as e:
            raise CheckFailed(str(e)) from None
        if done.returncode != 0:
            raise CheckFailed(done.stderr.strip() or f"git {args[0]} failed")
        return done.stdout

    def badge(self):
        """The header's note, or None: there's an update to install, or one is installed and needs a restart."""
        found = self._found
        if self.installed:
            return f"Restart to use {self.installed}"
        if found["available"]:
            return "New commit available" if self._channel() == "latest" else f"Update available: {found['available']}"
        return None

    def state(self):
        """For the web UI and /api/status."""
        with self._lock:
            found = dict(self._found)
        checked = found["checked"]
        return {
            "current": self.current,
            "channel": self._channel(),
            "commit": self.build["commit"] if self.build else None,  # running
            "build": self.build,
            "available": found["available"],
            "installed": self.installed,
            "badge": self.badge(),
            "releases": [{"tag": tag, "running": versions.same(tag, self.current),
                          "older": versions.is_newer(self.current, tag)} for tag in found["releases"]],
            "checked": datetime.fromtimestamp(checked, timezone.utc).isoformat() if checked is not None else None,
            "error": found["error"],
        }
