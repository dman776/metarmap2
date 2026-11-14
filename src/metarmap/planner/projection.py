"""
Where an airport sits on a physical board: a chart (one of the FAA sectionals or the US VFR Wall Planning Chart) and a
board width turn a latitude and longitude into millimetres from the board's top left corner.

The board is the whole printed rectangle. A chart's map fills the board less its margins (the legend borders), which
are fractions of the board, so they grow and shrink with it: Darryl's 32 x 22 inch board has 10 mm at the left and
7 mm at the bottom of a sectional, the wall chart has none.

The board's height is an input. Only the Houston sectional (Darryl's board) and the wall chart have a measured shape;
for any other sectional the height is an estimate from the chart's bounds that can be several percent off (Houston's was
23.4 in on a 32 in board, against the real 22 in), so a caller must let the user enter the real height.
"""

import json
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple

SECTIONALS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "static", "sectionals.json"
)

MM_PER_INCH = 25.4

# the margins of a sectional on Darryl's 32 x 22 inch board (10 mm at the left, 7 mm at the bottom), as board fractions
SECTIONAL_MARGIN_LEFT = 10 / (32 * MM_PER_INCH)
SECTIONAL_MARGIN_BOTTOM = 7 / (22 * MM_PER_INCH)

# the wall chart's printed size at 100% (Darryl): its ratio is exactly 59 / 36
WALL_SIZE_IN = (59.0, 36.0)

# sectionals whose whole board (the map and its margins) was measured, (width, height) in inches: Darryl's board is the
# Houston sectional at 32 x 22. Any other sectional's board shape is only an estimate from its bounds.
MEASURED_BOARDS_IN = {"Houston": (32.0, 22.0)}

# ASSUMPTION: the FAA does not publish the wall chart's projection where it could be found, so these are the usual
# values for the continental US (Lambert conformal conic, standard parallels 33 and 45 N, central meridian 96 W,
# origin 39 N). Only a few kilometres of the picture depend on them.
WALL_PARALLELS = (33.0, 45.0)
WALL_CENTRAL_MERIDIAN = -96.0
WALL_ORIGIN_LATITUDE = 39.0

EDGE_SAMPLES = 64  # points per edge when a wall chart has no fit points and its bounds are fitted to its rectangle
FIT_PADDING = 0.02  # the wall chart's rectangle is this much (of its size) larger than the points it is fitted around


@dataclass(frozen=True)
class Chart:
    """
    A chart's name, the lat/lon bounds of its map and the margins around it.

    kind:         "sectional" (a flat projection, scaled by the cosine of the middle latitude) or "wall" (Lambert
                  conformal conic: the continental US is too big to treat as flat)
    margin_*:     fractions of the board's width (left, right) or height (top, bottom)
    printed_in:   the printed size (width, height) in inches at 100%, if known; it sets the map's shape (the wall chart)
    board_aspect: the measured width divided by height of the whole board, margins included, if known (Houston); it
                  sets the board's shape. A chart with neither has its board shape estimated from its bounds
    """

    name: str
    west: float
    east: float
    south: float
    north: float
    kind: str = "sectional"
    margin_left: float = 0.0
    margin_bottom: float = 0.0
    margin_top: float = 0.0
    margin_right: float = 0.0
    printed_in: Optional[Tuple[float, float]] = None
    board_aspect: Optional[float] = None
    parallels: Tuple[float, ...] = ()
    central_meridian: float = 0.0
    origin_latitude: float = 0.0
    fit_points: Tuple[Tuple[float, float], ...] = ()  # wall: (lat, lon) points the printed rectangle is fitted around

    @property
    def map_aspect(self):
        """
        The map's width divided by its height. Wall: the printed ratio. Sectional: the bounds in a flat projection
        scaled by the cosine of the middle latitude, an approximation of the printed shape (the real charts are
        Lambert conformal conic, so a printed sectional differs by a percent or two).
        """
        if self.printed_in:
            return self.printed_in[0] / self.printed_in[1]
        mid = math.radians((self.south + self.north) / 2)
        return (self.east - self.west) * math.cos(mid) / (self.north - self.south)


@lru_cache(maxsize=1)
def charts():
    """Every chart in sectionals.json: the sectionals, then the US Wall Planning Chart."""
    with open(SECTIONALS_FILE) as f:
        data = json.load(f)
    found = [
        Chart(
            name=c["name"],
            west=c["west"],
            east=c["east"],
            south=c["south"],
            north=c["north"],
            margin_left=SECTIONAL_MARGIN_LEFT,
            margin_bottom=SECTIONAL_MARGIN_BOTTOM,
            board_aspect=_board_aspect(c["name"]),
        )
        for c in data["charts"]
    ]
    wall = data.get("wall_chart")
    if wall:
        found.append(
            Chart(
                name=wall["name"],
                west=wall["west"],
                east=wall["east"],
                south=wall["south"],
                north=wall["north"],
                kind="wall",
                printed_in=WALL_SIZE_IN,
                parallels=WALL_PARALLELS,
                central_meridian=WALL_CENTRAL_MERIDIAN,
                origin_latitude=WALL_ORIGIN_LATITUDE,
                fit_points=tuple((p[0], p[1]) for p in wall.get("fit_points", ())),
            )
        )
    return tuple(found)


def _board_aspect(name):
    """The measured board's width divided by height for a sectional, or None if its board was not measured."""
    measured = MEASURED_BOARDS_IN.get(name)
    return measured[0] / measured[1] if measured else None


def chart_by_name(name):
    """The chart called `name` (case doesn't matter), or None."""
    wanted = str(name).strip().lower()
    return next((c for c in charts() if c.name.lower() == wanted), None)


def unwrapped(chart, lon):
    """
    A longitude in the chart's own range. The Western Aleutian Islands chart crosses the antimeridian (its east is
    above 180), so a longitude west of it, such as Adak's -176.65, is that chart's 183.35.
    """
    return lon + 360 if chart.east > 180 and lon < 0 else lon


def contains(chart, lat, lon):
    """Whether a point is inside the chart's bounds."""
    return chart.south <= lat <= chart.north and chart.west <= unwrapped(chart, lon) <= chart.east


def board_size(chart, width_mm, height_mm=None):
    """
    (width, height) in mm of a board `width_mm` wide. An explicit `height_mm` wins; else the chart's measured board
    shape if it has one (Houston: 32 x 22 in); else the height that gives the map (the board less its margins) the
    chart's own shape, which for a sectional is an estimate from its bounds: let the user enter the real height.
    """
    if not (math.isfinite(width_mm) and width_mm > 0) or (
        height_mm is not None and not (math.isfinite(height_mm) and height_mm > 0)
    ):
        raise ValueError("a board's width and height must be numbers above 0")
    if height_mm is not None:
        return width_mm, height_mm
    if chart.board_aspect:
        return width_mm, width_mm / chart.board_aspect
    map_width = width_mm * (1 - chart.margin_left - chart.margin_right)
    map_height = map_width / chart.map_aspect
    return width_mm, map_height / (1 - chart.margin_top - chart.margin_bottom)


def project(chart, lat, lon, width_mm, height_mm=None):
    """
    (x, y) in mm of a point on a board `width_mm` wide and `height_mm` high (see board_size() for the default): from
    the board's top left corner, x to the right and y down, inside the map area (the board less its margins, which are
    fractions of the board) for a point inside the chart. A board whose shape differs from the chart's stretches the
    map to fill the area. A point outside the chart's bounds still projects, outside that area; use contains() to tell.
    """
    width, height = board_size(chart, width_mm, height_mm)
    left, top, map_width, map_height = _map_area(chart, width, height)
    if chart.kind == "wall":
        x, y = _lambert_fraction(chart, lat, lon)
    else:
        x = (unwrapped(chart, lon) - chart.west) / (chart.east - chart.west)
        y = (chart.north - lat) / (chart.north - chart.south)
    return left + x * map_width, top + y * map_height


def _tan_half(phi):
    return math.tan(math.pi / 4 + phi / 2)


@lru_cache(maxsize=None)
def _lambert_constants(chart):
    """(n, f, rho0) of the chart's cone: project() and unproject() share them, so the two cannot drift apart."""
    phi1, phi2 = (math.radians(p) for p in chart.parallels)
    n = math.log(math.cos(phi1) / math.cos(phi2)) / math.log(_tan_half(phi2) / _tan_half(phi1))
    f = math.cos(phi1) * _tan_half(phi1) ** n / n
    rho0 = f / _tan_half(math.radians(chart.origin_latitude)) ** n
    return n, f, rho0


def _lambert(chart, lat, lon):
    """(x, y) of a point in a spherical Lambert conformal conic projection of the unit sphere, y up."""
    n, f, rho0 = _lambert_constants(chart)
    rho = f / _tan_half(math.radians(lat)) ** n
    theta = n * math.radians(lon - chart.central_meridian)
    return rho * math.sin(theta), rho0 - rho * math.cos(theta)


def _inverse_lambert(chart, x, y):
    """(lat, lon) in degrees of a point (x, y) in the unit-sphere Lambert projection above (the inverse of it)."""
    n, f, rho0 = _lambert_constants(chart)
    sign = math.copysign(1.0, n)
    rho = sign * math.hypot(x, rho0 - y)
    theta = math.atan2(sign * x, sign * (rho0 - y))
    lat = 2 * math.atan((f / rho) ** (1 / n)) - math.pi / 2
    return math.degrees(lat), chart.central_meridian + math.degrees(theta / n)


@lru_cache(maxsize=None)
def _wall_rectangle(chart):
    """
    (x0, x1, y0, y1) in Lambert units of the wall chart's rectangle: the smallest one holding the chart's fit points
    (the extreme points of the continental US), padded by FIT_PADDING and then grown about its centre to the printed
    shape. A chart with no fit points uses its lat/lon bounds, whose edges curve in this projection, so edge points
    are sampled; a box that flares at its corners wastes board area, which is why the fit points are the default.
    """
    points = list(chart.fit_points)
    if not points:
        for i in range(EDGE_SAMPLES + 1):
            t = i / EDGE_SAMPLES
            lat = chart.south + t * (chart.north - chart.south)
            lon = chart.west + t * (chart.east - chart.west)
            points += [(lat, chart.west), (lat, chart.east), (chart.south, lon), (chart.north, lon)]
    xs, ys = zip(*(_lambert(chart, lat, lon) for lat, lon in points))
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pad_x, pad_y = (x1 - x0) * FIT_PADDING, (y1 - y0) * FIT_PADDING
    x0, x1, y0, y1 = x0 - pad_x, x1 + pad_x, y0 - pad_y, y1 + pad_y
    width, height = x1 - x0, y1 - y0
    aspect = chart.map_aspect
    if width / height < aspect:
        grow = height * aspect - width
        x0, x1 = x0 - grow / 2, x1 + grow / 2
    else:
        grow = width / aspect - height
        y0, y1 = y0 - grow / 2, y1 + grow / 2
    return x0, x1, y0, y1


def _lambert_fraction(chart, lat, lon):
    """(x, y) of a point as fractions of the wall chart's rectangle, from its top left corner, y down."""
    x0, x1, y0, y1 = _wall_rectangle(chart)
    x, y = _lambert(chart, lat, lon)
    return (x - x0) / (x1 - x0), (y1 - y) / (y1 - y0)


def _inverse_lambert_fraction(chart, fx, fy):
    """(lat, lon) of a point given as fractions of the wall chart's rectangle (the inverse of _lambert_fraction)."""
    x0, x1, y0, y1 = _wall_rectangle(chart)
    return _inverse_lambert(chart, x0 + fx * (x1 - x0), y1 - fy * (y1 - y0))


def _map_area(chart, width, height):
    """(left, top, map_width, map_height) in mm of the map area: the board less its margins."""
    return (
        width * chart.margin_left,
        height * chart.margin_top,
        width * (1 - chart.margin_left - chart.margin_right),
        height * (1 - chart.margin_top - chart.margin_bottom),
    )


def unproject(chart, x_mm, y_mm, width_mm, height_mm=None, unwrap=False):
    """
    (lat, lon) of a point `x_mm` right and `y_mm` down from the board's top left corner: the exact inverse of
    project() for the same chart and board, whatever the margins, the explicit height or the projection. The
    longitude is in -180 to 180, so a point on the Western Aleutians chart past 180 degrees comes back as a negative
    longitude; with unwrap=True it is in the chart's own range instead (183.35, not -176.65), which is what a map that
    draws that chart continuously needs (see unwrapped()).
    """
    for name, value in (("x_mm", x_mm), ("y_mm", y_mm)):
        if not math.isfinite(value):  # a NaN would come back as a NaN position, silently
            raise ValueError(f"{name} must be a finite number, not {value!r}")
    width, height = board_size(chart, width_mm, height_mm)
    left, top, map_width, map_height = _map_area(chart, width, height)
    fx, fy = (x_mm - left) / map_width, (y_mm - top) / map_height
    if chart.kind == "wall":
        lat, lon = _inverse_lambert_fraction(chart, fx, fy)
    else:
        lat = chart.north - fy * (chart.north - chart.south)
        lon = chart.west + fx * (chart.east - chart.west)
    if lon > 180:
        lon -= 360
    return lat, unwrapped(chart, lon) if unwrap else lon


EDGE_POINTS = 16  # points along each edge of the outline: 64 in all, enough for a conic chart's curved edges


def outline(chart, width_mm, height_mm=None, per_edge=EDGE_POINTS):
    """
    The map area (the board less its margins, the shaded area on the plan) as a polygon on the earth for a page that
    draws the plan over a real map: [lat, lon] points to 5 decimals, per_edge along each edge, clockwise from the top
    left (the top edge left to right, then down the right edge, back along the bottom and up the left), the first
    point not repeated. Longitudes are in the chart's own range, so the Western Aleutians chart, which crosses the
    antimeridian, has longitudes up to 187.65 and no jump. On a conic chart the edges are curves, which is why they
    are sampled.
    """
    width, height = board_size(chart, width_mm, height_mm)
    left, top, map_width, map_height = _map_area(chart, width, height)
    right, bottom = left + map_width, top + map_height
    points = []
    for k in range(per_edge):
        t = k / per_edge
        points.append((left + t * map_width, top))  # across the top
    for k in range(per_edge):
        t = k / per_edge
        points.append((right, top + t * map_height))  # down the right
    for k in range(per_edge):
        t = k / per_edge
        points.append((right - t * map_width, bottom))  # back along the bottom
    for k in range(per_edge):
        t = k / per_edge
        points.append((left, bottom - t * map_height))  # up the left
    out = []
    for x, y in points:
        lat, lon = unproject(chart, x, y, width, height, unwrap=True)
        out.append([round(lat, 5), round(lon, 5)])
    return out
