"""Tests for announcing the map on the network, with a stand-in for the zeroconf package."""

import logging
import threading
from types import SimpleNamespace

import pytest

from metarmap import discovery
from metarmap.settings import Settings


class FakeZeroconf:
    """Just what Discovery uses of the zeroconf module; it records what was registered."""

    registered, unregistered, closed = [], [], []

    class IPVersion:
        V4Only = "v4"

    class ServiceInfo:
        def __init__(self, type_, name, addresses, port, properties, server):
            self.type, self.name, self.addresses, self.port = type_, name, addresses, port
            self.properties, self.server = properties, server

    class Zeroconf:
        def __init__(self, ip_version=None):
            self.ip_version = ip_version

        def register_service(self, info, allow_name_change=False):
            FakeZeroconf.registered.append((info, allow_name_change))

        def unregister_service(self, info):
            FakeZeroconf.unregistered.append(info)

        def close(self):
            FakeZeroconf.closed.append(self)


@pytest.fixture(autouse=True)
def fresh_fake():
    FakeZeroconf.registered, FakeZeroconf.unregistered, FakeZeroconf.closed = [], [], []


@pytest.fixture
def config():
    settings = Settings()
    settings.web_server.name = "Houston map"
    return SimpleNamespace(data=settings)


def make(config, module=FakeZeroconf):
    return discovery.Discovery(config, load=lambda: module, address=lambda: "10.0.0.2")


def test_announces_the_map_by_name(config):
    d = make(config)
    d.port = 8080
    d.restart()
    info, allow_change = FakeZeroconf.registered[0]
    assert info.type == "_metarmap2._tcp.local." and info.name == "Houston map._metarmap2._tcp.local."
    assert info.addresses == [bytes([10, 0, 0, 2])] and info.port == 8080 and allow_change
    assert info.properties["path"] == "/api/status"
    assert "password" not in info.properties and "user" not in info.properties  # nothing to log in with
    assert info.server.startswith("metarmap2-") and info.server.endswith(".local.")  # not the computer's own name
    assert d.announcing and d.state()["announcing"]


def test_the_name_defaults_to_the_computers(config, monkeypatch):
    monkeypatch.setattr(discovery.socket, "gethostname", lambda: "metarmap.local")
    config.data.web_server.name = "  "
    d = make(config)
    d.port = 80
    d.restart()
    assert FakeZeroconf.registered[0][0].name == "metarmap._metarmap2._tcp.local."


def test_a_new_name_announces_again_and_stop_withdraws(config):
    d = make(config)
    d.port = 80
    d.restart()
    config.data.web_server.name = "Dallas map"
    d.restart()
    assert [i.name for i, _ in FakeZeroconf.registered] == [
        "Houston map._metarmap2._tcp.local.",
        "Dallas map._metarmap2._tcp.local.",
    ]
    assert len(FakeZeroconf.unregistered) == 1 and len(FakeZeroconf.closed) == 1
    d.stop()
    assert len(FakeZeroconf.unregistered) == 2 and not d.announcing


def test_nothing_is_announced_when_off_or_before_the_port_is_known(config):
    d = make(config)
    d.restart()  # no port yet
    config.data.web_server.announce = False
    d.port = 80
    d.restart()
    assert FakeZeroconf.registered == [] and not d.announcing


def test_without_the_package_it_runs_on_and_says_it_is_missing(config, caplog):
    caplog.set_level(logging.INFO)
    d = make(config, module=None)
    d.port = 80
    d.restart()
    d.restart()
    assert not d.announcing and not d.available()
    assert d.state()["missing"] is True
    assert sum("isn't installed" in r.message for r in caplog.records) == 1  # said once
    config.data.web_server.announce = False
    assert d.state()["missing"] is False  # switched off: nothing to install


def test_a_missing_package_is_looked_for_once_a_minute(config, monkeypatch):
    looked = []
    d = discovery.Discovery(config, load=lambda: looked.append(1))
    now = [1000.0]
    monkeypatch.setattr(discovery.time, "monotonic", lambda: now[0])
    d.available()
    d.available()
    assert len(looked) == 1
    now[0] += discovery.RECHECK_SECONDS
    d.available()
    assert len(looked) == 2


def test_a_failing_registration_is_logged_not_raised(config, caplog):
    class Broken(FakeZeroconf):
        class Zeroconf(FakeZeroconf.Zeroconf):
            def register_service(self, info, allow_name_change=False):
                raise OSError("no network")

    d = make(config, module=Broken)
    d.port = 80
    d.restart()
    assert not d.announcing and "no network" in caplog.text


class FakePip:
    """A pip process: prints its lines, then exits with a code."""

    def __init__(self, lines, code=0):
        self.lines, self.code, self.killed, self.command = lines, code, False, None

    def __call__(self, command, **kwargs):
        self.command = command
        self.stdout = iter(line + "\n" for line in self.lines)
        return self

    def wait(self):
        return self.code

    def kill(self):
        self.killed = True


def finished(job):
    for _ in range(300):
        if job["done"]:
            return job
        threading.Event().wait(0.01)
    return job


def test_install_runs_pip_logs_what_it_says_and_then_announces(caplog):
    caplog.set_level(logging.INFO)
    done = threading.Event()
    pip = FakePip(
        [
            "Collecting zeroconf",
            "  Downloading zeroconf-0.154.0-py3-none-any.whl (100 kB)",
            "Installing collected packages: ifaddr, zeroconf",
            "Successfully installed ifaddr-0.2.0 zeroconf-0.154.0",
        ]
    )
    job = discovery.PackageInstall(popen=pip, on_done=done.set).start()
    assert done.wait(5) and finished(job)["ok"]
    assert pip.command[1:4] == ["-m", "pip", "install"] and pip.command[-1] == "zeroconf"
    assert job["changed"] and job["message"] == "Installed zeroconf" and job["fraction"] == 1.0
    assert "pip: Collecting zeroconf" in caplog.text and "pip: Successfully installed" in caplog.text
    assert "installed zeroconf in" in caplog.text


def test_install_label_follows_pips_stages():
    seen = []
    install = discovery.PackageInstall()

    class Slow(FakePip):
        def __call__(self, command, **kwargs):
            super().__call__(command, **kwargs)
            lines = self.stdout

            def watching():
                for line in lines:
                    yield line
                    seen.append(install.job["label"])

            self.stdout = watching()
            return self

    pip = Slow(
        ["Collecting zeroconf", "Building wheel for zeroconf (pyproject.toml)", "Successfully installed zeroconf-1"]
    )
    install._popen = pip
    job = install.start()
    assert finished(job)["ok"]
    assert seen[0] == "Looking up zeroconf" and seen[1].startswith("Building zeroconf, which can take minutes")


def test_install_failure_shows_pips_last_lines_and_logs_it(caplog):
    pip = FakePip([f"line {n}" for n in range(10)], code=1)
    job = discovery.PackageInstall(popen=pip, on_done=lambda: pytest.fail("announced after a failure")).start()
    assert finished(job)["ok"] is False and job["errors"][-1] == "line 9" and len(job["errors"]) == 6
    assert "pip exited with 1" in caplog.text


def test_install_that_cannot_run_is_reported():
    def popen(command, **kwargs):
        raise FileNotFoundError("no python")

    job = discovery.PackageInstall(popen=popen).start()
    assert finished(job)["ok"] is False and "no python" in job["errors"][0]


def test_a_quiet_pip_gets_a_heartbeat_and_a_stop_after_the_time_limit(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(discovery, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(discovery, "INSTALL_TIMEOUT", 0.03)
    release = threading.Event()

    class Quiet(FakePip):
        def __call__(self, command, **kwargs):
            super().__call__(command, **kwargs)
            self.stdout = iter(())
            return self

        def wait(self):
            release.wait(2)  # pip hangs until it is killed
            return -9 if self.killed else 0

        def kill(self):
            super().kill()
            release.set()

    pip = Quiet([])
    job = discovery.PackageInstall(popen=pip).start()
    assert finished(job)["ok"] is False and pip.killed
    assert "pip is still running" in caplog.text and "took longer than" in job["errors"][0]


def test_the_name_in_use_is_the_one_announced(config):
    class Renaming(FakeZeroconf):
        class Zeroconf(FakeZeroconf.Zeroconf):
            def register_service(self, info, allow_name_change=False):
                info.name = "Houston map-2._metarmap2._tcp.local."  # another map had the name

    d = make(config, module=Renaming)
    assert d.name() == "Houston map"  # not announced yet: as set
    d.port = 80
    d.restart()
    assert d.name() == "Houston map-2" and d.state()["name"] == "Houston map-2"


def test_refresh_announces_again_only_when_something_changed(config):
    addresses = ["10.0.0.2"]
    d = discovery.Discovery(config, load=lambda: FakeZeroconf, address=lambda: addresses[0])
    starts = []
    d.start = lambda port=None: starts.append(1)
    d.refresh()  # no port yet: the web server hasn't started
    d.port = 80
    d.refresh()  # not announcing
    assert len(starts) == 1
    d.restart()
    d.refresh()
    assert len(starts) == 1  # all is well
    addresses[0] = "10.0.0.9"  # a new lease
    d.refresh()
    assert len(starts) == 2
    config.data.web_server.announce = False
    d.refresh()
    assert len(starts) == 2


def test_refresh_waits_for_the_network(config):
    def no_network():
        raise OSError("Network is unreachable")

    d = discovery.Discovery(config, load=lambda: FakeZeroconf, address=no_network)
    d.port = 80
    d.start = lambda port=None: pytest.fail("announced without a network")
    d.refresh()


@pytest.mark.parametrize("name", ["N12.Houston", "é" * 40, "bell\x07"])
def test_names_that_would_not_announce_are_refused(name):
    with pytest.raises(ValueError):
        Settings().set("web_server.name", name)
