from datetime import datetime
import os
import sys
import subprocess
import shutil
import tempfile

try:
    import lib.safe_logging as safe_logging
except ModuleNotFoundError:
    import safe_logging as safe_logging


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


def get_sun_times(config):
    import astral.geocoder
    import astral.sun

    try:
        city = get_location(config.data.geo.city)
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


class UpdateResult:
    """What run_update() did: ok, whether the code changed, a log, and any git errors."""

    def __init__(self):
        self.ok = False
        self.changed = False
        self.log = []
        self.errors = []


def run_update(repo=None, progress=None):
    """
    Updates the map's code from GitHub (git reset --hard, then git pull), keeping config.json and airports.json.
    Git runs as the owner of the folder, not root, so file ownership stays consistent.

    progress: optional callback(fraction 0..1, label) for the web UI's progress bar.
    Returns an UpdateResult.
    """
    repo = repo or os.getcwd()
    result = UpdateResult()

    def step(fraction, label):
        if progress:
            progress(fraction, label)

    def say(msg):
        safe_logging.safe_log("[u]" + msg)
        result.log.append("[u]" + msg)

    def git(*args, quiet=False):
        done = subprocess.run([shutil.which("git") or "/usr/bin/git", "-C", repo, *args],
                              capture_output=True, text=True, **as_owner)
        if not quiet:
            for text in (done.stdout.strip(), done.stderr.strip()):
                if text:
                    say(text)
        if done.returncode != 0:
            message = f"git {' '.join(args)} failed (exit code {done.returncode})"
            say(message)
            result.errors.append(done.stderr.strip() or message)
        return done

    step(0.0, "Starting")
    say("starting update... ")
    uid, gid = _repo_owner(repo)
    as_owner = _as_owner(uid, gid)
    if as_owner:
        step(0.05, "Checking file ownership")
        say(f"running git as {as_owner['env']['USER']}")
        fixed = _fix_ownership(repo, uid, gid)
        if fixed:
            say(f"gave {fixed} files back to {as_owner['env']['USER']}")
    before = git("rev-parse", "HEAD", quiet=True).stdout.strip()

    step(0.15, "Saving your settings")
    say("saving config files... ")
    saved = tempfile.mkdtemp(prefix="metarmap-update-")
    for name in CONFIG_FILES:
        if os.path.exists(os.path.join(repo, name)):
            shutil.copy2(os.path.join(repo, name), saved)

    step(0.25, "Resetting local changes")
    say("git reset... ")
    ok = git("reset", "--hard").returncode == 0
    if ok:
        step(0.4, "Downloading the update")
        say("updating from github...")
        ok = git("pull").returncode == 0

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
    result.changed = ok and git("rev-parse", "HEAD", quiet=True).stdout.strip() != before
    say("update complete" if ok else "update FAILED; see the messages above")
    step(1.0, "Done" if ok else "Failed")
    return result


def update(repo=None):
    """
    Runs the update and returns its log as HTML (used by GET /update and the Home Assistant integration).
    """
    return "".join(line + "<br />" for line in run_update(repo).log)


def restart():
    safe_logging.safe_log("[u]restarting... " + os.path.abspath(sys.argv[0]))
    os.execl(sys.executable, os.path.abspath(sys.argv[0]), *sys.argv)


def is_pingable(site="www.aviationweather.gov"):
    return subprocess.run(["ping", "-c", "1", site], capture_output=True).returncode
