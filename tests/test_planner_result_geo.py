"""
The Chart Planner's result on the earth (metarmap.web.planner): what a map that draws the plan over real tiles needs.
Each pixel's lat/lon (placed) and orig_lat/orig_lon (where its airport is), the chart's outline polygon and the bounds
around everything, all in the chart's own longitude range. The airport fetch is a fake: no network.
"""

import json
import time

import pytest

from metarmap.planner import airports as live_airports
from metarmap.planner import projection
from metarmap.web import create_app
from metarmap.web import planner as planner_web
from test_web import Client

MM = projection.MM_PER_INCH
WIDTH_IN = 32


class Airports:
    """Stands for planner.airports.load: answers with its list."""

    def __init__(self, airports):
        self.airports = airports

    def __call__(self, box, clock=None, progress=None, **kwargs):
        return live_airports.Result(self.airports, False, "2026-11-12T10:00:00+00:00", None)


def places(chart, total, low=0.1, high=0.9):
    """`total` airports spread over the middle of the chart's map area, as the weather service would give them:
    longitudes in -180 to 180 even on the chart that crosses the antimeridian."""
    columns = 8
    rows = -(-total // columns)
    out = []
    for k in range(total):
        row, column = divmod(k, columns)
        fx = low + (column + 0.5) / columns * (high - low)
        fy = low + (row + 0.5) / rows * (high - low)
        if chart.kind == "wall":
            lat, lon = projection._inverse_lambert_fraction(chart, fx, fy)
        else:
            lat, lon = chart.north - fy * (chart.north - chart.south), chart.west + fx * (chart.east - chart.west)
        out.append(
            {
                "code": f"K{k:03d}",
                "name": f"Field {k}",
                "lat": round(lat, 5),
                "lon": round(lon - 360 if lon > 180 else lon, 5),
                "rank": float(total - k),
            }
        )
    return out


@pytest.fixture
def plan(make_app, monkeypatch):
    """plan(chart_name, total=40, spread=(0.1, 0.9), **form) -> the finished job, for fresh recommended airports spread
    over that part of the chart (a narrower spread crowds them)."""

    def run(chart_name, total=40, spread=(0.1, 0.9), **form):
        chart = projection.chart_by_name(chart_name)
        services = make_app()
        monkeypatch.setattr(services.metars, "_look_up", lambda codes, timeout=30: True)
        found = places(chart, total, *spread)
        planner = planner_web.Planner(services, load=Airports(found))
        client = Client(create_app(services, ip="10.0.0.2", planner=planner))
        body = {
            "chart": chart_name,
            "source": "recommended",
            "start_fresh": True,
            "target": total,
            "suggest_sizes": False,
            "width_in": WIDTH_IN,
            **form,
        }
        status, answer = client("/config/planner/plan", method="POST", body=body)
        assert status == 202, answer
        end = time.time() + 60
        while time.time() < end:
            job = client.json("/config/planner/progress")
            if job["done"]:
                assert job["ok"], job
                job["found"] = {a["code"]: a for a in found}
                job["chart_object"] = chart
                return job
            time.sleep(0.02)
        raise AssertionError("the planner job did not finish")

    return run


def inside(point, polygon):
    """Whether (lat, lon) is inside the polygon of [lat, lon] points (ray casting)."""
    y, x = point
    hit = False
    for (y1, x1), (y2, x2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


# ---- the pixels ----------------------------------------------------------------------------------------------


def test_each_pixel_is_placed_on_the_earth_where_unproject_puts_it(plan):
    job = plan("Houston")
    chart = job["chart_object"]
    board_w, board_h = projection.board_size(chart, WIDTH_IN * MM)
    pixels = job["result"]["sheet"]["pixels"]
    assert len(pixels) == 40
    for pixel in pixels:
        lat, lon = projection.unproject(chart, pixel["x"], pixel["y"], board_w, board_h, unwrap=True)
        assert pixel["lat"] == pytest.approx(lat, abs=5.1e-6) and pixel["lon"] == pytest.approx(lon, abs=5.1e-6)


def test_each_pixel_remembers_where_its_airport_really_is(plan):
    job = plan("Houston")
    for pixel in job["result"]["sheet"]["pixels"]:
        airport = job["found"][pixel["code"]]
        assert pixel["orig_lat"] == pytest.approx(airport["lat"], abs=1e-4)
        assert pixel["orig_lon"] == pytest.approx(airport["lon"], abs=1e-4)


def test_a_moved_pixel_is_not_where_its_airport_is_but_near_it(plan):
    job = plan("Houston", total=120, spread=(0.45, 0.55))  # crowded into a tenth of the chart: pixels have to move
    pixels = job["result"]["sheet"]["pixels"]
    moved = [p for p in pixels if p["moved_mm"] > 1]
    assert moved
    for p in moved:
        assert (p["lat"], p["lon"]) != (p["orig_lat"], p["orig_lon"])
        assert abs(p["lat"] - p["orig_lat"]) < 0.5 and abs(p["lon"] - p["orig_lon"]) < 0.5  # at most 18 mm of map


def test_a_skipped_pixel_has_a_place_but_no_airport():
    chart = projection.chart_by_name("Houston")
    sheet = {"pixels": [{"x": 400.0, "y": 300.0, "code": None}, {"x": 500.0, "y": 300.0, "code": "KAAA"}]}
    found = {"KAAA": {"lat": 29.0, "lon": -95.0}}
    outline, bounds = planner_web._on_the_earth(sheet, chart, 32 * MM, 22 * MM, found)
    skipped, real = sheet["pixels"]
    assert skipped["lat"] is not None and skipped["lon"] is not None
    assert skipped["orig_lat"] is None and skipped["orig_lon"] is None
    assert (real["orig_lat"], real["orig_lon"]) == (29.0, -95.0)
    assert bounds["south"] <= min(skipped["lat"], 29.0) and bounds["north"] >= max(skipped["lat"], 29.0)
    assert len(outline) == 64


# ---- the outline and the bounds -----------------------------------------------------------------------------


def test_the_outline_is_64_points_inside_the_chart_and_encloses_its_airports(plan):
    job = plan("Houston")
    chart, result = job["chart_object"], job["result"]
    outline = result["chart"]["outline"]
    assert len(outline) == 64 and all(len(point) == 2 for point in outline)
    assert all(chart.south - 1e-4 <= lat <= chart.north + 1e-4 for lat, _lon in outline)
    assert all(chart.west - 1e-4 <= lon <= chart.east + 1e-4 for _lat, lon in outline)
    for pixel in result["sheet"]["pixels"]:
        assert inside((pixel["orig_lat"], pixel["orig_lon"]), outline), pixel["code"]


def test_the_bounds_cover_the_outline_and_every_pixel_true_and_placed(plan):
    job = plan("Houston", total=120, spread=(0.45, 0.55))
    result = job["result"]
    bounds, outline = result["chart"]["bounds"], result["chart"]["outline"]
    assert set(bounds) == {"south", "west", "north", "east"}
    assert bounds["south"] < bounds["north"] and bounds["west"] < bounds["east"]
    points = list(outline)
    for pixel in result["sheet"]["pixels"]:
        points += [[pixel["lat"], pixel["lon"]], [pixel["orig_lat"], pixel["orig_lon"]]]
    for lat, lon in points:
        assert bounds["south"] <= lat <= bounds["north"] and bounds["west"] <= lon <= bounds["east"]
    assert bounds["south"] == min(p[0] for p in points) and bounds["north"] == max(p[0] for p in points)
    assert bounds["west"] == min(p[1] for p in points) and bounds["east"] == max(p[1] for p in points)


def test_the_result_is_plain_json_with_five_decimals(plan):
    result = plan("Houston")["result"]
    text = json.dumps(result, allow_nan=False)  # raises on a NaN or an infinity
    assert text
    values = result["chart"]["bounds"].values()
    assert all(round(v, 5) == v for v in values)
    assert all(round(v, 5) == v for point in result["chart"]["outline"] for v in point)


# ---- the charts that are not an ordinary sectional ---------------------------------------------------------


def test_the_western_aleutians_are_drawn_without_a_jump_over_the_antimeridian(plan):
    job = plan("Western Aleutian Islands")
    chart, result = job["chart_object"], job["result"]
    assert chart.east > 180
    lons = [p["lon"] for p in result["sheet"]["pixels"]]
    lons += [p["orig_lon"] for p in result["sheet"]["pixels"]]
    lons += [lon for _lat, lon in result["chart"]["outline"]]
    lons += [result["chart"]["bounds"]["west"], result["chart"]["bounds"]["east"]]
    assert all(168 < lon < 188 for lon in lons), sorted(lons)[:3] + sorted(lons)[-3:]
    assert any(lon > 180 for lon in lons)  # the far side of the line is above 180, not -17x
    assert result["chart"]["bounds"]["east"] == pytest.approx(chart.east, abs=1e-4)


def test_the_wall_charts_outline_fans_out_beyond_the_continental_box(plan):
    job = plan("US Wall Planning", total=60)
    result = job["result"]
    lats = [lat for lat, _lon in result["chart"]["outline"]]
    lons = [lon for _lat, lon in result["chart"]["outline"]]
    assert min(lats) < 24 and max(lats) > 50
    assert min(lons) < -125 and max(lons) > -67
    bounds = result["chart"]["bounds"]
    assert bounds["south"] <= min(lats) and bounds["north"] >= max(lats)
    assert bounds["west"] <= min(lons) and bounds["east"] >= max(lons)
    for pixel in result["sheet"]["pixels"]:
        assert inside((pixel["orig_lat"], pixel["orig_lon"]), result["chart"]["outline"]), pixel["code"]


# ---- the plan stays on its map ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chart_name, total", [("Houston", 40), ("US Wall Planning", 120), ("Western Aleutian Islands", 24)]
)
def test_every_placed_pixel_is_inside_the_outline_and_the_bounds(plan, chart_name, total):
    result = plan(chart_name, total=total)["result"]
    outline, bounds = result["chart"]["outline"], result["chart"]["bounds"]
    assert len(result["sheet"]["pixels"]) == total
    for pixel in result["sheet"]["pixels"]:
        spot = (pixel["lat"], pixel["lon"])
        assert inside(spot, outline), (chart_name, pixel["code"], spot)
        assert bounds["south"] <= pixel["lat"] <= bounds["north"], (chart_name, pixel["code"])
        assert bounds["west"] <= pixel["lon"] <= bounds["east"], (chart_name, pixel["code"])
