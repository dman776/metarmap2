"""
The startup sequences that fade the map in (led.init_sequence), as plain math: when each LED starts to fade in,
from where its airport is, and its color at each moment. The renderer plays them; Comet is the LED library's own.

Each LED fades from dark to its visualizer color over FADE_SECONDS; the starts are spread over the rest of
SECONDS, so the last LED is lit when the sequence ends. A start is a fraction: 0 at once, 1 last.
"""

import math
import random
from typing import List, Optional, Sequence, Tuple

import metarmap.lib.colors as colors_lib
from metarmap.models import Look

SECONDS = 3.0  # the whole sequence
FADE_SECONDS = 0.5  # each LED's fade from dark to its color

OFF = colors_lib.color(colors_lib.OFF)
WHITE = colors_lib.color(colors_lib.WHITE)

# led.init_sequence's choices, with their names on the Config page
NAMES = {  # in settings.INIT_SEQUENCES' order
    "comet": "Comet",
    "center_out": "Center out",
    "edges_in": "Edges in",
    "sweep": "Sweep",
    "radar": "Radar sweep",
    "sparkle": "Sparkle in",
}

# led.init_sweep_from's choices: the side of the map Sweep starts from, and the way it travels (east, north)
SWEEP_FROM = {  # in settings.SWEEP_SIDES' order
    "W": ("West to east", (1, 0)),
    "NW": ("Northwest to southeast", (1, -1)),
    "N": ("North to south", (0, -1)),
    "NE": ("Northeast to southwest", (-1, -1)),
    "E": ("East to west", (-1, 0)),
    "SE": ("Southeast to northwest", (-1, 1)),
    "S": ("South to north", (0, 1)),
    "SW": ("Southwest to northeast", (1, 1)),
}

Position = Optional[Tuple[float, float]]  # (lat, lon), or None for an LED with no airport or an unknown one


def project(positions: Sequence[Position]) -> List[Optional[Tuple[float, float]]]:
    """
    (x, y) on a flat map, in degrees of latitude: east and north. A degree of longitude is shorter away from the
    equator, so it's scaled by the cosine of the airports' middle latitude, as a sectional is drawn.
    """
    known = [p for p in positions if p is not None]
    if not known:
        return [None] * len(positions)
    lats = [lat for lat, _ in known]
    scale = math.cos(math.radians((min(lats) + max(lats)) / 2))
    return [None if p is None else (p[1] * scale, p[0]) for p in positions]


def _spread(values):
    """Values from 0 to 1: the smallest 0, the largest 1 (all 0 when they're the same)."""
    low, high = min(values), max(values)
    return [0.0 if high == low else (v - low) / (high - low) for v in values]


def start_times(sequence: str, positions: Sequence[Position], sweep_from="W", rng=random) -> List[float]:
    """
    When each LED starts to fade in, as a fraction of the sequence (0 first, 1 last). The center is the middle of
    the box around the airports. An LED with no position comes last.
    """
    n = len(positions)
    if sequence == "sparkle":
        order = list(range(n))
        rng.shuffle(order)
        starts = [0.0] * n
        for rank, led in enumerate(order):
            starts[led] = rank / (n - 1) if n > 1 else 0.0
        return starts

    points = project(positions)
    known = [(i, p) for i, p in enumerate(points) if p is not None]
    starts = [1.0] * n
    if not known:
        return starts
    xs, ys = [p[0] for _, p in known], [p[1] for _, p in known]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    if sequence in ("center_out", "edges_in"):
        distance = _spread([0.0] + [math.hypot(x - cx, y - cy) for _, (x, y) in known])[1:]  # from the center
        values = distance if sequence == "center_out" else [1 - d for d in distance]
    elif sequence == "sweep":
        vx, vy = SWEEP_FROM.get(sweep_from, SWEEP_FROM["W"])[1]
        values = _spread([x * vx + y * vy for _, (x, y) in known])
    elif sequence == "radar":
        # the beam starts pointing north and turns clockwise, once
        values = [(math.atan2(x - cx, y - cy) % (2 * math.pi)) / (2 * math.pi) for _, (x, y) in known]
    else:
        raise ValueError(f"unknown startup sequence {sequence!r}")
    for (i, _), value in zip(known, values):
        starts[i] = value
    return starts


def target(look: Look):
    """The color an LED fades in to: its look's (first) color; dark for an LED that's off."""
    return OFF if look.effect == "off" or look.color is None else look.color


def level(t: float, start: float) -> float:
    """How far an LED that starts at `start` (a fraction) is faded in at `t` seconds: 0 dark, 1 its color."""
    begin = start * (SECONDS - FADE_SECONDS)
    x = min(1.0, max(0.0, (t - begin) / FADE_SECONDS))
    return x * x  # eased in: the eye sees the first steps of a fade most


def colors_at(t: float, starts: Sequence[float], targets: Sequence[Tuple[int, int, int]]):
    """Every LED's color at `t` seconds into the sequence."""
    out = []
    for start, color in zip(starts, targets):
        k = level(t, start)
        out.append(tuple(int(round(c * k)) for c in color))
    return out
