"""
Telling the network this map is here (zeroconf: mDNS and DNS-SD), so a Copilot, or another Chart's page, can find it
without being given an address. Each map announces a `_metarmap2._tcp` service named for the map, on the web UI's port.

The zeroconf package is optional. Without it the map runs as before and says so once; Home offers a button that
installs it (install_package), and the announcing starts right after, with no restart.
"""

import importlib
import logging
import socket
import subprocess
import sys
import threading
import time
import uuid

from metarmap import __version__

log = logging.getLogger(__name__)

SERVICE_TYPE = "_metarmap2._tcp.local."
PACKAGE = "zeroconf"
RECHECK_SECONDS = 60  # how long "not installed" is remembered, so a page load doesn't search the disk each time
INSTALL_TIMEOUT = 900  # seconds for pip: on a Pi Zero W it may build the package
API_PATH = "/api/status"  # in the announcement: where a client reads the map's state


def load_zeroconf():
    """The zeroconf module, or None when it isn't installed (or can't load)."""
    importlib.invalidate_caches()  # a package installed while the map runs
    try:
        return importlib.import_module(PACKAGE)
    except ImportError:
        return None
    except Exception as e:
        log.warning(f"{PACKAGE} is installed but doesn't load ({type(e).__name__}: {e})")
        return None


def host_name():
    """This computer's name without a domain: the default map name, and the host in the announcement."""
    return socket.gethostname().split(".")[0]


def host_label():
    """The host name in the announcement: this machine's own, so two Pis both called metarmap don't claim one."""
    return f"metarmap2-{uuid.getnode() & 0xFFFFFF:06x}"


def map_name(settings):
    """The name the map goes by on the network: web_server.name, else the computer's name."""
    return settings.web_server.name.strip() or host_name()


class Discovery:
    """
    Announces the map while web_server.announce is on and zeroconf is installed.
    config: has .data (Settings). load: returns the zeroconf module or None. address: returns this machine's IPv4
    address (tests pass their own).
    """

    def __init__(self, config, load=load_zeroconf, address=lambda: "127.0.0.1"):
        self._config = config
        self._load = load
        self._address = address
        self._lock = threading.Lock()
        self._zeroconf = None
        self._info = None
        self._said = False  # logged that zeroconf is missing
        self._module = None  # the zeroconf module once found
        self._missing_at = float("-inf")  # when it was last looked for and not found
        self.port = None  # the web server's port, known when it starts (run())
        self.announcing = False
        self._announced = None  # (address, name) of the announcement now
        self.registered_name = None  # the instance name as announced (zeroconf adds "-2" to one that's taken)

    def name(self):
        """The name this map goes by: as announced, else as set."""
        return self.registered_name if self.announcing and self.registered_name else map_name(self._config.data)

    def _zeroconf_module(self, fresh=False):
        """The zeroconf module or None. A miss is remembered for RECHECK_SECONDS unless `fresh`."""
        if self._module is None and (fresh or time.monotonic() - self._missing_at >= RECHECK_SECONDS):
            self._module = self._load()
            if self._module is None:
                self._missing_at = time.monotonic()
        return self._module

    def available(self):
        return self._zeroconf_module() is not None

    def state(self):
        """What the pages and /api/status say: is the package missing (the Home button), is the map announced."""
        wanted = self._config.data.web_server.announce
        available = self.available()
        return {
            "wanted": wanted,
            "available": available,
            "missing": wanted and not available,
            "announcing": self.announcing,
            "name": self.name(),
        }

    def start(self, port=None):
        """Announces the map, in the background (registering waits on the network). Does nothing when off."""
        if port is not None:
            self.port = port
        threading.Thread(target=self.restart, name="discovery", daemon=True).start()

    def refresh(self):
        """
        Called now and then: announces again, in the background, when the address changed (a new lease, another
        Wi-Fi) or the first try failed (no network yet). Does nothing when all is well, off, or without the package.
        """
        if not self._config.data.web_server.announce or self.port is None or not self.available():
            return
        try:
            address = self._address()
        except OSError:
            return
        if not self.announcing or self._announced != (address, map_name(self._config.data)):
            self.start()

    def restart(self):
        """Announces again with the name and port now (a changed name, or the package just installed)."""
        with self._lock:
            self._stop()
            settings = self._config.data
            if not settings.web_server.announce or self.port is None:
                return
            module = self._zeroconf_module(fresh=True)
            if module is None:
                if not self._said:
                    self._said = True
                    log.info(
                        f"{PACKAGE} isn't installed, so this map isn't announced on the network (Home installs it)"
                    )
                return
            try:
                name = map_name(settings)
                address = self._address()
                info = module.ServiceInfo(
                    SERVICE_TYPE,
                    f"{name}.{SERVICE_TYPE}",
                    addresses=[socket.inet_aton(address)],
                    port=self.port,
                    properties={"version": __version__, "path": API_PATH},
                    server=f"{host_label()}.local.",
                )
                zc = module.Zeroconf(ip_version=module.IPVersion.V4Only)
                self._zeroconf, self._info = zc, info
                zc.register_service(info, allow_name_change=True)  # another map with this name becomes "name-2"
                self.registered_name = info.name[: -len(SERVICE_TYPE) - 1]
                self._announced = (address, name)
                self.announcing = True
                log.info(f"announcing {self.registered_name!r} on the network (port {self.port})")
            except Exception as e:
                log.warning(f"can't announce the map on the network: {type(e).__name__}: {e}")
                self._stop()

    def stop(self):
        with self._lock:
            self._stop()

    def _stop(self):
        zc, info = self._zeroconf, self._info
        self._zeroconf = self._info = None
        self.announcing = False
        if zc is None:
            return
        try:
            if info is not None:
                zc.unregister_service(info)
            zc.close()
        except Exception as e:
            log.warning(f"stopping the announcement: {type(e).__name__}: {e}")


# pip's lines that say where it is -> (how far along, what the dialog says); the first match in a line wins
PIP_STAGES = (
    ("Collecting", 0.1, f"Looking up {PACKAGE}"),
    ("Downloading", 0.3, f"Downloading {PACKAGE}"),
    ("Using cached", 0.3, f"Using a cached {PACKAGE}"),
    ("Preparing metadata", 0.4, f"Preparing {PACKAGE}"),
    ("Building wheel", 0.5, f"Building {PACKAGE}, which can take minutes on a Pi Zero"),
    ("Installing collected packages", 0.8, f"Installing {PACKAGE}"),
    ("Successfully installed", 1.0, f"Installed {PACKAGE}"),
)
HEARTBEAT_SECONDS = 15  # while pip is quiet: a log line and the elapsed time in the dialog


class PackageInstall:
    """
    `pip install zeroconf` started from Home, in the background; the page polls progress() like an update's.
    Every line pip prints goes to the log ("pip: ..."), and the stage it reached and the time it has taken are in the
    job's label. popen: subprocess.Popen (tests pass a fake). on_done: called when it worked, to start announcing.
    """

    def __init__(self, popen=subprocess.Popen, on_done=None):
        self._popen = popen
        self.on_done = on_done
        self._lock = threading.Lock()
        self.job = None
        self._stage = ""  # the label for the stage pip is at, without the elapsed time

    def start(self):
        with self._lock:
            if self.job is None or self.job["done"]:
                self._stage = f"Starting pip for {PACKAGE}"
                job = self.job = {
                    "fraction": 0.0,
                    "label": f"Starting pip for {PACKAGE}",
                    "done": False,
                    "ok": None,
                    "changed": None,
                    "target": PACKAGE,
                    "message": "",
                    "errors": [],
                }
                threading.Thread(target=self._install, args=(job,), name="install-package", daemon=True).start()
            return self.job

    def progress(self):
        return self.job

    def _install(self, job):
        started = time.monotonic()
        finished = threading.Event()
        try:
            command = [sys.executable, "-m", "pip", "install", "--no-input", "--progress-bar", "off", PACKAGE]
            log.info(f"installing {PACKAGE}: {' '.join(command)}")
            process = self._popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            threading.Thread(
                target=self._watch, args=(job, process, started, finished), name="install-watch", daemon=True
            ).start()
            tail = []
            for line in process.stdout:
                line = line.rstrip()
                if not line:
                    continue
                log.info(f"pip: {line}")
                tail = (tail + [line])[-6:]
                for key, fraction, label in PIP_STAGES:
                    if line.startswith(key):
                        job.update(fraction=fraction, label=label)
                        self._stage = label
                        break
            code = process.wait()
            took = time.monotonic() - started
            job["ok"] = code == 0
            if job["ok"]:
                log.info(f"installed {PACKAGE} in {took:.0f} s")
                job.update(changed=True, message=f"Installed {PACKAGE}", fraction=1.0, label=f"Installed {PACKAGE}")
                if self.on_done:
                    self.on_done()
            else:
                log.warning(f"installing {PACKAGE} failed (pip exited with {code}) after {took:.0f} s")
                job.update(
                    changed=False, errors=job["errors"] or tail or [f"pip exited with {code}"]
                )  # or why it was stopped
        except Exception as e:
            log.exception(f"installing {PACKAGE} failed: {e}")
            job.update(ok=False, changed=False, errors=[f"{type(e).__name__}: {e}"])
        finally:
            finished.set()
            job["done"] = True

    def _watch(self, job, process, started, finished):
        """While pip runs: says it is still going every HEARTBEAT_SECONDS, and stops it after INSTALL_TIMEOUT."""
        while not finished.wait(HEARTBEAT_SECONDS):
            elapsed = time.monotonic() - started
            log.info(f"pip is still running ({elapsed:.0f} s): {job['label']}")
            job["label"] = f"{self._stage} ({elapsed:.0f} s)"
            if elapsed > INSTALL_TIMEOUT:
                log.warning(f"pip ran longer than {INSTALL_TIMEOUT} s: stopping it")
                job["errors"] = [f"pip took longer than {INSTALL_TIMEOUT // 60} minutes and was stopped"]
                process.kill()
                return
