#!/usr/bin/env bash
#
# Installs the METAR map on a Raspberry Pi or Linux host. Run it from the cloned repo, as your normal user or root:
#
#     git clone https://github.com/dman776/metarmap2
#     cd metarmap2
#     ./install.sh
#
# It installs the system packages, turns on I2C for the OLED screen, puts the folder on the newest release, creates a
# Python environment (.venv) with the map's packages, asks for the web UI login and your city, and installs and starts
# the metarmap service. Running it again is safe: it updates what's there and keeps your settings.
#
# The map installed is the newest release (a tag such as v2.9.2), not the newest commit, which may be unfinished. A
# folder that's already on a release, has changes to the code, or has update.channel set to "latest" is left as it is.
#
#     ./install.sh --latest      keep the newest commit instead of switching to a release (for testing)
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO/.venv"
PYTHON="$VENV/bin/python"
# these can be changed for testing the script off a Pi
SERVICE_DIR="${METARMAP_SERVICE_DIR:-/etc/systemd/system}"
OLD_SERVICE="${METARMAP_OLD_SERVICE:-/lib/systemd/system/metarmap.service}"  # where the README used to install it
MODEL_FILE="${METARMAP_MODEL_FILE:-/proc/device-tree/model}"
SERVICE="$SERVICE_DIR/metarmap.service"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
fail() { printf '\n\033[31mError: %s\033[0m\n' "$*" >&2; exit 1; }

interactive() { [ -t 0 ] || [ "${METARMAP_INTERACTIVE:-}" = 1 ]; }

LATEST=false
for arg in "$@"; do
    case "$arg" in
        --latest) LATEST=true ;;
        -h|--help) sed -n '3,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) fail "unknown option: $arg (see ./install.sh --help)" ;;
    esac
done

# ask "question" default -> the answer, or the default if left empty
ask() {
    local answer
    read -r -p "    $1 [$2]: " answer || true
    printf '%s' "${answer:-$2}"
}

# reads or changes one setting in config.json with the map's own settings code
setting() {
    (cd "$REPO" && "$PYTHON" - "$@" <<'EOF'
import contextlib
import io
import sys
from metarmap.config import Config
from metarmap.settings import Settings

key = sys.argv[1]
if len(sys.argv) > 2:
    # through Config, which first moves an older map's airports.json into config.json
    with contextlib.redirect_stdout(io.StringIO()):
        Config("config.json").edit(key, sys.argv[2])
else:
    value = Settings.load("config.json")
    for part in key.split("."):
        value = getattr(value, part)
    print(value)
EOF
    )
}

# puts the folder on the newest release and prints what it did; exits 10 if the code changed, 1 if it couldn't
newest_release() {
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO/src" python3 - "$REPO" <<'EOF'
import sys
from metarmap.lib import utils

ok, message, changed = utils.install_newest_release(sys.argv[1])
print(message)
sys.exit((10 if changed else 0) if ok else 1)
EOF
}

known_city() {
    "$PYTHON" -c 'import sys, astral.geocoder as g; g.lookup(sys.argv[1], g.database())' "$1" 2>/dev/null
}

# ---- checks ---------------------------------------------------------------------------------------------------

SUDO=()
if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null || fail "sudo wasn't found; run as root or install sudo"
    SUDO=(sudo)
fi
command -v apt-get >/dev/null || fail "this script is for Raspberry Pi OS; apt-get wasn't found"
[ -f "$REPO/config.json" ] && [ -f "$REPO/pyproject.toml" ] || fail "run this from the metarmap2 folder you cloned"

on_pi=false
if [ -r "$MODEL_FILE" ] && grep -qa "Raspberry Pi" "$MODEL_FILE"; then
    on_pi=true
    say "Installing the METAR map on a $(tr -d '\0' < "$MODEL_FILE")"
else
    say "Installing the METAR map (this isn't a Raspberry Pi: no LED or OLED drivers)"
fi
note "Folder: $REPO"

# ---- system packages ------------------------------------------------------------------------------------------

say "Installing system packages"
# python3-pil: Pillow for the OLED screen, ready-built for the Pi; build-essential: for LED drivers that have no
# ready-built package on some Pi OS versions
"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get install -y git python3-venv python3-dev python3-pil build-essential i2c-tools

if $on_pi && command -v raspi-config >/dev/null; then
    say "Turning on I2C (for the OLED screen)"
    "${SUDO[@]}" raspi-config nonint do_i2c 0
fi

# ---- release --------------------------------------------------------------------------------------------------

if [ "$LATEST" = true ]; then
    say "Keeping the newest commit (--latest)"
elif [ -z "${METARMAP_INSTALL_AGAIN:-}" ]; then
    say "Checking for the newest release"
    status=0
    output="$(newest_release 2>&1)" || status=$?
    note "$(printf '%s\n' "$output" | tail -n 1)"
    if [ "$status" -eq 10 ]; then
        # the release has its own installer, matching its code: carry on with that one
        note "Carrying on with that release's installer"
        METARMAP_INSTALL_AGAIN=1 exec "$REPO/install.sh" "$@"
    elif [ "$status" -ne 0 ]; then
        note "Couldn't switch to a release, so this installs what's here. The web UI's Update can switch it later."
    fi
fi

# ---- Python environment ---------------------------------------------------------------------------------------

say "Setting up the Python environment in .venv"
# --system-site-packages: use Pi OS's own Pillow and GPIO packages instead of building them
if [ ! -x "$PYTHON" ]; then
    python3 -m venv --system-site-packages "$VENV"
fi
"$PYTHON" -m pip install --upgrade pip
if $on_pi; then
    "$PYTHON" -m pip install -e "${REPO}[pi]"
else
    "$PYTHON" -m pip install -e "$REPO"
fi

# ---- settings -------------------------------------------------------------------------------------------------

if interactive; then
    say "Settings (press Enter to keep the value in brackets)"
    user="$(ask "Web UI user name" "$(setting web_server.user)")"
    setting web_server.user "$user"

    read -r -s -p "    Web UI password [leave empty to keep the current one]: " password || true
    echo
    if [ -n "${password:-}" ]; then
        setting web_server.password "$password"
    elif [ "$(setting web_server.password)" = "map" ]; then
        note "The password is still the default (map); change it on the web UI's Config > Access."
    fi

    while true; do
        city="$(ask "City, for dimming the LEDs at night" "$(setting geo.city)")"
        if known_city "$city"; then
            setting geo.city "$city"
            break
        fi
        note "\"$city\" isn't in the list of cities the map knows; try a nearby larger city (e.g. Dallas, Chicago)."
    done
else
    note "Not asking for settings (no terminal); edit them on the web UI's Config page."
fi

# ---- service --------------------------------------------------------------------------------------------------

say "Installing the metarmap service"
if [ -f "$OLD_SERVICE" ] && [ "$OLD_SERVICE" != "$SERVICE" ]; then
    # one service file only: the one this script writes
    "${SUDO[@]}" mv "$OLD_SERVICE" "$OLD_SERVICE.old"
    note "Moved the older $OLD_SERVICE to $OLD_SERVICE.old"
fi
sed -e "s#/home/pi/metarmap2#$REPO#g" -e "s#^ExecStart=/usr/bin/python3 #ExecStart=$PYTHON #" \
    "$REPO/metarmap.service" | "${SUDO[@]}" tee "$SERVICE" >/dev/null
"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable metarmap.service
"${SUDO[@]}" systemctl restart metarmap.service

# ---- done -----------------------------------------------------------------------------------------------------

port="$(setting web_server.port)"
[ "$port" = 80 ] && suffix="" || suffix=":$port"
host="$(hostname)"
ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
say "Done. The map is starting."
note "Web UI:  http://${host%.local}.local$suffix/${ip:+   (or http://$ip$suffix/)}"
note "Next:    set up your airports on Config > Airports, one per LED, in the order they're wired."
note "Status:  systemctl status metarmap      Log: $REPO/metarmap.log"
$on_pi && note "LED test: choose the Chase visualizer on the Home page; it lights each LED in turn."
exit 0
