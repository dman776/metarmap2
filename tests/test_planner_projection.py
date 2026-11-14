import pytest

from metarmap.planner import projection
from metarmap.planner.projection import board_size, chart_by_name, charts, contains, project

BOARD_MM = 32 * 25.4

AIRPORTS = {  # code: (lat, lon)
    "KSEA": (47.449, -122.309),
    "KLAX": (33.943, -118.408),
    "KHOU": (29.645, -95.279),
    "KJFK": (40.640, -73.779),
}


def test_charts_are_the_sectionals_then_the_wall_chart():
    found = charts()
    assert len(found) == 56
    assert [c.kind for c in found].count("wall") == 1 and found[-1].kind == "wall"
    assert found[-1].name == "US Wall Planning"


def test_the_wall_chart_is_not_in_the_web_maps_chart_list():
    from metarmap.web import views

    assert "US Wall Planning" not in [c["name"] for c in views.load_sectionals()]


def test_chart_by_name_ignores_case_and_gives_none_for_an_unknown_name():
    assert chart_by_name("houston").name == "Houston"
    assert chart_by_name(" US WALL PLANNING ").kind == "wall"
    assert chart_by_name("Atlantis") is None


def test_the_wall_chart_has_the_printed_ratio_and_no_margins():
    wall = chart_by_name("US Wall Planning")
    assert wall.map_aspect == 59 / 36
    assert (wall.margin_left, wall.margin_bottom, wall.margin_top, wall.margin_right) == (0, 0, 0, 0)
    width, height = board_size(wall, BOARD_MM)
    assert width == BOARD_MM
    assert height / 25.4 == pytest.approx(32 * 36 / 59)  # 19.53 in
    assert height / 25.4 == pytest.approx(19.53, abs=0.005)


def test_houstons_board_is_darryls_32_by_22_inches_with_his_measured_margins():
    houston = chart_by_name("Houston")
    assert houston.board_aspect == pytest.approx(32 / 22)
    assert houston.margin_left == pytest.approx(10 / BOARD_MM)
    assert houston.margin_bottom == pytest.approx(7 / (22 * 25.4))
    assert houston.margin_top == 0 and houston.margin_right == 0
    width, height = board_size(houston, BOARD_MM)
    assert width == BOARD_MM
    assert height / 25.4 == pytest.approx(22)  # not the 23.44 in its bounds would estimate
    # the map's west edge is 10 mm in and its south edge 7 mm up from the bottom, as measured on that board
    x, y = project(houston, houston.south, houston.west, BOARD_MM)
    assert x == pytest.approx(10)
    assert height - y == pytest.approx(7)


def test_a_sectional_without_a_measured_board_estimates_its_shape_from_its_bounds():
    chart = chart_by_name("Los Angeles")
    assert chart.board_aspect is None
    width, height = board_size(chart, BOARD_MM)
    map_width = width * (1 - chart.margin_left)
    map_height = height * (1 - chart.margin_bottom)
    assert map_width / map_height == pytest.approx(chart.map_aspect)


def test_only_houston_has_a_measured_board_and_the_other_sectionals_keep_their_estimate():
    for chart in charts():
        if chart.kind == "wall" or chart.name == "Houston":
            continue
        assert chart.board_aspect is None, chart.name
        width, height = board_size(chart, BOARD_MM)
        assert height == pytest.approx(width * (1 - chart.margin_left) / chart.map_aspect / (1 - chart.margin_bottom))


def test_an_explicit_height_wins_for_every_kind_of_chart():
    for name in ("Houston", "Los Angeles", "US Wall Planning"):
        assert board_size(chart_by_name(name), BOARD_MM, 500.0) == (BOARD_MM, 500.0)


def test_the_margins_scale_with_an_explicit_height():
    houston = chart_by_name("Houston")
    _, y = project(houston, houston.south, houston.west, BOARD_MM, 600.0)
    assert 600.0 - y == pytest.approx(600.0 * houston.margin_bottom)
    x, _ = project(houston, houston.south, houston.west, BOARD_MM, 600.0)
    assert x == pytest.approx(10)  # the left margin is a fraction of the width, which did not change
    # the same point on a taller board is the same fraction of the way down the map area
    _, y_mid = project(houston, 30.0, -94.0, BOARD_MM, 600.0)
    _, y_mid_2 = project(houston, 30.0, -94.0, BOARD_MM, 1200.0)
    assert y_mid_2 == pytest.approx(y_mid * 2)


def test_a_board_with_no_size_is_refused():
    houston = chart_by_name("Houston")
    for width, height in ((0, None), (-5, None), (BOARD_MM, 0), (BOARD_MM, -1)):
        with pytest.raises(ValueError):
            board_size(houston, width, height)


def test_a_board_with_a_size_that_is_not_a_number_is_refused():
    houston = chart_by_name("Houston")
    for width, height in (
        (float("nan"), None),
        (float("inf"), None),
        (BOARD_MM, float("nan")),
        (BOARD_MM, float("inf")),
    ):
        with pytest.raises(ValueError):
            board_size(houston, width, height)
        with pytest.raises(ValueError):
            project(houston, 29.6, -95.3, width, height)


def test_the_western_aleutians_cross_the_antimeridian_and_adak_is_on_that_chart():
    aleutians = chart_by_name("Western Aleutian Islands")
    assert aleutians.east > 180  # its bounds run past 180, so west of it a longitude is negative
    assert contains(aleutians, 51.88, -176.65)  # Adak (PADK)
    assert contains(aleutians, 52.72, 174.11)  # Shemya (PASY), on the far side
    assert not contains(aleutians, 51.88, -150.0) and not contains(aleutians, 51.88, 160.0)
    assert not contains(chart_by_name("Houston"), 51.88, -176.65)


def test_the_western_aleutians_run_east_across_the_antimeridian_left_to_right():
    aleutians = chart_by_name("Western Aleutian Islands")
    width, height = board_size(aleutians, BOARD_MM)
    shemya = project(aleutians, 52.72, 174.11, BOARD_MM)
    adak = project(aleutians, 51.88, -176.65, BOARD_MM)
    assert 0 <= shemya[0] < adak[0] <= width and 0 <= adak[1] <= height
    # a point past 180 given as a longitude of more than 180 is the same place as its negative
    assert project(aleutians, 51.88, 183.35, BOARD_MM) == pytest.approx(adak)


def test_a_sectionals_corners_are_the_corners_of_the_map_area():
    houston = chart_by_name("Houston")
    width, height = board_size(houston, BOARD_MM)
    left = width * houston.margin_left
    bottom = height * (1 - houston.margin_bottom)
    assert project(houston, houston.north, houston.west, BOARD_MM) == pytest.approx((left, 0))
    assert project(houston, houston.north, houston.east, BOARD_MM) == pytest.approx((width, 0))
    assert project(houston, houston.south, houston.west, BOARD_MM) == pytest.approx((left, bottom))
    assert project(houston, houston.south, houston.east, BOARD_MM) == pytest.approx((width, bottom))


def test_a_sectionals_projection_runs_east_to_the_right_and_north_up():
    houston = chart_by_name("Houston")
    mid_lat, mid_lon = (houston.south + houston.north) / 2, (houston.west + houston.east) / 2
    x, y = project(houston, mid_lat, mid_lon, BOARD_MM)
    assert project(houston, mid_lat, mid_lon + 1, BOARD_MM)[0] > x
    assert project(houston, mid_lat + 1, mid_lon, BOARD_MM)[1] < y


def test_a_point_outside_a_chart_still_projects_outside_the_map_area():
    houston = chart_by_name("Houston")
    assert not contains(houston, 47.4, -122.3)
    assert contains(houston, 29.6, -95.3)
    x, y = project(houston, 47.4, -122.3, BOARD_MM)
    assert x < 0 and y < 0


def test_the_wall_charts_fit_points_are_inside_its_board_and_touch_all_four_edges():
    wall = chart_by_name("US Wall Planning")
    assert wall.fit_points
    width, height = board_size(wall, BOARD_MM)
    points = [project(wall, lat, lon, BOARD_MM) for lat, lon in wall.fit_points]
    for x, y in points:
        assert 0 < x < width and 0 < y < height
    # the rectangle is the fit points' own, padded by 2%, then grown to the printed shape: it fills the board
    # in one direction and is a little roomier in the other
    assert min(x for x, _ in points) < width * 0.1 and max(x for x, _ in points) > width * 0.9
    assert min(y for _, y in points) < height * 0.1 and max(y for _, y in points) > height * 0.9


def test_the_continental_us_lands_in_the_wall_chart_in_the_right_order():
    wall = chart_by_name("US Wall Planning")
    width, height = board_size(wall, BOARD_MM)
    at = {code: project(wall, lat, lon, BOARD_MM) for code, (lat, lon) in AIRPORTS.items()}
    for x, y in at.values():
        assert 0 < x < width and 0 < y < height
    # west to east (Seattle and Los Angeles are both on the west coast, which runs nearly north and south here)
    assert max(at["KSEA"][0], at["KLAX"][0]) < at["KHOU"][0] < at["KJFK"][0]
    # north to south (y grows downward); JFK is north of LAX and Houston
    assert at["KSEA"][1] < at["KJFK"][1] < at["KLAX"][1] < at["KHOU"][1]
    # Seattle is in the top left, Houston in the lower middle, New York at the right
    assert at["KSEA"][0] < width * 0.2 and at["KSEA"][1] < height * 0.25
    assert width * 0.4 < at["KHOU"][0] < width * 0.65 and at["KHOU"][1] > height * 0.7
    assert at["KJFK"][0] > width * 0.85


def test_the_wall_chart_scales_with_the_board():
    wall = chart_by_name("US Wall Planning")
    x1, y1 = project(wall, 40.0, -100.0, BOARD_MM)
    x2, y2 = project(wall, 40.0, -100.0, BOARD_MM * 2)
    assert (x2, y2) == pytest.approx((x1 * 2, y1 * 2))


def test_the_wall_charts_central_meridian_is_a_vertical_line():
    wall = chart_by_name("US Wall Planning")
    xs = [project(wall, lat, projection.WALL_CENTRAL_MERIDIAN, BOARD_MM)[0] for lat in (26, 35, 45, 49)]
    assert xs == pytest.approx([xs[0]] * 4)


# ---- unproject ----------------------------------------------------------------------------------

FRACTIONS = (0.0, 0.013, 0.5, 0.987, 1.0)  # the corners, near them, and the centre of the map area


def map_points(chart, width_mm, height_mm=None):
    """(x, y) board points over the map area: the corners, near the corners, the centre."""
    width, height = board_size(chart, width_mm, height_mm)
    left, top, map_width, map_height = projection._map_area(chart, width, height)
    return [(left + fx * map_width, top + fy * map_height) for fx in FRACTIONS for fy in FRACTIONS]


@pytest.mark.parametrize("width_in", [12, 32, 59, 100])
@pytest.mark.parametrize("height_in", [None, 14.0])
def test_unproject_is_the_inverse_of_project_for_every_chart(width_in, height_in):
    width_mm = width_in * 25.4
    height_mm = None if height_in is None else height_in * 25.4
    for chart in charts():
        for x, y in map_points(chart, width_mm, height_mm):
            lat, lon = projection.unproject(chart, x, y, width_mm, height_mm)
            assert -90 <= lat <= 90 and -180 <= lon <= 180, chart.name
            assert project(chart, lat, lon, width_mm, height_mm) == pytest.approx((x, y), abs=1e-3), chart.name
            # and from the other side: a latitude and longitude come back as they went in
            x2, y2 = project(chart, lat, lon, width_mm, height_mm)
            lat2, lon2 = projection.unproject(chart, x2, y2, width_mm, height_mm)
            assert lat2 == pytest.approx(lat, abs=1e-6) and lon2 == pytest.approx(lon, abs=1e-6), chart.name


def test_unproject_gives_back_the_airports_that_were_projected():
    for name in ("Houston", "US Wall Planning"):
        chart = chart_by_name(name)
        for lat, lon in AIRPORTS.values():
            x, y = project(chart, lat, lon, BOARD_MM)
            assert projection.unproject(chart, x, y, BOARD_MM) == pytest.approx((lat, lon), abs=1e-6)


def test_houston_at_32_by_22_inches_has_its_margins_and_its_corners_on_the_chart():
    houston = chart_by_name("Houston")
    width, height = BOARD_MM, 22 * 25.4
    top_left = projection.unproject(houston, 10.0, 0.0, width, height)  # the left margin is 10 mm
    assert top_left == pytest.approx((houston.north, houston.west), abs=1e-6)
    bottom_right = projection.unproject(houston, width, height - 7.0, width, height)  # the bottom margin is 7 mm
    assert bottom_right == pytest.approx((houston.south, houston.east), abs=1e-6)


def test_unproject_gives_a_negative_longitude_past_the_antimeridian():
    aleutians = chart_by_name("Western Aleutian Islands")
    assert aleutians.east > 180
    x, y = project(aleutians, 51.88, -176.65, BOARD_MM)  # Adak
    lat, lon = projection.unproject(aleutians, x, y, BOARD_MM)
    assert (lat, lon) == pytest.approx((51.88, -176.65), abs=1e-6)
    west_edge = projection.unproject(aleutians, *map_points(aleutians, BOARD_MM)[0], BOARD_MM)
    assert west_edge[1] == pytest.approx(aleutians.west, abs=1e-6)  # 168 east is still 168


def test_unproject_refuses_a_board_that_is_not_a_size():
    houston = chart_by_name("Houston")
    with pytest.raises(ValueError):
        projection.unproject(houston, 10, 10, float("nan"))
    with pytest.raises(ValueError):
        projection.unproject(houston, 10, 10, BOARD_MM, -5)


def test_unproject_can_give_the_longitude_in_the_charts_own_range():
    aleutians = chart_by_name("Western Aleutian Islands")
    width, height = board_size(aleutians, BOARD_MM)
    left, top, map_width, map_height = projection._map_area(aleutians, width, height)
    east_edge = (left + map_width, top + map_height / 2)
    _lat, wrapped = projection.unproject(aleutians, *east_edge, BOARD_MM)
    _lat, own = projection.unproject(aleutians, *east_edge, BOARD_MM, unwrap=True)
    assert wrapped == pytest.approx(aleutians.east - 360, abs=1e-6)  # -172.35, as before
    assert own == pytest.approx(aleutians.east, abs=1e-6)  # 187.65: no jump for a map that draws it continuously
    houston = chart_by_name("Houston")
    assert projection.unproject(houston, 400, 300, BOARD_MM, unwrap=True) == projection.unproject(
        houston, 400, 300, BOARD_MM
    )  # only the antimeridian chart is changed


# ---- outline -------------------------------------------------------------------------------------------------


def test_the_outline_is_64_points_clockwise_from_the_top_left():
    houston = chart_by_name("Houston")
    out = projection.outline(houston, BOARD_MM)
    assert len(out) == 64 and out[0] != out[-1]  # the first point is not repeated at the end
    assert out[0] == [pytest.approx(houston.north, abs=1e-5), pytest.approx(houston.west, abs=1e-5)]
    assert out[16][0] == pytest.approx(houston.north, abs=1e-5) and out[16][1] == pytest.approx(houston.east, abs=1e-5)
    assert out[32] == [pytest.approx(houston.south, abs=1e-5), pytest.approx(houston.east, abs=1e-5)]
    assert out[48] == [pytest.approx(houston.south, abs=1e-5), pytest.approx(houston.west, abs=1e-5)]
    assert all(len(point) == 2 for point in out)


@pytest.mark.parametrize("name", ["Houston", "Seattle", "Western Aleutian Islands", "US Wall Planning"])
def test_every_outline_point_is_the_exact_inverse_of_its_edge_position(name):
    chart = chart_by_name(name)
    width, height = board_size(chart, BOARD_MM)
    left, top, map_width, map_height = projection._map_area(chart, width, height)
    edges = [
        lambda t: (left + t * map_width, top),
        lambda t: (left + map_width, top + t * map_height),
        lambda t: (left + map_width - t * map_width, top + map_height),
        lambda t: (left, top + map_height - t * map_height),
    ]
    out = projection.outline(chart, BOARD_MM)
    for edge, points in zip(edges, (out[0:16], out[16:32], out[32:48], out[48:64])):
        for k, (lat, lon) in enumerate(points):
            expected = projection.unproject(chart, *edge(k / 16), BOARD_MM, unwrap=True)
            assert lat == pytest.approx(expected[0], abs=5.1e-6) and lon == pytest.approx(expected[1], abs=5.1e-6)


def test_the_outline_follows_the_board_that_was_planned():
    houston = chart_by_name("Houston")
    small = projection.outline(houston, 16 * 25.4)  # the same chart on half the board: the same area of the earth
    big = projection.outline(houston, 32 * 25.4)
    assert small == big
    taller = projection.outline(houston, 32 * 25.4, 30 * 25.4)  # a taller board stretches the same map area
    assert taller[0] == big[0] and taller[32] == big[32]  # it is still the chart's corners
    assert taller[1] == big[1]


def test_the_wall_charts_outline_fans_out_beyond_the_continental_us():
    out = projection.outline(chart_by_name("US Wall Planning"), BOARD_MM)
    lats, lons = [p[0] for p in out], [p[1] for p in out]
    assert min(lats) < 24 and max(lats) > 50  # the Lambert rectangle covers sea and Canada past the lower 48
    assert min(lons) < -125 and max(lons) > -67
    top = out[:16]
    assert max(p[0] for p in top) != min(p[0] for p in top)  # a conic chart's top edge is a curve, not a line


def test_an_outline_over_the_antimeridian_has_no_jump():
    aleutians = chart_by_name("Western Aleutian Islands")
    out = projection.outline(aleutians, BOARD_MM)
    lons = [p[1] for p in out]
    assert all(168 < v < 188 for v in lons)
    assert max(lons) == pytest.approx(aleutians.east, abs=1e-5) and min(lons) == pytest.approx(aleutians.west, abs=1e-5)


def test_the_outline_is_small_plain_json():
    import json

    text = json.dumps(projection.outline(chart_by_name("US Wall Planning"), BOARD_MM), allow_nan=False)
    assert len(text) < 3_000


def test_the_outline_refuses_a_board_that_is_not_a_size():
    with pytest.raises(ValueError):
        projection.outline(chart_by_name("Houston"), 0)


@pytest.mark.parametrize("x, y", [(float("nan"), 10), (10, float("nan")), (float("inf"), 10), (10, float("-inf"))])
def test_unproject_refuses_a_position_that_is_not_a_number(x, y):
    with pytest.raises(ValueError, match="finite"):
        projection.unproject(chart_by_name("Houston"), x, y, BOARD_MM)
