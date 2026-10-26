from datetime import datetime
import os
import sys
import subprocess
import shutil
import tempfile

import metarmap.lib.safe_logging as safe_logging


def wheel(pos):
    # Input a value 0 to 255 to get a color value.
    # The colours are a transition r - g - b - back to r.
    if pos < 0 or pos > 255:
        r = g = b = 0
    elif pos < 85:
        r = int(pos * 3)
        g = int(255 - pos * 3)
        b = 0
    elif pos < 170:
        pos -= 85
        r = int(255 - pos * 3)
        g = 0
        b = int(pos * 3)
    else:
        pos -= 170
        r = 0
        g = int(pos * 3)
        b = int(255 - pos * 3)
    return r, g, b


def get_location(city):
    import astral.geocoder
    import astral.sun
    try:
        return astral.geocoder.lookup(city, astral.geocoder.database())
    except KeyError:
        safe_logging.safe_log("Error: Location not recognized, please check list of supported cities and reconfigure")


def get_sun_times(city_name):
    import astral.geocoder
    import astral.sun

    try:
        city = get_location(city_name)
    except KeyError:
        safe_logging.safe_log("Error: Location not recognized, please check list of supported cities and reconfigure")
    else:
        safe_logging.safe_log("[u]" + str(city))
        sun = astral.sun.sun(city.observer, date=datetime.now().date(), tzinfo=city.timezone)
        # DAWN = sun['dawn']
        # SUNRISE = sun['sunrise']
        # SUNSET = sun['sunset']
        # DUSK = sun['dusk']
    # return DAWN, SUNRISE, SUNSET, DUSK
    return sun


def find_in_list(akey, avalue, alist):
    return list(filter(lambda alist: alist[akey] == avalue, alist))


def index_in_list(akey, alist):
    return list(alist.keys()).index(akey)


def get_proportion_between_floats(
    start: float,
    current: float,
    end: float
):
    """
    Gets the "distance" (0.0 to 1.0) between the start and the end where the current is.
    IE:
        If the Current is the same as Start, then the result will be 0.0
        If the Current is the same as the End, then the result will be 1.0
        If the Current is halfway between Start and End, then the result will be 0.5
    Arguments:
        start {float} -- The starting temp.
        current {float} -- The temp we want to get the proportion for.
        end {float} -- The end temp to calculate the interpolaton for.
    Returns:
        float -- The amount of interpolaton for Current between Start and End
    """

    total_delta = (end - start)
    time_in = (current - start)

    return time_in / total_delta


def celsius_to_fahrenheit(temperature_celsius: float):
    """
    Converts a temperature in celsius to fahrenheit.
    Args:
        temperature_celsius (float): A temperature in C
    Returns:
        [type]: The temperature converted to F
    """
    if temperature_celsius is None:
        return 0

    return (temperature_celsius * (9.0 / 5.0)) + 32.0


CONFIG_FILES = ("config.json", "airports.json")


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
    for dirpath, dirnames, filenames in os.walk(repo):
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
    return subprocess.run([shutil.which("git") or "/usr/bin/git", "-C", repo, *args],
                          capture_output=True, text=True, timeout=timeout, **{**owner, "env": env})


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


def run_update(repo=None, progress=None, channel="releases", version=None, current=None):
    """
    Updates the map's code from GitHub, keeping config.json and airports.json. Git runs as the owner of the folder,
    not root, so file ownership stays consistent.

    channel "releases": installs the newest release tag (v2.8.4), but only if it's newer than the running version
    (current; default this code's version), so an update never goes backwards. "latest": installs the newest commit
    on GitHub's default branch, released or not (for testing).
    version: a release tag to install whatever the channel, older or newer (picking a release by hand).
    progress: optional callback(fraction 0..1, label) for the web UI's progress bar.
    Returns an UpdateResult.
    """
    from metarmap import __version__
    from metarmap.lib import versions

    repo = repo or os.getcwd()
    current = current or __version__
    result = UpdateResult()

    def step(fraction, label):
        if progress:
            progress(fraction, label)

    def say(msg):
        safe_logging.safe_log("[u]" + msg)
        result.log.append("[u]" + msg)

    def fail(message):
        say(message)
        result.errors.append(message)

    def git(*args, quiet=False):
        try:
            done = run_git(repo, *args)
        except subprocess.TimeoutExpired:
            done = subprocess.CompletedProcess(args, 1, "", f"git {args[0]} took longer than {GIT_TIMEOUT} s")
        if not quiet:
            for text in (done.stdout.strip(), done.stderr.strip()):
                if text:
                    say(text)
        if done.returncode != 0 and not quiet:
            message = f"git {' '.join(args)} failed (exit code {done.returncode})"
            say(message)
            result.errors.append(done.stderr.strip() or message)
        return done

    step(0.0, "Starting")
    say(f"starting update ({'release ' + version if version else channel})... ")
    uid, gid = _repo_owner(repo)
    as_owner = _as_owner(uid, gid)
    if as_owner:
        step(0.05, "Checking file ownership")
        say(f"running git as {as_owner['env']['USER']}")
        fixed = _fix_ownership(repo, uid, gid)
        if fixed:
            say(f"gave {fixed} files back to {as_owner['env']['USER']}")
    before = git("rev-parse", "HEAD", quiet=True).stdout.strip()

    # what to install: a release tag, or the default branch's newest commit
    step(0.1, "Downloading the update")
    checkout = None
    if version or channel == "releases":
        ok = git("fetch", "--tags", "--force", "origin").returncode == 0
        if ok and version:
            if git("rev-parse", "--verify", "--quiet", f"refs/tags/{version}^{{commit}}", quiet=True).returncode:
                ok = False
                fail(f"{version} isn't a release on GitHub")
            else:
                checkout = ["-c", "advice.detachedHead=false", "checkout", version]
                result.target = version
        elif ok:
            newest = next(iter(versions.releases(git("tag", "--list", quiet=True).stdout.split())), None)
            if newest is None:
                ok = False
                fail("There are no releases on GitHub yet")
            elif versions.is_newer(newest, current):
                checkout = ["-c", "advice.detachedHead=false", "checkout", newest]
                result.target = newest
            else:
                result.message = f"Already on the newest release ({newest})"
                say(result.message)
    elif channel == "latest":
        ok = git("fetch", "origin").returncode == 0
        if ok:
            branch = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", quiet=True)
            if branch.returncode:  # a clone that doesn't know GitHub's default branch yet
                git("remote", "set-head", "origin", "--auto", quiet=True)
                branch = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", quiet=True)
            remote_branch = branch.stdout.strip()
            if branch.returncode or "/" not in remote_branch:
                ok = False
                fail("Couldn't find GitHub's default branch")
            else:
                checkout = ["checkout", "-B", remote_branch.split("/", 1)[1], remote_branch]
    else:
        ok = False
        fail(f"Unknown update channel {channel!r}")

    if ok and checkout:
        step(0.3, "Saving your settings")
        say("saving config files... ")
        saved = tempfile.mkdtemp(prefix="metarmap-update-")
        for name in CONFIG_FILES:
            if os.path.exists(os.path.join(repo, name)):
                shutil.copy2(os.path.join(repo, name), saved)

        step(0.45, "Resetting local changes")
        say("git reset... ")
        ok = git("reset", "--hard").returncode == 0
        if ok:
            step(0.6, f"Installing {result.target or 'the newest commit'}")
            say(f"installing {result.target or 'the newest commit'}...")
            ok = git(*checkout).returncode == 0

        step(0.9, "Restoring your settings")
        say("restoring config files... ")
        for name in CONFIG_FILES:
            backup = os.path.join(saved, name)
            if os.path.exists(backup):
                target = os.path.join(repo, name)
                shutil.copy2(backup, target)
                if as_owner:
                    os.chown(target, uid, gid)
        shutil.rmtree(saved, ignore_errors=True)

    result.ok = ok
    after = git("rev-parse", "HEAD", quiet=True).stdout.strip() if ok else before
    result.changed = ok and after != before
    if ok and channel == "latest" and not version:
        result.target = after[:7] or None
    if ok and not result.message:
        latest = channel == "latest" and not version
        if result.changed:
            result.message = f"Installed the newest commit ({result.target})" if latest else \
                f"Installed {result.target}"
        else:
            result.message = f"Already on the newest commit ({result.target})" if latest else \
                f"Already on {result.target}"
    say("update complete" if ok else "update FAILED; see the messages above")
    step(1.0, "Done" if ok else "Failed")
    return result


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
    src = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../src
    path = os.environ.get("PYTHONPATH")
    env = {**os.environ, "PYTHONPATH": src + (os.pathsep + path if path else "")}
    safe_logging.safe_log("[u]restarting... python -m metarmap")
    os.execve(sys.executable, [sys.executable, "-m", "metarmap", *sys.argv[1:]], env)


def is_pingable(site="www.aviationweather.gov"):
    return subprocess.run(["ping", "-c", "1", site], capture_output=True).returncode
