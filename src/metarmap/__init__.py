"""MetarMap2: a Raspberry Pi METAR map with NeoPixel LEDs, an OLED screen and a web UI. Run it: python -m metarmap"""

import os


def _read_version():
    """
    The version is the newest release tag the code is at or after (v26.11.12 gives "26.11.12"): a release is made by
    tagging, with no number to set. Read from git, run as the checkout's owner like every other git command (a
    service running as root would otherwise be refused); without a checkout (an installed copy) from the package's
    metadata; "0+unknown" if neither knows. Pre-release tags (v26.11.12-rc1) aren't versions.
    """
    try:
        from metarmap import update

        done = update.run_git(
            os.path.dirname(os.path.abspath(__file__)),
            "describe",
            "--tags",
            "--abbrev=0",
            "--match",
            "v[0-9]*",
            "--exclude",
            "*-*",
            timeout=5,
        )
        if done.returncode == 0 and done.stdout.strip().startswith("v"):
            return done.stdout.strip()[1:]
    except Exception:  # no git, not a checkout, a timeout, a folder git can't read
        import logging

        logging.getLogger(__name__).debug("no version from git", exc_info=True)
    try:
        from importlib.metadata import version

        return version("metarmap2")
    except Exception:  # not installed (PackageNotFoundError)
        return "0+unknown"


__version__ = _read_version()

# who the map is, in every request to aviationweather.gov, the FAA's TFR list and adsb.fi
USER_AGENT = f"metarmap2/{__version__} (+https://github.com/dman776/metarmap2)"
