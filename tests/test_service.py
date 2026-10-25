"""Tests for switching an installed metarmap.service from controller.py to `python3 -m metarmap`."""
import subprocess
from pathlib import Path

import pytest

from metarmap import service

REPO = Path(__file__).parent.parent

# every metarmap.service this project shipped before it ran `python3 -m metarmap` (from git history)
OLD = {
    "root": "[Unit]\nDescription=MetarMap\nAfter={after}\n\n[Service]\nWorkingDirectory={repo}\n"
            "ExecStart={repo}/controller.py\nRestart=always\nUser=root\n\n[Install]\nWantedBy=multi-user.target\n",
    "sleep": "[Unit]\nDescription=MetarMap\nAfter=network-online.target\n\n[Service]\nWorkingDirectory={repo}\n"
             "ExecStartPre=/bin/sleep 10\nExecStart=sudo {repo}/controller.py\nRestart=always\nUser=pi\n\n"
             "[Install]\nWantedBy=multi-user.target\n",
    "ping": "[Unit]\nDescription=MetarMap\nAfter=network-online.target\n\n[Service]\nWorkingDirectory={repo}\n"
            "ExecStartPre=/bin/sh -c 'until ping -c1 www.aviationweather.gov; do sleep 1; done;'\n"
            "ExecStart=sudo {repo}/controller.py\nRestart=always\nUser=pi\n\n[Install]\nWantedBy=multi-user.target\n",
    "sudo": "[Unit]\nDescription=MetarMap\nAfter=network-online.target\n\n[Service]\nWorkingDirectory={repo}\n"
            "ExecStart=sudo {repo}/controller.py\nRestart=always\nUser=pi\n\n[Install]\nWantedBy=multi-user.target\n",
}


class Run:
    """A fake subprocess.run that records commands; `fail` names the commands that fail."""

    def __init__(self, fail=()):
        self.commands = []
        self.fail = fail

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        failed = any(word in command for word in self.fail)
        return subprocess.CompletedProcess(command, 1 if failed else 0, "", "simulated failure" if failed else "")


@pytest.fixture
def repo(tmp_path):
    checkout = tmp_path / "metarmap2"
    checkout.mkdir()
    (checkout / "metarmap.service").write_text((REPO / "metarmap.service").read_text())
    return checkout


@pytest.fixture
def installed(tmp_path):
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    return systemd / "metarmap.service"


def old(name, repo, after="network-online.target"):
    return OLD[name].format(repo=repo, after=after)


def migrate(installed, repo, run, root=True):
    return service.migrate(paths=[installed], repo=repo, run=run, root=root)


@pytest.mark.parametrize("name", OLD)
def test_switches_every_shipped_service_file(installed, repo, name):
    installed.write_text(old(name, repo))
    installed.chmod(0o644)
    run = Run()
    assert migrate(installed, repo, run) == [installed]

    new = installed.read_text()
    assert f"WorkingDirectory={repo}\n" in new
    assert f"Environment=PYTHONPATH={repo}/src\n" in new
    assert "ExecStart=/usr/bin/python3 -m metarmap\n" in new
    assert "controller.py" not in new and "/home/pi" not in new
    assert installed.stat().st_mode & 0o777 == 0o644
    assert (installed.parent / ("metarmap.service" + service.BACKUP_SUFFIX)).read_text() == old(name, repo)
    assert not (installed.parent / "metarmap.service.new").exists()

    (check, check_kwargs), (reload, _) = run.commands
    assert check == ["/usr/bin/python3", "-c", "import metarmap.app"]
    assert check_kwargs["env"]["PYTHONPATH"] == f"{repo}/src"
    assert reload == ["systemctl", "daemon-reload"]


def test_the_first_service_file(installed, repo):
    installed.write_text(old("root", repo, after="network.target"))
    assert migrate(installed, repo, Run()) == [installed]


def test_a_switched_file_is_left_alone(installed, repo):
    installed.write_text(service.render(repo))
    run = Run()
    assert migrate(installed, repo, run) == []
    assert run.commands == []


@pytest.mark.parametrize("text", [
    OLD["sudo"].replace("Restart=always", "Restart=always\nEnvironment=FOO=1"),  # customized
    OLD["sudo"].replace("{repo}/controller.py", "/home/someone/other/controller.py"),  # another checkout
    OLD["sudo"].replace("WorkingDirectory={repo}", "WorkingDirectory=/tmp"),
    OLD["sudo"].replace("controller.py", "controller.py --debug"),
    OLD["sudo"] + "this is not a setting\n",
])
def test_customized_files_are_left_alone(installed, repo, text):
    installed.write_text(text.format(repo=repo, after=""))
    run = Run()
    assert migrate(installed, repo, run) == []
    assert installed.read_text() == text.format(repo=repo, after="")
    assert run.commands == []


def test_nothing_without_root(installed, repo):
    installed.write_text(old("sudo", repo))
    assert migrate(installed, repo, Run(), root=False) == []
    assert installed.read_text() == old("sudo", repo)


def test_nothing_when_not_installed(installed, repo):
    assert migrate(installed, repo, Run()) == []


def test_symlinks_are_left_alone(installed, repo, tmp_path):
    target = tmp_path / "linked.service"
    target.write_text(old("sudo", repo))
    installed.symlink_to(target)
    assert migrate(installed, repo, Run()) == []
    assert target.read_text() == old("sudo", repo)


def test_left_alone_if_the_new_command_cannot_import_the_map(installed, repo):
    installed.write_text(old("sudo", repo))
    run = Run(fail=["-c"])
    assert migrate(installed, repo, run) == []
    assert installed.read_text() == old("sudo", repo)
    assert len(run.commands) == 1  # no daemon-reload


def test_put_back_if_daemon_reload_fails(installed, repo):
    installed.write_text(old("sudo", repo))
    assert migrate(installed, repo, Run(fail=["daemon-reload"])) == []
    assert installed.read_text() == old("sudo", repo)


def test_both_install_locations(tmp_path, repo):
    paths = []
    for folder in ("etc", "lib"):
        (tmp_path / folder).mkdir()
        paths.append(tmp_path / folder / "metarmap.service")
        paths[-1].write_text(old("sudo", repo))
    run = Run()
    assert service.migrate(paths=paths, repo=repo, run=run, root=True) == paths
    assert [c for c, _ in run.commands].count(["systemctl", "daemon-reload"]) == 1


def test_the_repo_service_file_is_a_shipped_template():
    """render() swaps TEMPLATE_REPO for the checkout's folder, so metarmap.service must use it."""
    text = (REPO / "metarmap.service").read_text()
    assert f"WorkingDirectory={service.TEMPLATE_REPO}\n" in text
    assert f"Environment=PYTHONPATH={service.TEMPLATE_REPO}/src\n" in text
    assert service.why_not(old("sudo", service.TEMPLATE_REPO), service.TEMPLATE_REPO) is None
