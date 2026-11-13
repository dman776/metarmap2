"""Tests for the Chart Planner's layout: spacing the pins out, ordering them into strings, skips, drops, sizes."""

import math
import random
from dataclasses import replace

import pytest

from metarmap.planner.layout import Pin, Settings, fill_strings, plan, recommend, sweep_sizes


def settings(**kw):
    kw.setdefault("board_w", 1000.0)
    kw.setdefault("board_h", 600.0)
    return Settings(**kw)


def grid(columns, rows, step, x0=100.0, y0=100.0):
    return [Pin(f"P{r}{c}", x0 + c * step, y0 + r * step) for r in range(rows) for c in range(columns)]


def gap_between(items, a, b):
    return math.hypot(items[a].x - items[b].x, items[a].y - items[b].y)


def spaced(n, columns=20, step=100.0, seed=2):
    """n pins on a jittered grid, far enough apart that nothing is crowded (and mostly too far for a wire)."""
    rng = random.Random(seed)
    return [
        Pin(
            f"S{k}",
            100 + (k % columns) * step + rng.uniform(-20, 20),
            100 + (k // columns) * step + rng.uniform(-20, 20),
        )
        for k in range(n)
    ]


def clusters_in_a_row(count=6, size=10, spacing=60.0, jump=150.0):
    """count clusters of size pins in a line, spacing apart inside a cluster and jump from one cluster to the next."""
    pins, x = [], 50.0
    for c in range(count):
        for k in range(size):
            pins.append(Pin(f"C{c}{k}", x, 100.0))
            x += spacing
        x += jump - spacing
    return pins


def test_declutter_keeps_min_gap_max_move_and_the_board():
    pins = [Pin("A", 500, 300), Pin("B", 505, 300), Pin("C", 502, 306), Pin("D", 1, 1), Pin("E", 4, 1)]
    s = settings()
    planned = plan(pins, s)
    assert not planned.crowded
    for item in planned.items:
        assert 0 <= item.x <= s.board_w and 0 <= item.y <= s.board_h
        assert item.moved_mm <= s.max_move + 1e-6
        assert math.hypot(item.x - item.orig_x, item.y - item.orig_y) == pytest.approx(item.moved_mm)
    for a in range(len(pins)):
        for b in range(a + 1, len(pins)):
            assert gap_between(planned.items, a, b) >= s.min_gap - 1e-6
    assert planned.moved == 5


def test_a_grid_at_the_pitch_needs_no_extension():
    planned = plan(grid(5, 5, 80.0), settings(start_corner="tl"))
    assert planned.extensions == 0
    assert planned.moved == 0
    assert [len(string) for string in planned.strings] == [25]
    assert planned.items[0].code == "P00"


def test_a_pair_200_mm_apart_needs_an_extension():
    planned = plan([Pin("A", 100, 100), Pin("B", 300, 100)], settings())
    assert planned.extensions == 1
    gap = planned.gaps[0]
    assert gap.status == "extension"
    assert gap.length_mm == pytest.approx(200)
    assert gap.extension_mm == pytest.approx(120)


@pytest.mark.parametrize("far, hidden", [(160, 1), (200, 2)])
def test_skipped_pixels_bridge_a_gap_instead_of_an_extension(far, hidden):
    pins = [Pin("A", 100, 100), Pin("B", 100 + far, 100)]
    planned = plan(pins, settings(allow_skips=True))
    assert planned.extensions == 0
    assert planned.skips == hidden
    assert len(planned.items) == 2 + hidden
    middle = planned.items[1]
    assert middle.skipped and middle.code is None
    assert middle.y == pytest.approx(100)
    assert plan(pins, settings()).skips == 0  # only when allowed


def test_a_skipped_pixel_keeps_min_gap_from_the_airports():
    pins = [Pin("A", 100, 100), Pin("B", 260, 100), Pin("C", 180, 110)]
    planned = plan(pins, settings(allow_skips=True, start_corner="tl"))
    for a in range(len(planned.items)):
        for b in range(a + 1, len(planned.items)):
            assert gap_between(planned.items, a, b) >= 18 - 1e-6


def test_the_join_between_strings_is_free():
    pins = [Pin(f"L{k}", 100 + k * 50, 100) for k in range(3)] + [Pin(f"R{k}", 700 + k * 50, 100) for k in range(3)]
    joined = plan(pins, settings(string_len=3, start_corner="tl"))  # two strings: the long gap is the join
    assert joined.extensions == 0
    assert [len(string) for string in joined.strings] == [3, 3]
    assert {joined.items[k].code for k in joined.strings[0]} == {"L0", "L1", "L2"}
    one = plan(pins, settings(string_len=6, start_corner="tl"))  # one string: nowhere to hide it
    assert one.extensions == 1


def test_a_long_gap_at_the_fixed_join_is_free():
    pins = [Pin(f"A{k}", 50 + k * 60, 100) for k in range(4)] + [Pin(f"B{k}", 500 + k * 60, 100) for k in range(4)]
    planned = plan(pins, settings(string_len=4, start_corner="tl"))
    assert planned.extensions == 0
    assert [planned.items[k].code for k in planned.strings[1]] == ["B0", "B1", "B2", "B3"]
    (join,) = planned.joins
    assert join["index"] == 0 and join["between"] == (3, 4)
    assert join["length_mm"] == pytest.approx(500 - (50 + 3 * 60))
    assert len(planned.gaps) == 6  # the join is not a wire gap


def test_the_search_puts_a_long_jump_at_the_join():
    pins = [Pin(f"A{k}", 100 + k * 60, 100) for k in range(50)] + [Pin(f"B{k}", 5000 + k * 60, 400) for k in range(50)]
    board = {"board_w": 8500, "board_h": 600, "start_corner": "tl"}
    assert plan(pins, settings(**board)).extensions == 0  # string_len 50: A is the first string, B the second
    assert plan(pins, settings(string_len=100, **board)).extensions == 1  # one string: nowhere to hide the jump


@pytest.mark.parametrize("n", [1, 49, 50, 51, 99, 100, 101, 150, 300])
def test_every_string_but_the_last_is_full(n):
    planned = plan(spaced(n), settings(board_w=2400, board_h=1800))
    sizes = [len(string) for string in planned.strings]
    assert sum(sizes) == n and all(size == 50 for size in sizes[:-1]) and 0 < sizes[-1] <= 50
    assert [i for string in planned.strings for i in string] == list(range(n))
    assert planned.spare_pixels == len(sizes) * 50 - n
    assert len(planned.gaps) == n - len(sizes)  # a wire gap is inside a string; the joins are not gaps
    assert [join["index"] for join in planned.joins] == list(range(len(sizes) - 1))
    for join in planned.joins:
        a, b = join["between"]
        assert (a, b) == (50 * (join["index"] + 1) - 1, 50 * (join["index"] + 1))
        assert join["length_mm"] == pytest.approx(gap_between(planned.items, a, b))


def test_no_pins_have_no_strings_joins_or_spare_pixels():
    planned = plan([], settings())
    assert planned.strings == [] and planned.joins == [] and planned.spare_pixels == 0 and planned.skips_wanted == 0


def test_the_last_string_ends_in_spare_pixels():
    one = plan([Pin("A", 100, 100), Pin("B", 160, 100)], settings())
    assert one.spare_pixels == 48 and one.joins == []
    full = plan(spaced(100), settings(board_w=2400, board_h=1800))
    assert full.spare_pixels == 0 and len(full.joins) == 1


def test_skipped_pixels_only_fill_the_spare_slots_and_never_add_a_string():
    pins = clusters_in_a_row()  # 60 pins, five jumps of 150 mm: each wants one hidden pixel
    s = settings(board_w=4500, board_h=300, allow_skips=True, start_corner="tl")
    bridged = plan(pins, s)
    assert len(bridged.strings) == 2 and len(bridged.items) == 60 + bridged.skips
    assert bridged.skips == 5 and bridged.extensions == 0 and bridged.skips_wanted == 0
    assert bridged.spare_pixels == 100 - 65
    without = plan(pins, settings(board_w=4500, board_h=300, start_corner="tl"))
    assert without.extensions > 0 and without.skips == 0
    assert without.skips_wanted >= without.extensions  # the UI can say how many hidden pixels would remove them


def test_a_skipped_pixel_is_never_the_first_or_last_of_a_string():
    for string_len in (50, 20, 13):
        pins = clusters_in_a_row(count=8, size=6, jump=160.0)
        planned = plan(
            pins, settings(board_w=5000, board_h=300, allow_skips=True, start_corner="tl", string_len=string_len)
        )
        assert planned.skips > 0
        for string in planned.strings:
            assert not planned.items[string[0]].skipped and not planned.items[string[-1]].skipped


def test_hidden_pixels_from_different_gaps_keep_their_distance():
    planned = plan(clusters_in_a_row(), settings(board_w=4500, board_h=300, allow_skips=True, start_corner="tl"))
    assert planned.skips == 5
    for a in range(len(planned.items)):
        for b in range(a + 1, len(planned.items)):
            assert gap_between(planned.items, a, b) >= 18 - 1e-6


def test_skips_stop_at_the_spare_slots_and_say_how_many_more_are_wanted():
    pins = clusters_in_a_row(count=5, size=10)  # 50 pins: no spare slot, four 150 mm jumps
    full = plan(pins, settings(board_w=4500, board_h=300, allow_skips=True, start_corner="tl"))
    assert full.skips == 0 and full.spare_pixels == 0 and len(full.strings) == 1
    assert full.extensions == 4 and full.skips_wanted == 4
    pins = clusters_in_a_row(count=5, size=10)[:-1]  # 49 pins: one spare slot, so only one jump can be bridged
    one = plan(pins, settings(board_w=4500, board_h=300, allow_skips=True, start_corner="tl"))
    assert one.skips == 1 and one.spare_pixels == 0 and len(one.strings) == 1
    assert one.extensions == 3 and one.skips_wanted == 3


def test_a_skip_that_pushes_a_free_gap_off_a_join_is_followed_by_another():
    xs = [
        100,
        160,
        310,
        370,
        520,
        580,
    ]  # the 150 mm jumps: between 160 and 310 (inside a string) and 370 and 520 (a join)
    pins = [Pin(f"P{k}", x, 100) for k, x in enumerate(xs)]
    s = settings(board_w=1000, board_h=300, string_len=4, start_corner="tl")
    assert plan(pins, s).extensions == 1  # the jump inside the string needs an extension; the one at the join is free
    bridged = plan(pins, replace(s, allow_skips=True))
    assert bridged.skips == 2 and bridged.extensions == 0  # the first skip moves the join off the second jump
    assert [item.skipped for item in bridged.items] == [False, False, True, False, False, True, False, False]
    assert [len(string) for string in bridged.strings] == [4, 4] and bridged.spare_pixels == 0


def test_skips_are_dropped_when_they_do_not_lower_the_extensions():
    xs = [100, 160, 310, 370, 520, 580, 640]  # as above, but one spare slot: a single skip only moves the problem
    pins = [Pin(f"P{k}", x, 100) for k, x in enumerate(xs)]
    planned = plan(pins, settings(board_w=1000, board_h=300, string_len=4, allow_skips=True, start_corner="tl"))
    assert planned.skips == 0 and len(planned.items) == 7 and planned.spare_pixels == 1
    assert planned.extensions == 1 and planned.skips_wanted == 1


def test_skips_wanted_counts_a_gap_one_more_pixel_can_bridge():
    pins = [Pin(f"P{k}", x, 100) for k, x in enumerate([100, 160, 310, 370, 430, 490, 550])]  # one 150 mm jump
    s = settings(board_w=1000, board_h=300, string_len=4, start_corner="tl")
    without = plan(pins, s)
    assert without.extensions == 1 and without.skips_wanted == 1  # counted although skips are off
    with_skips = plan(pins, replace(s, allow_skips=True))
    assert with_skips.extensions == 0 and with_skips.skips == 1 and with_skips.skips_wanted == 0


@pytest.mark.parametrize("allow_skips", [False, True])
def test_skips_wanted_leaves_out_a_gap_whose_pixel_would_fall_on_a_join(allow_skips):
    # the 150 mm jump is the third gap of the first string: a hidden pixel there would be that string's last pixel,
    # where it bridges nothing, so no number of spare slots helps and none is wanted
    pins = [Pin(f"P{k}", x, 100) for k, x in enumerate([100, 160, 220, 370, 430, 490, 550])]
    planned = plan(pins, settings(board_w=1000, board_h=300, string_len=4, allow_skips=allow_skips, start_corner="tl"))
    assert planned.extensions == 1 and planned.skips == 0 and planned.spare_pixels == 1
    assert planned.skips_wanted == 0


@pytest.mark.parametrize("corner, first", [("tl", "L"), ("tr", "R"), ("bl", "L"), ("br", "R")])
def test_start_corner_starts_at_the_nearest_pin(corner, first):
    pins = [Pin("L", 100, 50), Pin("M", 200, 50), Pin("N", 300, 50), Pin("R", 400, 50)]
    planned = plan(pins, settings(board_w=500, board_h=100, start_corner=corner))
    assert planned.items[0].code == first


def test_a_bad_start_corner_is_refused():
    with pytest.raises(ValueError, match="start_corner"):
        Settings(board_w=1, board_h=1, start_corner="middle")


def test_the_same_seed_gives_the_same_plan():
    rng = random.Random(7)
    pins = [Pin(f"K{k}", rng.uniform(20, 980), rng.uniform(20, 580)) for k in range(40)]
    first = plan(pins, settings(seed=3))
    second = plan(pins, settings(seed=3))
    assert [i.code for i in first.items] == [i.code for i in second.items]
    assert first.extensions == second.extensions
    assert sorted(i.code for i in first.items) == sorted(p.code for p in pins)  # every pin used once
    short = [plan(pins, settings(seed=3, string_len=9, allow_skips=True)) for _ in range(2)]  # with joins and skips
    assert [i.code for i in short[0].items] == [i.code for i in short[1].items]
    assert short[0].joins == short[1].joins


def test_three_hundred_pins_plan_into_whole_strings():
    planned = plan(spaced(300), settings(board_w=2400, board_h=1800, start_corner="tl"))  # slow on a Pi: no time limit
    assert [len(string) for string in planned.strings] == [50] * 6
    assert len(planned.joins) == 5 and planned.spare_pixels == 0
    assert sorted(i.code for i in planned.items) == sorted(f"S{k}" for k in range(300))


def test_a_crowd_is_reported_with_drops_that_spare_the_must_keep_ones():
    pins = [Pin(f"C{k}", 500, 300, rank=float(k), must_keep=k in (0, 1)) for k in range(10)]
    pins.append(Pin("FAR", 100, 100, rank=5))
    s = settings(start_corner="tl")
    planned = plan(pins, s)
    assert len(planned.crowded) == 1
    assert "FAR" not in planned.crowded[0] and len(planned.crowded[0]) >= 8
    dropped = {drop.code for drop in planned.drops}
    assert dropped and dropped.isdisjoint({"C0", "C1", "FAR"})
    assert all(drop.crowding not in dropped for drop in planned.drops)
    again = plan([p for p in pins if p.code not in dropped], s)  # dropping them solves it
    assert not again.crowded and not again.drops


def test_the_least_important_airport_goes_first():
    pins = [Pin(f"C{k}", 500 + k, 300, rank=float(k)) for k in range(12)]
    dropped = [drop.code for drop in plan(pins, settings()).drops]
    assert dropped and "C11" not in dropped and "C0" in dropped


def test_a_crowd_loses_only_the_pins_that_cannot_fit():
    rng = random.Random(1)
    pins = [Pin(f"C{k}", 500 + rng.uniform(-3, 3), 300 + rng.uniform(-3, 3), rank=float(k)) for k in range(20)]
    s = settings()
    planned = plan(pins, s)
    dropped = [drop.code for drop in planned.drops]
    # one pixel at the spot and six around it, each 18 mm out, is all that fits within the 18 mm move: 7
    assert 6 <= len(pins) - len(dropped) <= 8
    assert dropped == sorted(dropped, key=lambda code: int(code[1:]))  # the least important first
    assert all(drop.crowding not in dropped for drop in planned.drops)
    again = plan([p for p in pins if p.code not in dropped], s)
    assert not again.crowded and not again.drops


def test_pins_at_the_very_same_spot_are_spread_out():
    pins = [Pin(f"C{k}", 500, 300, rank=float(k)) for k in range(12)]
    planned = plan(pins, settings())
    assert 12 - len(planned.drops) >= 4  # not left on top of each other
    assert plan([Pin(f"S{k}", 500, 300) for k in range(3)], settings()).crowded == []


def test_a_gaussian_cluster_keeps_what_fits_and_the_kept_ones_plan_cleanly():
    rng = random.Random(5)
    pins = [Pin(f"G{k}", 500 + rng.gauss(0, 25), 300 + rng.gauss(0, 25), rank=rng.random()) for k in range(150)]
    s = settings()
    planned = plan(pins, s)
    dropped = {drop.code for drop in planned.drops}
    assert 25 <= len(pins) - len(dropped) < 80
    assert not plan([p for p in pins if p.code not in dropped], s).crowded


def crowd_case(seed):
    """A random crowd (a gaussian blob, some pins elsewhere, some must_keep) on Darryl's 32 x 22 inch board."""
    rng = random.Random(seed)
    width, height = 32 * 25.4, 22 * 25.4
    count, spread = rng.choice([5, 10, 30, 60, 120]), rng.choice([5, 15, 30, 60])
    cx, cy = rng.uniform(0, width), rng.uniform(0, height)
    pins = [
        Pin(
            f"P{k}",
            rng.gauss(cx, spread),
            rng.gauss(cy, spread),
            rank=rng.choice([0, 1, 2, rng.random()]),
            must_keep=rng.random() < 0.15,
        )
        for k in range(count)
    ]
    pins += [
        Pin(f"Q{k}", rng.uniform(0, width), rng.uniform(0, height), rank=rng.random())
        for k in range(rng.choice([0, 20]))
    ]
    return pins, Settings(width, height, min_gap=rng.choice([18, 25]), max_move=rng.choice([0, 5, 18]))


@pytest.mark.parametrize("seed", [195, *range(0, 40)])
def test_a_crowd_is_never_left_with_nothing_to_drop(seed):
    # seed 195: the pins kept were all placed min_gap apart, but planning them again stalled 0.035 mm short of 25
    pins, s = crowd_case(seed)
    dropped = {drop.code for drop in plan(pins, s).drops}
    kept = [p for p in pins if p.code not in dropped]
    must = {p.code for p in pins if p.must_keep}
    left = [code for cluster in plan(kept, s).crowded for code in cluster]
    assert all(code in must for code in left)  # only must_keep pins, which stay whatever they crowd


def test_a_pair_a_hair_under_min_gap_is_not_crowded_but_a_real_squeeze_is():
    s = settings(max_move=0, min_gap=25)
    assert plan([Pin("A", 500, 300), Pin("B", 524.95, 300)], s).crowded == []
    assert plan([Pin("A", 500, 300), Pin("B", 524.8, 300)], s).crowded == [["A", "B"]]


def test_the_drops_name_a_pin_that_stays_even_when_the_best_one_is_in_the_crowd():
    pins = [Pin("TOP", 500, 300, rank=9, must_keep=True)] + [Pin(f"L{k}", 505 + k, 300, rank=1.0) for k in range(5)]
    planned = plan(pins, settings(max_move=0))
    dropped = {drop.code for drop in planned.drops}
    assert "TOP" not in dropped and len(dropped) == 5
    assert {drop.crowding for drop in planned.drops} == {"TOP"}


@pytest.mark.parametrize(
    "bad",
    [
        {"board_w": 0},
        {"board_h": -5},
        {"pitch": 0},
        {"pitch": float("nan")},
        {"tolerance": -1},
        {"min_gap": -1},
        {"max_move": -0.5},
        {"string_len": 0},
        {"string_len": 2.5},
        {"string_len": True},
    ],
)
def test_settings_that_would_break_the_planner_are_refused(bad):
    name = next(iter(bad))
    with pytest.raises(ValueError, match=name):
        settings(**bad)


def test_a_pin_without_a_usable_position_is_refused_by_name():
    for bad in (float("nan"), float("inf")):
        pins = [Pin("A", 100, 100), Pin("BAD", bad, 100)]
        with pytest.raises(ValueError, match="BAD"):
            plan(pins, settings())
        with pytest.raises(ValueError, match="BAD"):
            recommend(pins, settings())


def test_two_pins_with_one_code_are_refused():
    pins = [Pin("A", 100, 100), Pin("A", 300, 100)]
    with pytest.raises(ValueError, match="'A'"):
        plan(pins, settings())
    with pytest.raises(ValueError, match="'A'"):
        recommend(pins, settings())


def test_a_pin_off_the_board_is_put_on_its_edge_and_listed():
    s = settings()
    pins = [Pin("OFF", -30, -30), Pin("ALSO", 1010, 300), Pin("ON", 400, 300)]
    planned = plan(pins, s)
    assert sorted(planned.clipped) == ["ALSO", "OFF"]
    by_code = {item.code: item for item in planned.items}
    assert (by_code["OFF"].orig_x, by_code["OFF"].orig_y) == (0.0, 0.0)  # max_move counts from the edge
    assert (by_code["ALSO"].orig_x, by_code["ALSO"].orig_y) == (s.board_w, 300)
    for item in planned.items:
        assert 0 <= item.x <= s.board_w and 0 <= item.y <= s.board_h
        assert item.moved_mm <= s.max_move + 1e-6
    assert plan([Pin("ON", 400, 300)], s).clipped == []
    assert pins[0].x == -30  # the caller's pins are left as they were


def test_no_pins_and_one_pin():
    assert plan([], settings()).items == []
    one = plan([Pin("A", 10, 10)], settings())
    assert [i.code for i in one.items] == ["A"] and one.gaps == [] and one.strings == [[0]]


def test_slack_gaps_are_counted():
    planned = plan([Pin("A", 100, 100), Pin("B", 125, 100)], settings())
    assert planned.slack_gaps == 1 and planned.gaps[0].status == "slack"


def test_recommend_keeps_the_must_keep_pins_the_target_and_the_spacing():
    rng = random.Random(1)
    pins = [Pin(f"K{k}", rng.uniform(0, 120), rng.uniform(0, 120), rank=rng.random()) for k in range(80)]
    pins[5] = Pin("MUST", 60, 60, rank=0.0, must_keep=True)
    s = settings(board_w=120, board_h=120)
    chosen = recommend(pins, s, target=12)
    assert len(chosen) == 12
    assert "MUST" in {p.code for p in chosen}
    assert not plan(chosen, s).crowded  # they all fit, spaced out
    everything = recommend(pins, s)
    assert 12 < len(everything) < 80
    assert not plan(everything, s).crowded
    ranks = sorted((p.rank for p in pins if p.code != "MUST"), reverse=True)
    assert max(p.rank for p in chosen if p.code != "MUST") == ranks[0]  # the most important is taken


def test_recommend_takes_the_must_keep_pins_even_over_the_target():
    pins = [Pin(f"M{k}", 100 + k * 100, 100, must_keep=True) for k in range(4)] + [Pin("X", 700, 300, rank=9)]
    chosen = recommend(pins, settings(), target=2)
    assert [p.code for p in chosen] == ["M0", "M1", "M2", "M3"]


def test_recommend_coverage_prefers_a_pin_far_from_the_chosen():
    pins = [Pin("A", 100, 100, rank=10), Pin("B", 150, 100, rank=9), Pin("C", 800, 100, rank=1)]
    assert [p.code for p in recommend(pins, settings(), target=2, coverage=0.0)] == ["A", "B"]
    assert [p.code for p in recommend(pins, settings(), target=2, coverage=1.0)] == ["A", "C"]


def test_fill_strings_rounds_up_to_whole_strings():
    assert [fill_strings(n) for n in (0, 1, 50, 51, 99, 100, 101)] == [50, 50, 50, 100, 100, 100, 150]
    assert fill_strings(7, string_len=5) == 10


def test_sweep_sizes_lists_the_best_size_first():
    def make_pins(width):
        step = width / 10
        return grid(4, 4, step, x0=0, y0=0)

    def settings_for(width):
        return settings(board_w=width, board_h=width)

    results = sweep_sizes(make_pins, [30, 320, 1600], settings_for)
    assert [r.width_mm for r in results] == [320, 1600, 30]
    assert results[0].extensions == 0 and results[0].crowded == 0
    assert results[1].extensions > 0 and results[1].crowded == 0
    assert results[2].crowded > 0 and results[2].drops > 0
