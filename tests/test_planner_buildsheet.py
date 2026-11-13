import json

import pytest

from metarmap.planner.buildsheet import PowerSettings, build_sheet, power_advice
from metarmap.planner.layout import Gap, Item, Pin, Plan, Settings, plan

ROW = Settings(board_w=10000, board_h=200)


def row(count, step=70.0, settings=ROW):
    """A plan of `count` airports on a line, `step` mm apart (the wire reaches, so no extension is needed)."""
    return plan([Pin(f"K{n:03d}", 20 + n * step, 100) for n in range(count)], settings)


def two_apart(distance, **options):
    settings = Settings(board_w=2000, board_h=500, **options)
    return plan([Pin("KAAA", 100, 100), Pin("KBBB", 100 + distance, 100)], settings), settings


def test_a_row_that_reaches_needs_no_cuts():
    planned = row(12)
    sheet = build_sheet(planned, ROW)
    assert sheet["problems"]["ok"] is True
    assert sheet["cuts"] == []
    assert sheet["shopping"]["extensions"] == 0
    assert sheet["shopping"]["splices"] == 0
    assert sheet["shopping"]["extension_wire_mm"] == 0.0
    assert [p["code"] for p in sheet["pixels"]] == [item.code for item in planned.items]
    assert all(entry["status"] in ("ok", "slack") for entry in sheet["route"])
    assert len(sheet["route"]) == 11


def test_pixels_are_numbered_in_led_order_with_their_string_and_position():
    sheet = build_sheet(row(120), ROW)
    pixels = sheet["pixels"]
    assert [p["index"] for p in pixels] == list(range(120))
    assert [p["number"] for p in pixels] == list(range(1, 121))
    assert (pixels[0]["string"], pixels[0]["position"]) == (1, 1)
    assert (pixels[49]["string"], pixels[49]["position"]) == (1, 50)
    assert (pixels[50]["string"], pixels[50]["position"]) == (2, 1)
    assert (pixels[119]["string"], pixels[119]["position"]) == (3, 20)


def test_one_forced_extension_is_a_cut_with_the_wire_to_splice():
    planned, settings = two_apart(200)
    sheet = build_sheet(planned, settings)
    assert planned.extensions == 1
    assert sheet["problems"]["ok"] is False
    (cut,) = sheet["cuts"]
    assert cut["between"] == [0, 1]
    assert cut["string"] == 1
    assert cut["length_mm"] == 200.0
    assert cut["extension_mm"] == 120.0
    assert sorted(cut["codes"]) == ["KAAA", "KBBB"]
    assert "cut between pixel 1" in cut["how"] and "splice in 120 mm" in cut["how"]
    assert sheet["shopping"]["extensions"] == 1
    assert sheet["shopping"]["extension_wire_mm"] == 120.0
    assert sheet["shopping"]["splices"] == 2
    (entry,) = sheet["route"]
    assert entry["kind"] == "wire" and entry["status"] == "extension" and entry["cut"] is True
    assert entry["extension_mm"] == 120.0
    assert entry["slack_mm"] == 0.0


def test_joins_fall_after_pixel_50_and_100_and_are_not_cuts():
    planned = row(120)
    sheet = build_sheet(planned, ROW)
    assert [join["between"] for join in sheet["joins"]] == [[49, 50], [99, 100]]
    assert [(j["string_a"], j["string_b"]) for j in sheet["joins"]] == [(1, 2), (2, 3)]
    assert [j["length_mm"] for j in sheet["joins"]] == [round(j["length_mm"], 1) for j in planned.joins]
    assert sheet["shopping"]["joins"] == 2
    assert sheet["shopping"]["join_cable_mm"] == round(sum(j["length_mm"] for j in sheet["joins"]), 1)
    kinds = [entry["kind"] for entry in sheet["route"]]
    assert [k for k, kind in enumerate(kinds) if kind == "join"] == [49, 99]
    assert {entry["status"] for entry in sheet["route"] if entry["kind"] == "join"} == {"join"}
    assert all(not entry["cut"] for entry in sheet["route"] if entry["kind"] == "join")
    assert all("needs no cut" in join["note"] for join in sheet["joins"])


def test_a_long_gap_at_a_join_is_a_join_and_not_a_cut():
    # 51 pixels in two clumps 500 mm apart: the long gap can sit at the join between the strings, where it is free
    pins = [Pin(f"A{n:02d}", 20 + n * 70, 100) for n in range(50)] + [Pin("ZEND", 20 + 49 * 70 + 500, 100)]
    planned = plan(pins, ROW)
    sheet = build_sheet(planned, ROW)
    assert sheet["shopping"]["extensions"] == planned.extensions == 0
    assert len(sheet["joins"]) == 1
    assert sheet["joins"][0]["length_mm"] > 400


def test_strings_and_spare_pixels():
    sheet = build_sheet(row(120), ROW)
    assert [(s["number"], s["first"], s["last"], s["pixels"], s["full"]) for s in sheet["strings"]] == [
        (1, 0, 49, 50, True),
        (2, 50, 99, 50, True),
        (3, 100, 119, 20, False),
    ]
    assert [s["spare_pixels"] for s in sheet["strings"]] == [0, 0, 30]
    assert sheet["shopping"]["spare_pixels"] == 30
    assert sheet["shopping"]["strings"] == 3
    assert sheet["shopping"]["pixels"] == 120
    assert sheet["shopping"]["airports"] == 120


def test_a_full_last_string_has_no_spare_pixels():
    sheet = build_sheet(row(50), ROW)
    assert sheet["strings"][0]["full"] is True
    assert sheet["strings"][0]["spare_pixels"] == 0
    assert sheet["joins"] == []


def test_skipped_pixels_are_in_the_chain_and_marked():
    planned, settings = two_apart(200, allow_skips=True)
    sheet = build_sheet(planned, settings)
    assert planned.skips == 2
    skipped = [p for p in sheet["pixels"] if p["skipped"]]
    assert len(skipped) == 2
    assert all(p["code"] is None and p["orig_x"] is None and p["orig_y"] is None for p in skipped)
    assert len(sheet["pixels"]) == 4
    assert sheet["shopping"]["skipped"] == 2
    assert sheet["shopping"]["airports"] == 2
    assert sheet["shopping"]["pixels"] == 4
    assert sheet["cuts"] == []
    assert sheet["problems"]["ok"] is True
    assert sheet["settings"]["allow_skips"] is True


def test_skips_that_would_help_are_explained():
    planned, settings = two_apart(200)  # skips are off: two hidden pixels would bridge the gap
    sheet = build_sheet(planned, settings)
    assert sheet["problems"]["skips_wanted"] == planned.skips_wanted == 2
    assert "2 hidden pixels would remove the extensions" in sheet["problems"]["skips_note"]
    assert "48 spare" in sheet["problems"]["skips_note"]
    assert build_sheet(row(5), ROW)["problems"]["skips_note"] == ""


def test_skips_that_do_not_fit_say_one_more_string_would():
    # a plan with 4 hidden pixels wanted and 2 spare slots, built by hand so the numbers are exact
    items = [Item("KAAA", 0, 0), Item("KBBB", 400, 0)]
    planned = Plan(
        items=items,
        strings=[[0, 1]],
        gaps=[Gap(0, 400.0, "extension", 320.0)],
        extensions=1,
        skips_wanted=4,
        spare_pixels=2,
    )
    note = build_sheet(planned, Settings(board_w=1000, board_h=500))["problems"]["skips_note"]
    assert "4 hidden pixels would remove the extensions left" in note
    assert "only 2 spare" in note and "one more string of 50" in note
    planned.skips_wanted = 1
    assert build_sheet(planned, Settings(board_w=1000, board_h=500))["problems"]["skips_note"].startswith(
        "1 hidden pixel would"
    )


def test_moved_pixels_keep_their_true_spot():
    settings = Settings(board_w=2000, board_h=500)
    planned = plan([Pin("KAAA", 500, 200), Pin("KBBB", 505, 200)], settings)
    sheet = build_sheet(planned, settings)
    assert planned.moved >= 1
    assert sheet["shopping"]["moved"] == planned.moved
    moved = [p for p in sheet["pixels"] if p["moved_mm"] > 0]
    assert moved
    for p in moved:
        assert (p["x"], p["y"]) != (p["orig_x"], p["orig_y"])
    assert {(p["orig_x"], p["orig_y"]) for p in sheet["pixels"]} == {(500.0, 200.0), (505.0, 200.0)}


def test_crowding_and_drops_are_reported():
    settings = Settings(board_w=2000, board_h=500, max_move=2.0)
    pins = [Pin(f"K{n:02d}", 500 + n, 200, rank=n) for n in range(6)]
    planned = plan(pins, settings)
    sheet = build_sheet(planned, settings)
    assert planned.crowded and planned.drops
    assert sheet["problems"]["ok"] is False
    assert sheet["problems"]["crowded"] == [list(cluster) for cluster in planned.crowded]
    assert sheet["problems"]["drops"] == [{"code": d.code, "crowding": d.crowding} for d in planned.drops]
    assert sheet["shopping"]["dropped"] == len(planned.drops)


def test_clipped_pins_are_reported():
    settings = Settings(board_w=1000, board_h=500)
    planned = plan([Pin("KOFF", -50, 100), Pin("KON", 300, 100)], settings)
    sheet = build_sheet(planned, settings)
    assert sheet["problems"]["clipped"] == ["KOFF"]
    assert sheet["shopping"]["clipped"] == 1


def test_start_and_board():
    settings = Settings(board_w=812.8, board_h=558.8, start_corner="tl")
    planned = plan([Pin("KAAA", 700, 400), Pin("KBBB", 100, 100), Pin("KCCC", 400, 300)], settings)
    sheet = build_sheet(planned, settings)
    assert sheet["start"]["index"] == 0
    assert sheet["start"]["corner"] == "tl"
    assert sheet["start"]["code"] == sheet["pixels"][0]["code"] == planned.items[0].code
    assert (sheet["start"]["x"], sheet["start"]["y"]) == (sheet["pixels"][0]["x"], sheet["pixels"][0]["y"])
    assert sheet["board"] == {"width_mm": 812.8, "height_mm": 558.8, "width_in": 32.0, "height_in": 22.0}
    assert build_sheet(planned, settings, board_in=(32.0, 22.0))["board"]["width_in"] == 32.0
    assert build_sheet(planned, settings, board_in=(31.5, 21.5))["board"]["height_in"] == 21.5


def test_slack_is_what_the_wire_has_to_spare():
    planned, settings = two_apart(50)
    sheet = build_sheet(planned, settings)
    (entry,) = sheet["route"]
    assert entry["length_mm"] == 50.0
    assert entry["slack_mm"] == 30.0
    assert entry["status"] in ("ok", "slack")
    assert sheet["cuts"] == []


def test_no_airports_does_not_crash():
    settings = Settings(board_w=1000, board_h=500)
    sheet = build_sheet(plan([], settings), settings)
    assert sheet["pixels"] == [] and sheet["route"] == [] and sheet["strings"] == []
    assert sheet["start"] is None
    assert sheet["problems"]["ok"] is True
    assert sheet["power"]["feed_points"] == []
    json.dumps(sheet)


def test_the_sheet_is_plain_json():
    planned, settings = two_apart(200, allow_skips=True, start_corner="bl")
    for sheet in (
        build_sheet(planned, settings),
        build_sheet(row(120), ROW),
        build_sheet(plan([Pin("A", 1, 1)], Settings(board_w=100, board_h=100)), Settings(board_w=100, board_h=100)),
    ):
        assert json.loads(json.dumps(sheet, allow_nan=False)) == sheet


# ---- power ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pixels,voltage",
    [(0, 5), (1, 5), (50, 5), (100, 5), (101, 12), (300, 12), (301, 12), (800, 12)],
)
def test_the_voltage_follows_the_pixel_count(pixels, voltage):
    advice = power_advice(pixels, PowerSettings())
    assert advice["voltage"] == voltage
    assert {option["voltage"] for option in advice["options"]} == {5, 12}
    assert [option["recommended"] for option in advice["options"]].count(True) == 1
    assert 24 not in {option["voltage"] for option in advice["options"]}
    assert any("24 V" in note for note in advice["notes"])
    assert any("level shifter" in note for note in advice["notes"])
    assert any("Never mix voltages" in note for note in advice["notes"])


def test_zero_pixels_is_all_zero():
    advice = power_advice(0, PowerSettings())
    assert advice["estimated_amps"] == 0.0
    assert advice["supply_amps"] == 0
    assert advice["supply_watts"] == 0.0
    assert advice["feed_points"] == []
    json.dumps(advice)


def test_the_estimate_is_pixels_times_current_times_brightness():
    advice = power_advice(100, PowerSettings(brightness=0.5, ma_white_5v=60.0))
    assert advice["voltage"] == 5
    assert advice["ma_per_pixel"] == 60.0
    assert advice["estimated_amps"] == 3.0  # 100 x 60 mA x 0.5
    five, twelve = advice["options"]
    assert (five["amps"], five["watts"]) == (3.0, 15.0)
    assert (twelve["amps"], twelve["watts"]) == (1.25, 15.0)  # 100 x 25 mA x 0.5 at 12 V
    assert advice["brightness"] == 0.5


def test_the_supply_is_rounded_up_to_a_common_size():
    # 3.0 A x 1.25 margin = 3.75 A: the next 5 V size is 5 A
    assert power_advice(100, PowerSettings())["supply_amps"] == 5
    assert power_advice(100, PowerSettings())["supply_watts"] == 25.0
    # 50 pixels x 60 mA x 0.5 = 1.5 A x 1.25 = 1.875: 2 A
    assert power_advice(50, PowerSettings())["supply_amps"] == 2
    # 12 V: 300 x 25 mA x 0.5 = 3.75 A x 1.25 = 4.69: 5 A
    assert power_advice(300, PowerSettings())["supply_amps"] == 5
    assert power_advice(300, PowerSettings())["supply_watts"] == 60.0
    # exactly on a size stays on it: 100 pixels x 50 mA x 1.0 = 5 A with no margin
    exact = power_advice(100, PowerSettings(brightness=1.0, ma_white_5v=50.0, margin=1.0))
    assert exact["options"][0]["amps"] == 5.0 and exact["supply_amps"] == 5
    # beyond the largest size: whole multiples of it
    big = power_advice(300, PowerSettings(brightness=1.0, ma_white_12v=250.0))
    assert big["supply_amps"] % 30 == 0 and big["supply_amps"] >= 75 * 1.25


def test_feed_points_snap_to_string_joins():
    # 5 V, 100 pixels: the first pixel only (the next feed would be at pixel 100, past the end)
    assert power_advice(100, PowerSettings())["feed_points"] == [0]
    # 12 V, 250 pixels: pixel 0, then pixel 200
    assert power_advice(250, PowerSettings())["feed_points"] == [0, 200]
    # 12 V, 300 pixels: pixel 0, then pixel 200
    assert power_advice(300, PowerSettings())["feed_points"] == [0, 200]
    # a different string length: 200 snaps to the nearest join (30 x 7 = 210)
    assert power_advice(250, PowerSettings(), string_len=30)["feed_points"] == [0, 210]
    assert all(point % 30 == 0 for point in power_advice(250, PowerSettings(), string_len=30)["feed_points"])


def test_a_long_chain_is_fed_at_every_join():
    advice = power_advice(400, PowerSettings())
    assert advice["voltage"] == 12
    assert advice["feed_points"] == [0, 50, 100, 150, 200, 250, 300, 350]
    assert "every string join" in advice["reason"]
    assert power_advice(301, PowerSettings())["feed_points"] == [0, 50, 100, 150, 200, 250, 300]


def test_the_5v_feed_rule_is_every_100_pixels():
    # the advice never picks 5 V for a chain this long, but the rule for 5 V is a feed every 100 pixels
    from metarmap.planner import buildsheet

    assert buildsheet._feed_points(250, 5, 50, every_string=False) == [0, 100, 200]


def test_bad_power_settings_are_refused():
    for options in (
        {"brightness": -0.1},
        {"brightness": 1.5},
        {"brightness": float("nan")},
        {"ma_white_5v": 0},
        {"ma_white_12v": -1},
        {"margin": 0.9},
    ):
        with pytest.raises(ValueError):
            PowerSettings(**options)
    with pytest.raises(ValueError):
        power_advice(-1, PowerSettings())


def test_the_sheet_carries_the_power_advice_for_the_chain():
    sheet = build_sheet(row(120), ROW, power=PowerSettings(brightness=0.25))
    assert sheet["power"]["pixels"] == 120
    assert sheet["power"]["voltage"] == 12
    assert sheet["power"]["brightness"] == 0.25
    assert sheet["power"]["feed_points"] == [0]  # the next 12 V feed would be at pixel 200, past the end
