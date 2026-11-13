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
