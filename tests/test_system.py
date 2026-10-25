"""Tests for metarmap.system: the Pi's login password and Wi-Fi network, with stand-ins for the Pi's commands."""
import os
import subprocess

import pytest

from metarmap import system

OLD_CONF = """ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

network={
\tssid="HomeNet"
\tpsk=abc123
}
"""


class Run:
    """A fake subprocess.run: records each command and its stdin; `fail` names commands that fail."""

    def __init__(self, fail=(), outputs=None):
        self.calls = []
        self.fail = fail
        self.outputs = outputs or {}

    def __call__(self, command, input=None, **kwargs):
        self.calls.append((command, input))
        failed = command[0] in self.fail or " ".join(command[:3]) in self.fail
        out = next((text for prefix, text in self.outputs.items() if " ".join(command).startswith(prefix)), "")
        return subprocess.CompletedProcess(command, 1 if failed else 0, out, "simulated failure" if failed else "")

    def commands(self):
        return [" ".join(c) for c, _ in self.calls]


@pytest.fixture
def tools(monkeypatch):
    """Pretend the Pi's tools are installed."""
    monkeypatch.setattr(system.shutil, "which", lambda name: f"/usr/bin/{name}")


# ---- checks -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("password", ["", "two\nlines", "tab\there"])
def test_bad_passwords(password):
    with pytest.raises(ValueError):
        system.check_password(password)


def test_good_password():
    system.check_password("correct horse: battery staple!")  # spaces and colons are fine


@pytest.mark.parametrize("ssid, password", [("", "longenough"), ("x" * 33, "longenough"), ('say "hi"', "longenough"),
                                            ("Home", "short"), ("Home", "x" * 64), ("Home\n", "longenough")])
def test_bad_wifi(ssid, password):
    with pytest.raises(ValueError):
        system.check_wifi(ssid, password)


def test_good_wifi():
    system.check_wifi("Coffee Shop", "")  # open network
    system.check_wifi("Home-5G", "12345678")


def test_login_user_is_the_folder_owner(tmp_path):
    import pwd
    assert system.login_user(tmp_path) == pwd.getpwuid(os.getuid()).pw_name


# ---- the login password -----------------------------------------------------------------------------------------

def test_password_goes_to_chpasswd_on_stdin(tools):
    run = Run()
    assert system.set_login_password("n3w pass", user="pi", run=run, root=True, pi=True) == "changed for pi"
    assert run.calls == [(["chpasswd"], "pi:n3w pass\n")]  # never on the command line


def test_password_change_failure(tools):
    with pytest.raises(system.ChangeFailed):
        system.set_login_password("n3w pass", user="pi", run=Run(fail=["chpasswd"]), root=True, pi=True)


def test_password_skipped_without_root(tools):
    run = Run()
    assert system.set_login_password("n3w pass", user="pi", run=run, root=False, pi=True).startswith("skipped")
    assert run.calls == []


def test_password_only_changes_on_a_raspberry_pi(tools):
    """Another Linux machine, a Mac or Windows: never, even as root."""
    run = Run()
    assert system.set_login_password("n3w pass", user="pi", run=run, root=True, pi=False) == \
        "skipped (not a Raspberry Pi)"
    assert run.calls == []


@pytest.mark.parametrize("model, pi", [(b"Raspberry Pi 4 Model B Rev 1.4\x00", True),
                                       (b"Raspberry Pi Zero W Rev 1.1\x00", True),
                                       (b"Pine64 RockPro64\x00", False), (None, False)])
def test_is_raspberry_pi(tmp_path, model, pi):
    model_file = tmp_path / "model"
    if model is not None:
        model_file.write_bytes(model)
    assert system.is_raspberry_pi(model_file) is pi


# ---- Wi-Fi: NetworkManager (Bookworm) ---------------------------------------------------------------------------

def test_networkmanager_adds_a_preferred_connection(tools):
    run = Run()
    assert system.set_wifi("Cabin", "pinecones", run=run, root=True, backend="networkmanager") == "switching to Cabin"
    commands = run.commands()
    assert commands[0] == "nmcli connection delete metarmap-Cabin"  # one from an earlier change
    assert commands[1].startswith("nmcli connection add type wifi con-name metarmap-Cabin ifname wlan0 ssid Cabin")
    assert "connection.autoconnect-priority 10" in commands[1]
    assert "wifi-sec.key-mgmt wpa-psk wifi-sec.psk pinecones" in commands[1]
    assert commands[2] == "nmcli connection up metarmap-Cabin"
    assert not any("delete" in c and "Cabin" not in c for c in commands)  # the current network is kept


def test_networkmanager_open_network(tools):
    run = Run()
    system.set_wifi("Library", "", run=run, root=True, backend="networkmanager")
    assert "wifi-sec" not in run.commands()[1]


def test_networkmanager_add_failure(tools):
    with pytest.raises(system.ChangeFailed):
        system.set_wifi("Cabin", "pinecones", run=Run(fail=["nmcli connection add"]), root=True,
                        backend="networkmanager")


# ---- Wi-Fi: wpa_supplicant (Bullseye) ---------------------------------------------------------------------------

PASSPHRASE = 'network={\n\tssid="Cabin"\n\t#psk="pinecones"\n\tpsk=0f1e2d3c\n}\n'


def test_wpa_supplicant_adds_a_preferred_network(tools, tmp_path):
    conf = tmp_path / "wpa_supplicant.conf"
    conf.write_text(OLD_CONF)
    run = Run(outputs={"wpa_passphrase": PASSPHRASE})
    system.set_wifi("Cabin", "pinecones", run=run, root=True, backend="wpa_supplicant", wpa_conf=conf)

    text = conf.read_text()
    assert text.startswith(OLD_CONF.rstrip("\n"))  # the current network stays as a fallback
    assert 'ssid="Cabin"' in text and "psk=0f1e2d3c" in text and "\tpriority=10\n}" in text
    assert "pinecones" not in text  # only the hashed key is stored
    assert run.calls[0] == (["wpa_passphrase", "Cabin"], "pinecones\n")  # the password on stdin
    assert run.commands()[-1] == "wpa_cli -i wlan0 reconfigure"


def test_wpa_supplicant_replaces_an_earlier_change(tools, tmp_path):
    conf = tmp_path / "wpa_supplicant.conf"
    conf.write_text(OLD_CONF)
    for _ in range(2):
        system.set_wifi("Cabin", "pinecones", run=Run(outputs={"wpa_passphrase": PASSPHRASE}), root=True,
                        backend="wpa_supplicant", wpa_conf=conf)
    assert conf.read_text().count('ssid="Cabin"') == 1
    assert conf.read_text().count('ssid="HomeNet"') == 1


def test_wpa_supplicant_open_network(tools, tmp_path):
    conf = tmp_path / "wpa_supplicant.conf"
    conf.write_text(OLD_CONF)
    system.set_wifi("Library", "", run=Run(), root=True, backend="wpa_supplicant", wpa_conf=conf)
    assert 'network={\n\tssid="Library"\n\tkey_mgmt=NONE\n\tpriority=10\n}' in conf.read_text()


def test_wpa_supplicant_failure(tools, tmp_path):
    conf = tmp_path / "wpa_supplicant.conf"
    conf.write_text(OLD_CONF)
    with pytest.raises(system.ChangeFailed):
        system.set_wifi("Cabin", "pinecones", run=Run(fail=["wpa_cli"], outputs={"wpa_passphrase": PASSPHRASE}),
                        root=True, backend="wpa_supplicant", wpa_conf=conf)


def test_wifi_skipped_without_root():
    assert system.set_wifi("Cabin", "pinecones", run=Run(), root=False).startswith("skipped")


# ---- which network ----------------------------------------------------------------------------------------------

def test_backend(tools):
    assert system.wifi_backend(Run(outputs={"nmcli -t -f RUNNING general": "running\n"})) == "networkmanager"
    assert system.wifi_backend(Run(outputs={"nmcli -t -f RUNNING general": "stopped\n"})) == "wpa_supplicant"


def test_current_wifi(tools):
    assert system.current_wifi(Run(outputs={"iwgetid -r": "HomeNet\n"})) == "HomeNet"
    nmcli = Run(fail=["iwgetid"], outputs={"nmcli -t -f ACTIVE,SSID": "no:Other\nyes:Home\\:Net\n"})
    assert system.current_wifi(nmcli) == "Home:Net"


def test_remove_network():
    assert 'ssid="HomeNet"' not in system.remove_network(OLD_CONF, "HomeNet")
    assert system.remove_network(OLD_CONF, "Other") == OLD_CONF
