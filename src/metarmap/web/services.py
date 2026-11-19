"""
What the web layer uses of the map: a typing.Protocol, so web/ never imports metarmap.app (which imports the web).

metarmap.app.App satisfies it as it is; a test can pass a small fake that has just the members a route reads.
"""

from typing import Optional, Protocol

from metarmap.advisories import Advisories
from metarmap.atis import Atis
from metarmap.config import Config
from metarmap.discovery import Discovery
from metarmap.display import Display
from metarmap.metar import Reports
from metarmap.releases import ReleaseCheck
from metarmap.renderer import Renderer
from metarmap.speech import Speech
from metarmap.sun import SunTimes
from metarmap.tfr import Tfrs
from metarmap.traffic import Traffic


class Services(Protocol):
    config: Config
    sun: SunTimes
    metars: Reports
    renderer: Renderer
    display: Display
    releases: Optional[ReleaseCheck]
    traffic: Optional[Traffic]
    advisories: Optional[Advisories]
    tfrs: Optional[Tfrs]
    speech: Optional[Speech]
    atis: Optional[Atis]
    discovery: Optional[Discovery]

    def refetch_metars(self) -> bool:
        """GET /fetch: the METARs now. False if a fetch under way didn't end in time (nothing fetched)."""

    def schedule_fetch(self) -> None:
        """The regular fetch's wait starting now (after a fetch by hand)."""

    def next_fetch(self) -> dict:
        """When METARs are next fetched, that wait's length, and when they were last fetched (Unix times)."""

    def next_rotation(self) -> Optional[float]:
        """When auto-rotate next changes the visualizer (Unix time), or None when it's off."""
