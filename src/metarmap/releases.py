"""
What's newest on GitHub, for the web UI's "Update available" badge and the Config page's list of releases.

Updates install release tags (v2.8.4); the "latest" channel follows the newest commit instead, for testing. The
check only asks GitHub which tags and commits exist (git ls-remote): it downloads no code and changes no files.
"""
import os
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
        self._found = {"releases": [], "available": None, "commit": None, "checked": None, "error": None}
        self.installed = None  # what an update installed: it runs after the next restart

    def check(self):
        """Asks GitHub what's newest. Never raises: a failure is kept as state()["error"]. Returns state()."""
        channel = self._channel()
        try:
            tags = [line.split("refs/tags/", 1)[1] for line in self._run("ls-remote", "--tags", "--refs", "origin")
                    .splitlines() if "refs/tags/" in line]
            releases = versions.releases(tags)
            commit = self._run("rev-parse", "--short", "HEAD").strip() or None
            if channel == "latest":
                newest = (self._run("ls-remote", "origin", "HEAD").split() or [""])[0]
                # a commit this copy doesn't have, or doesn't include, is new
                have = newest and self._git("merge-base", "--is-ancestor", newest, "HEAD").returncode == 0
                available = newest[:7] if newest and not have else None
            else:
                available = releases[0] if releases and versions.is_newer(releases[0], self.current) else None
            found = {"releases": releases, "available": available, "commit": commit, "error": None}
        except CheckFailed as e:
            safe_log(f"[u]couldn't check GitHub for updates: {e}")
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
            "commit": found["commit"],
            "available": found["available"],
            "installed": self.installed,
            "badge": self.badge(),
            "releases": [{"tag": tag, "running": versions.same(tag, self.current),
                          "older": versions.is_newer(self.current, tag)} for tag in found["releases"]],
            "checked": datetime.fromtimestamp(checked, timezone.utc).isoformat() if checked is not None else None,
            "error": found["error"],
        }
