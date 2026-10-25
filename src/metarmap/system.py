"""
Changing the Pi itself from the web UI: the login user's password and the Wi-Fi network.

Every command goes through `run` (subprocess.run by default), so tests can stand in for the Pi. The map runs as
root, which these need; off a Pi (or not as root) they report that they were skipped.
"""
import os
import pwd
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WPA_CONF = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
MODEL_FILE = Path("/proc/device-tree/model")  # names the board on a Raspberry Pi
WIFI_PRIORITY = 10  # above Pi OS's default 0, so the new network is tried first; the old one stays as a fallback


class ChangeFailed(Exception):
    """A change to the Pi that didn't work; the message says why, for the web UI."""


def check_password(password):
    """Raises ValueError for a password the web UI or Linux can't take."""
    if not password:
        raise ValueError("the password can't be empty")
    if any(ord(ch) < 32 for ch in password):
        raise ValueError("the password can't contain line breaks or other control characters")


def login_user(repo=REPO):
    """The Pi's login user: whoever owns the map's folder (e.g. pi). None if that's root or unknown."""
    try:
        uid = os.stat(repo).st_uid
        return None if uid == 0 else pwd.getpwuid(uid).pw_name
    except (OSError, KeyError):
        return None


def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def is_raspberry_pi(model_file=MODEL_FILE):
    """Whether this is a Raspberry Pi (not another Linux machine, a Mac or Windows)."""
    try:
        return "Raspberry Pi" in Path(model_file).read_bytes().decode(errors="ignore")
    except OSError:
        return False


def can_set_login_password():
    """Whether set_login_password() will change anything: only on a Raspberry Pi, with the map running as root."""
    return is_raspberry_pi() and is_root() and login_user() is not None


def set_login_password(password, user=None, run=subprocess.run, root=None, pi=None):
    """
    Sets the Linux password of the Pi's login user with chpasswd (given on stdin, so it isn't on a command line).
    Only on a Raspberry Pi: on any other machine the map never changes a password.
    Returns what happened, for the web UI; raises ChangeFailed if chpasswd failed.
    """
    check_password(password)
    if not (is_raspberry_pi() if pi is None else pi):
        return "skipped (not a Raspberry Pi)"
    user = user or login_user()
    if not (is_root() if root is None else root) or not user or not shutil.which("chpasswd"):
        return "skipped (not running as root)"
    done = run(["chpasswd"], input=f"{user}:{password}\n", capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise ChangeFailed(f"chpasswd failed: {done.stderr.strip() or done.returncode}")
    return f"changed for {user}"


# ---- Wi-Fi ----------------------------------------------------------------------------------------------------

def check_wifi(ssid, password):
    """Raises ValueError for a network name or password Wi-Fi can't use."""
    if not 1 <= len(ssid.encode()) <= 32:
        raise ValueError("the network name must be 1 to 32 characters")
    if '"' in ssid or any(ord(ch) < 32 for ch in ssid):
        raise ValueError("the network name can't contain quotes or control characters")
    if password and not 8 <= len(password) <= 63:
        raise ValueError("a Wi-Fi password must be 8 to 63 characters (or empty for an open network)")
    if any(ord(ch) < 32 for ch in password):
        raise ValueError("the Wi-Fi password can't contain control characters")


def wifi_backend(run=subprocess.run):
    """How this Pi manages Wi-Fi: "networkmanager" (Bookworm), "wpa_supplicant" (Bullseye), or None."""
    if shutil.which("nmcli"):
        done = run(["nmcli", "-t", "-f", "RUNNING", "general"], capture_output=True, text=True, timeout=15)
        if done.returncode == 0 and done.stdout.strip() == "running":
            return "networkmanager"
    if shutil.which("wpa_cli"):
        return "wpa_supplicant"
    return None


def current_wifi(run=subprocess.run):
    """The Wi-Fi network the Pi is on now, or None."""
    try:
        if shutil.which("iwgetid"):
            done = run(["iwgetid", "-r"], capture_output=True, text=True, timeout=15)
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout.strip()
        if shutil.which("nmcli"):
            done = run(["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"], capture_output=True, text=True,
                       timeout=15)
            for line in done.stdout.splitlines():
                if line.startswith("yes:"):
                    return line[4:].replace("\\:", ":")
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def set_wifi(ssid, password, run=subprocess.run, root=None, backend=None, wpa_conf=WPA_CONF):
    """
    Switches the Pi to another Wi-Fi network, keeping the current one as a fallback. Returns what happened;
    raises ChangeFailed if it couldn't. The switch drops the network the request came in on, so call it after
    answering the request.
    """
    check_wifi(ssid, password)
    if not (is_root() if root is None else root):
        return "skipped (not running as root on a Pi)"
    backend = backend or wifi_backend(run)
    if backend == "networkmanager":
        return _set_wifi_networkmanager(ssid, password, run)
    if backend == "wpa_supplicant":
        return _set_wifi_wpa_supplicant(ssid, password, run, Path(wpa_conf))
    return "skipped (no NetworkManager or wpa_supplicant)"


def _set_wifi_networkmanager(ssid, password, run):
    name = f"metarmap-{ssid}"
    run(["nmcli", "connection", "delete", name], capture_output=True, text=True, timeout=30)  # from an earlier change
    add = ["nmcli", "connection", "add", "type", "wifi", "con-name", name, "ifname", "wlan0", "ssid", ssid,
           "connection.autoconnect", "yes", "connection.autoconnect-priority", str(WIFI_PRIORITY)]
    if password:
        add += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
    done = run(add, capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise ChangeFailed(f"nmcli couldn't add the network: {done.stderr.strip() or done.returncode}")
    # if this fails, NetworkManager goes back to the network it was on
    run(["nmcli", "connection", "up", name], capture_output=True, text=True, timeout=60)
    return f"switching to {ssid}"


def _set_wifi_wpa_supplicant(ssid, password, run, wpa_conf):
    if password:
        done = run(["wpa_passphrase", ssid], input=password + "\n", capture_output=True, text=True, timeout=15)
        if done.returncode != 0:
            raise ChangeFailed(f"wpa_passphrase failed: {done.stderr.strip() or done.returncode}")
        # drop the commented-out plain-text password wpa_passphrase adds
        block = "\n".join(line for line in done.stdout.splitlines() if not line.strip().startswith("#psk="))
    else:
        block = f'network={{\n\tssid="{ssid}"\n\tkey_mgmt=NONE\n}}'
    block = block.rstrip().rstrip("}").rstrip() + f"\n\tpriority={WIFI_PRIORITY}\n}}"
    text = wpa_conf.read_text() if wpa_conf.exists() else "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n"
    text = remove_network(text, ssid)  # an earlier block for the same network
    wpa_conf.write_text(text.rstrip("\n") + "\n\n" + block.strip() + "\n")
    done = run(["wpa_cli", "-i", "wlan0", "reconfigure"], capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise ChangeFailed(f"wpa_cli couldn't apply it: {done.stderr.strip() or done.returncode}")
    return f"switching to {ssid}"


def remove_network(conf, ssid):
    """wpa_supplicant.conf without the network={...} blocks for `ssid`."""
    pattern = re.compile(r"\n*network=\{[^}]*?\bssid=\"" + re.escape(ssid) + r"\"[^}]*\}\n?", re.S)
    return pattern.sub("\n", conf)
