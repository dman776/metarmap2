"""
What every page needs besides the map's parts, and rendering a template.
"""
import os
import socket
from dataclasses import dataclass
from typing import List

import bottle

from metarmap import __version__

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


@dataclass
class Site:
    ip: str  # shown in the header and /api/status
    sectionals: List[dict]  # static/sectionals.json


def my_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 1))  # connect() for UDP doesn't send packets
    return s.getsockname()[0]


def render(site, name, **data):
    """Renders templates/<name> with `data`, plus the version and IP the header and footer show."""
    return bottle.template(name, template_lookup=[TEMPLATE_DIR], version=__version__, myIP=site.ip, **data)
