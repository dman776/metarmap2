"""
What every page needs besides the map's parts, and rendering a template.
"""
import os
import socket
from dataclasses import dataclass
from typing import List, Optional

import bottle

from metarmap import __version__

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@dataclass
class Site:
    ip: str  # shown in the header and /api/status
    sectionals: List[dict]  # static/sectionals.json
    releases: Optional[object] = None  # metarmap.releases.ReleaseCheck: the header's "Update available"


def my_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 1))  # connect() for UDP doesn't send packets
    return s.getsockname()[0]


def assets_version():
    """
    The ?v= on the pages' script and style links: the version plus when a static file last changed. Browsers keep
    a cached app.js for a while, and the version alone stays the same between releases (an update on the latest
    channel, or a change on the map itself), so the pages would run new templates with old scripts.
    """
    try:
        changed = max(entry.stat().st_mtime_ns for entry in os.scandir(STATIC_DIR) if entry.is_file())
    except (OSError, ValueError):
        return __version__
    return f"{__version__}.{changed // 1_000_000_000:x}"


def render(site, name, **data):
    """Renders templates/<name> with `data`, plus the version, IP and update state the header and footer show."""
    release = site.releases.state() if site.releases is not None else None
    return bottle.template(name, template_lookup=[TEMPLATE_DIR], version=__version__, myIP=site.ip, release=release,
                           assets=assets_version(), **data)
