"""
A one-time switch of the installed metarmap.service from controller.py to `python3 -m metarmap`.

Maps set up before the code became a package have a copy of metarmap.service in /lib/systemd/system that runs
controller.py, and an update from the web UI doesn't touch it. At startup the map (running as root) replaces that
copy with the repo's metarmap.service, but only if:
  - it is one of the service files this project shipped (only their settings, running this repo's controller.py),
  - the new service's command can import the map, and
  - systemctl daemon-reload works afterwards; if it doesn't, the old file is put back.
The old file is kept next to it as metarmap.service.controller-py.bak. The new service is used from the next
start of the service (or reboot); the running map isn't restarted.
"""
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from metarmap.lib.safe_logging import safe_log

REPO = Path(__file__).resolve().parents[2]  # the git checkout: src/metarmap/service.py -> repo
INSTALLED = (Path("/etc/systemd/system/metarmap.service"), Path("/lib/systemd/system/metarmap.service"))
TEMPLATE_REPO = "/home/pi/metarmap2"  # the repo folder as written in metarmap.service
BACKUP_SUFFIX = ".controller-py.bak"
# every setting the shipped service files have had; a file with any other setting was customized and is left alone
SHIPPED_KEYS = {"Description", "After", "WorkingDirectory", "ExecStartPre", "ExecStart", "Restart", "User",
                "WantedBy"}


def parse(text) -> Dict[str, List[str]]:
    """The settings of a unit file, {key: [values]}. Raises ValueError for a line it doesn't understand."""
    settings: Dict[str, List[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "#;" or (line.startswith("[") and line.endswith("]")):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ValueError(f"unexpected line: {line}")
        settings.setdefault(key.strip(), []).append(value.strip())
    return settings


def why_not(text, repo) -> Optional[str]:
    """Why an installed service file shouldn't be replaced, or None if it's an old shipped one for this repo."""
    try:
        settings = parse(text)
    except ValueError as e:
        return str(e)
    extra = sorted(set(settings) - SHIPPED_KEYS)
    if extra:
        return f"it has settings the shipped file never had ({', '.join(extra)})"
    command = shlex.split(" ".join(settings.get("ExecStart", [])))
    if command[:1] == ["sudo"]:
        command = command[1:]
    if command != [f"{repo}/controller.py"]:
        return f"it doesn't run {repo}/controller.py"
    if settings.get("WorkingDirectory") != [str(repo)]:
        return f"its WorkingDirectory isn't {repo}"
    return None


def render(repo) -> str:
    """The repo's metarmap.service, for a checkout at `repo`."""
    return (Path(repo) / "metarmap.service").read_text().replace(TEMPLATE_REPO, str(repo))


def starts(text, repo, run) -> bool:
    """Whether the new service's python can import the map (with the service's PYTHONPATH)."""
    settings = parse(text)
    command = shlex.split(settings["ExecStart"][0])
    env = dict(os.environ)
    for item in settings.get("Environment", []):
        key, _, value = item.partition("=")
        env[key] = value
    try:
        done = run([command[0], "-c", "import metarmap.app"], cwd=str(repo), env=env, capture_output=True,
                   text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        safe_log(f"{command[0]} can't run: {e}")
        return False
    if done.returncode != 0:
        safe_log(f"{command[0]} can't import the map: {done.stderr.strip()}")
    return done.returncode == 0


def migrate(paths=INSTALLED, repo=REPO, run=subprocess.run, root=None) -> List[Path]:
    """
    Replaces installed service files that still run controller.py (see the module docstring).
    Returns the files replaced.
    """
    if root is None:
        root = hasattr(os, "geteuid") and os.geteuid() == 0
    if not root or not (Path(repo) / "metarmap.service").exists():
        return []
    new = render(repo)
    replaced = []
    for path in map(Path, paths):
        if path.is_symlink() or not path.is_file():
            continue
        old = path.read_text()
        if "controller.py" not in old:
            continue  # already switched
        reason = why_not(old, repo)
        if reason:
            safe_log(f"leaving {path} as it is: {reason}")
            continue
        if not replaced and not starts(new, repo, run):
            safe_log(f"leaving {path} as it is: the new service wouldn't start")
            return []
        shutil.copy2(path, path.with_name(path.name + BACKUP_SUFFIX))
        tmp = path.with_name(path.name + ".new")
        tmp.write_text(new)
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
        replaced.append(path)

    if replaced:
        done = run(["systemctl", "daemon-reload"], capture_output=True, text=True, timeout=120)
        if done.returncode != 0:
            for path in replaced:
                shutil.copy2(path.with_name(path.name + BACKUP_SUFFIX), path)
            safe_log(f"systemctl daemon-reload failed ({done.stderr.strip()}); put the old service file back")
            return []
        safe_log(f"switched {', '.join(map(str, replaced))} to `python3 -m metarmap`; "
                 f"the old file is saved as *{BACKUP_SUFFIX}")
    return replaced
