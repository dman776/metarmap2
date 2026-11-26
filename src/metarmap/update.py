"""
Updating the map's code from GitHub: run_update() installs the newest release (or commit, or branch) while keeping
config.json (airports.json isn't in git), run_git() is how git runs (as the folder's owner, never asking for a
password), install_newest_release() is for install.sh, and restart() loads the new code. What's newest is releases.py's.
"""

import json
import logging
import os
import shutil
import subprocess
import sys

from metarmap.lib import versions
from metarmap.settings import BRANCH_NAME

log = logging.getLogger(__name__)

CONFIG_FILES = ("config.json", "airports.json")  # what the code-changed check ignores
BACKUP_SUFFIX = ".update-backup"  # config.json's copy beside it while an update runs


def _repo_owner(repo):
    st = os.stat(repo)
    return st.st_uid, st.st_gid


def _as_owner(uid, gid):
    """
    Extra subprocess.run() arguments that run a command as the repo's owner (e.g. pi) when the map runs as root,
    so files git creates belong to that user. Empty when there's no need to switch user.
    """
    if os.geteuid() != 0 or uid == 0:
        return {}
    import pwd

    account = pwd.getpwuid(uid)
    env = {**os.environ, "HOME": account.pw_dir, "USER": account.pw_name, "LOGNAME": account.pw_name}
    return {"user": uid, "group": gid, "env": env}


def _fix_ownership(repo, uid, gid):
    """
    Gives files that earlier updates (run as root) left owned by root back to the repo's owner.
    Returns how many were changed.
    """
    if os.geteuid() != 0 or uid == 0:
        return 0
    changed = 0
    for dirpath, _dirnames, filenames in os.walk(repo):
        for path in [dirpath] + [os.path.join(dirpath, f) for f in filenames]:
            st = os.lstat(path)
            if (st.st_uid, st.st_gid) != (uid, gid):
                os.lchown(path, uid, gid)
                changed += 1
    return changed


GIT_TIMEOUT = 300  # seconds; a download that takes longer has stalled


def run_git(repo, *args, timeout=GIT_TIMEOUT):
    """
    Runs git in `repo` as the folder's owner (see _as_owner), never stopping to ask for a password.
    Returns the CompletedProcess; raises subprocess.TimeoutExpired if git takes longer than `timeout`.
    """
    owner = _as_owner(*_repo_owner(repo))
    env = {**owner.get("env", os.environ), "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        [shutil.which("git") or "/usr/bin/git", "-C", repo, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        **{**owner, "env": env},
    )


class UpdateResult:
    """
    What run_update() did: ok, whether the code changed, what it installed (target: a release tag, or the commit on
    the latest channel), a one-line message for the web UI, a log, and any git errors.
    """

    def __init__(self):
        self.ok = False
        self.changed = False
        self.target = None
        self.message = ""
        self.log = []
        self.errors = []


class _Update:
    """One run of run_update(): the options, the UpdateResult it fills in, and a method for each stage."""

    def __init__(self, repo, progress, channel, version, current, branch):
        self.repo = repo
        self.progress = progress
        self.channel = channel
        self.version = version
        self.current = current
        self.branch = branch
        self.result = UpdateResult()
        self.uid = self.gid = 0
        self.as_owner = {}

    def step(self, fraction, label):
        if self.progress:
            self.progress(fraction, label)

    def say(self, msg):
        log.info(msg)
        self.result.log.append("[u]" + msg)

    def fail(self, message):
        self.say(message)
        self.result.errors.append(message)

    def git(self, *args, quiet=False):
        try:
            done = run_git(self.repo, *args)
        except subprocess.TimeoutExpired:
            done = subprocess.CompletedProcess(args, 1, "", f"git {args[0]} took longer than {GIT_TIMEOUT} s")
        if not quiet:
            for text in (done.stdout.strip(), done.stderr.strip()):
                if text:
                    self.say(text)
        if done.returncode != 0 and not quiet:
            message = f"git {' '.join(args)} failed (exit code {done.returncode})"
            self.say(message)
            self.result.errors.append(done.stderr.strip() or message)
        return done

    def start(self):
        self.step(0.0, "Starting")
        what = (
            f"release {self.version}"
            if self.version
            else f"branch {self.branch}"
            if self.channel == "branch"
            else self.channel
        )
        self.say(f"starting update ({what})... ")
        self.uid, self.gid = _repo_owner(self.repo)
        self.as_owner = _as_owner(self.uid, self.gid)
        if self.as_owner:
            user = self.as_owner["env"]["USER"]
            self.step(0.05, "Checking file ownership")
            self.say(f"running git as {user}")
            fixed = _fix_ownership(self.repo, self.uid, self.gid)
            if fixed:
                self.say(f"gave {fixed} files back to {user}")

    def pick_checkout(self):
        """What to install: a release tag, or the default branch's newest commit. Returns (ok, git checkout args)."""
        self.step(0.1, "Downloading the update")
        if self.version or self.channel == "releases":
            return self._release_checkout()
        if self.channel == "latest":
            return self._latest_checkout()
        if self.channel == "branch":
            return self._branch_checkout()
        self.fail(f"Unknown update channel {self.channel!r}")
        return False, None

    def _release_checkout(self):
        result = self.result
        if self.git("fetch", "--tags", "--force", "origin").returncode:
            return False, None
        if self.version:
            if self.git(
                "rev-parse", "--verify", "--quiet", f"refs/tags/{self.version}^{{commit}}", quiet=True
            ).returncode:
                self.fail(f"{self.version} isn't a release on GitHub")
                return False, None
            result.target = self.version
            return True, ["-c", "advice.detachedHead=false", "checkout", self.version]
        newest = next(iter(versions.releases(self.git("tag", "--list", quiet=True).stdout.split())), None)
        if newest is None:
            self.fail("There are no releases on GitHub yet")
            return False, None
        if versions.is_newer(newest, self.current):
            result.target = newest
            return True, ["-c", "advice.detachedHead=false", "checkout", newest]
        result.message = f"Already on the newest release ({newest})"
        self.say(result.message)
        return True, None

    def _latest_checkout(self):
        if self.git("fetch", "origin").returncode:
            return False, None
        head = self.git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", quiet=True)
        if head.returncode:  # a clone that doesn't know GitHub's default branch yet
            self.git("remote", "set-head", "origin", "--auto", quiet=True)
            head = self.git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", quiet=True)
        remote_branch = head.stdout.strip()
        if head.returncode or "/" not in remote_branch:
            self.fail("Couldn't find GitHub's default branch")
            return False, None
        return True, ["checkout", "-B", remote_branch.split("/", 1)[1], remote_branch]

    def _branch_checkout(self):
        branch = self.branch
        if not branch or not BRANCH_NAME.match(branch):
            self.fail("Pick a branch to update from" if not branch else f"{branch!r} isn't a branch name")
            return False, None
        # --prune: a branch deleted on GitHub is gone here too
        if self.git("fetch", "--prune", "origin").returncode:
            return False, None
        if self.git("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", quiet=True).returncode:
            self.fail(f"There's no branch {branch} on GitHub")
            return False, None
        return True, ["checkout", "-B", branch, f"origin/{branch}"]

    def install(self, checkout):
        """Checks out `checkout` with config.json kept as it was. Returns whether it worked."""
        target = self.result.target or "the newest commit"
        config = os.path.join(self.repo, "config.json")
        backup = config + BACKUP_SUFFIX
        # config.json is tracked, so the reset and checkout would overwrite it. The copy sits beside it (a reboot
        # can't clear it, as it could in /tmp) and goes back in a finally, so an exception can't lose the settings;
        # if the power fails, the next update puts it back (recover). airports.json is ignored by git: untouched.
        self.step(0.3, "Saving your settings")
        self.say("saving config.json... ")
        self.recover(config, backup)
        has_config = os.path.exists(config)
        if has_config:
            self.copy_whole(config, backup)
        restored = True
        try:
            self.step(0.45, "Resetting local changes")
            self.say("git reset... ")
            ok = self.git("reset", "--hard").returncode == 0
            if ok:
                self.step(0.6, f"Installing {target}")
                self.say(f"installing {target}...")
                ok = self.git(*checkout).returncode == 0
        finally:
            self.step(0.9, "Restoring your settings")
            self.say("restoring config.json... ")
            if has_config:
                restored = self.restore(config, backup)
        return ok and restored

    def copy_whole(self, source, destination):
        """Copies a file so that `destination` is always whole: written beside it, then swapped in."""
        partial = destination + ".tmp"
        shutil.copy2(source, partial)
        if self.as_owner:
            os.chown(partial, self.uid, self.gid)
        os.replace(partial, destination)

    def restore(self, config, backup):
        """Puts the copy back as config.json and removes it. If that fails the copy stays, and it says so."""
        try:
            self.copy_whole(backup, config)
            os.remove(backup)
        except OSError as e:
            self.fail(f"Couldn't put your settings back ({e}); they are in {os.path.basename(backup)}")
            return False
        return True

    def recover(self, config, backup):
        """
        A copy left by an update that died before it could restore (a power cut). It goes back only if it is whole
        (valid JSON) and the update really did reset config.json (it is missing or is the repo's own copy): after a
        power cut right after the copy, config.json is still the user's, and may have changed since.
        """
        if not os.path.exists(backup):
            return
        try:
            with open(backup) as f:
                json.load(f)
            committed = self.git("show", "HEAD:config.json", quiet=True).stdout
            if os.path.exists(config):
                with open(config) as f:
                    reset = f.read() == committed
            else:
                reset = True
        except (OSError, ValueError):
            log.warning("Found %s from an update that didn't finish, but it can't be read; leaving it", backup)
            return
        if not reset:
            log.warning("Found %s from an update that didn't finish; config.json has changed since: leaving it", backup)
            return
        log.warning("Found %s from an update that didn't finish; restoring it", backup)
        self.say("restoring the settings an earlier update left behind... ")
        self.restore(config, backup)

    def finish(self, ok, before):
        """Fills in the result: whether the code changed, and the message for the web UI."""
        result = self.result
        result.ok = ok
        after = self.git("rev-parse", "HEAD", quiet=True).stdout.strip() if ok else before
        result.changed = ok and after != before
        latest = self.channel in ("latest", "branch") and not self.version
        if ok and latest:
            result.target = after[:7] or None
        if ok and not result.message:
            newest = f"the newest commit{' of ' + self.branch if self.channel == 'branch' else ''} ({result.target})"
            if result.changed:
                result.message = f"Installed {newest}" if latest else f"Installed {result.target}"
            else:
                result.message = f"Already on {newest}" if latest else f"Already on {result.target}"
        self.say("update complete" if ok else "update FAILED; see the messages above")
        self.step(1.0, "Done" if ok else "Failed")
        return result


def run_update(repo=None, progress=None, channel="releases", version=None, current=None, branch=None):
    """
    Updates the map's code from GitHub, keeping config.json (airports.json isn't in git). Git runs as the owner of the
    folder, not root, so file ownership stays consistent.

    channel "releases": installs the newest release tag (v2.8.4), but only if it's newer than the running version
    (current; default this code's version), so an update never goes backwards. "latest": installs the newest commit
    on GitHub's default branch, released or not (for testing). "branch": the newest commit on `branch` (dev_mode),
    even if that branch was force-pushed.
    version: a release tag to install whatever the channel, older or newer (picking a release by hand).
    progress: optional callback(fraction 0..1, label) for the web UI's progress bar.
    Returns an UpdateResult.
    """
    from metarmap import __version__  # here, not at the top: metarmap/__init__.py imports this module to read it

    update = _Update(repo or os.getcwd(), progress, channel, version, current or __version__, branch)
    update.start()
    before = update.git("rev-parse", "HEAD", quiet=True).stdout.strip()
    ok, checkout = update.pick_checkout()
    if ok and checkout:
        ok = update.install(checkout)
    return update.finish(ok, before)


def install_newest_release(repo):
    """
    For install.sh: puts a fresh clone on the newest release (a tag such as v2.9.2) instead of the newest commit of
    the branch it was cloned from. Returns (ok, message, changed): changed is whether the code on disk changed.

    It leaves the folder as it is (ok, with the reason in the message) if it's already on a release (one picked by
    hand, over SSH or on the web UI, stays), if update.channel in config.json is "latest" or (with dev_mode)
    "branch" (a map for testing), or if
    the code has changes (config.json and airports.json aside). Not ok: GitHub couldn't be reached, or has no releases.
    """
    try:
        with open(os.path.join(repo, "config.json")) as f:
            data = json.load(f)
        channel = data.get("update", {}).get("channel")
        dev_mode = data.get("dev_mode") is True
    except (OSError, ValueError, AttributeError):
        channel, dev_mode = None, False
    if channel == "latest":
        return True, "Update channel is Latest commit: staying on the newest commit", False
    if channel == "branch" and dev_mode:
        return True, "Update channel is Branch (dev_mode): staying on this commit", False

    try:
        at_head = versions.releases(run_git(repo, "tag", "--points-at", "HEAD").stdout.split())
        edited = run_git(repo, "diff", "--quiet", "HEAD", "--", ".", *(f":!{name}" for name in CONFIG_FILES))
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e), False
    if at_head:
        return True, f"Already on release {at_head[0]}", False
    if edited.returncode == 1:
        return True, "This folder has changes to the code, so it's left as it is", False

    result = run_update(repo, channel="releases", current="0")  # "0": older than any release, so the newest installs
    if not result.ok:
        return False, (result.errors or ["the update failed"])[0], False
    return True, result.message, result.changed


def update(repo=None, **kwargs):
    """
    Runs the update and returns its log as HTML (used by GET /update and the Home Assistant integration).
    kwargs: run_update()'s channel, version and current.
    """
    return "".join(line + "<br />" for line in run_update(repo, **kwargs).log)


def restart():
    """
    Replaces this process with a fresh `python -m metarmap`, so an update's new code is loaded.
    The package's folder goes on PYTHONPATH, so this works however the map was started (controller.py, -m, or
    an installed package).
    """
    src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../src
    path = os.environ.get("PYTHONPATH")
    env = {**os.environ, "PYTHONPATH": src + (os.pathsep + path if path else "")}
    log.info("restarting... python -m metarmap")
    os.execve(sys.executable, [sys.executable, "-m", "metarmap", *sys.argv[1:]], env)
