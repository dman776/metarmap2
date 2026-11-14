"""
Tests for planner.apply: what the airports look like after a plan, what the summary says, and the preview's token.
Pure: no Config, no files, no web.
"""

import pytest

from metarmap.config import MAX_LEDS
from metarmap.metar import MOCK_KEY
from metarmap.planner import apply
from metarmap.settings import Airport


def airport(code, name="", display=False, **extra):
    a = Airport(code=code, name=name, display=display)
    a._extra = dict(extra)
    return a


def pixels(*codes):
    return [{"code": c} for c in codes]


def run(current, led, virtual, plan, strings, string_len, names=None):
    return apply.plan_changes(current, led, virtual, pixels(*plan), string_len, strings, names or {})


def codes_of(change):
    return [a.code for a in change.airports]


# ---- the strip ----------------------------------------------------------------------------------------------


def test_the_same_plan_changes_nothing():
    current = [airport("KHOU", "Hobby", True), airport("KIAH"), airport("KGLS")]
    change = run(current, 3, 0, ["KHOU", "KIAH", "KGLS"], 1, 3)
    s = change.summary
    assert codes_of(change) == ["KHOU", "KIAH", "KGLS"]
    assert (s["kept"], s["moved"], s["added"], s["became_virtual"], s["promoted"]) == (3, 0, [], [], [])
    assert s["unchanged"] is True and s["moves"] == []
    assert change.led_count == 3 and change.virtual_count == 0


def test_a_reorder_moves_the_airports_and_says_where():
    current = [airport("A"), airport("B"), airport("C")]
    change = run(current, 3, 0, ["C", "A", "B"], 1, 3)
    assert codes_of(change) == ["C", "A", "B"]
    assert change.summary["moved"] == 3 and change.summary["kept"] == 0
    assert change.summary["moves"] == [
        {"code": "C", "from": 2, "to": 0},
        {"code": "A", "from": 0, "to": 1},
        {"code": "B", "from": 1, "to": 2},
    ]
    assert change.summary["unchanged"] is False


def test_one_airport_that_stays_is_kept():
    change = run([airport("A"), airport("B"), airport("C")], 3, 0, ["A", "C", "B"], 1, 3)
    assert (change.summary["kept"], change.summary["moved"]) == (1, 2)


def test_a_new_airport_is_added_with_its_name_and_no_oled():
    change = run([airport("A", "Alpha", True)], 1, 0, ["A", "X"], 1, 2, {"X": "Xray Field", "A": "ignored"})
    new = change.airports[1]
    assert (new.code, new.name, new.display) == ("X", "Xray Field", False)
    assert change.summary["added"] == ["X"]
    assert change.airports[0].name == "Alpha"  # a name the Chart has is never replaced


def test_an_empty_name_is_filled_from_the_plan():
    change = run([airport("A", "")], 1, 0, ["A"], 1, 1, {"A": "Alpha Field"})
    assert change.airports[0].name == "Alpha Field"


def test_the_oled_flag_and_a_mock_metar_follow_the_code():
    current = [airport("A"), airport("B", "Bravo", True, **{MOCK_KEY: "KBBB 011200Z 00000KT 10SM CLR 20/10 A3000"})]
    change = run(current, 2, 0, ["B", "A"], 1, 2)
    b = change.airports[0]
    assert b.code == "B" and b.display is True and b.name == "Bravo" and MOCK_KEY in b._extra
    assert change.airports[1]._extra == {}
    b._extra["x"] = 1  # a copy: the Chart's own airport is not shared with the new list
    assert "x" not in current[1]._extra


def test_other_keys_of_an_airport_are_kept():
    change = run([airport("A", visits=3)], 1, 0, ["A"], 1, 1)
    assert change.airports[0]._extra == {"visits": 3}


# ---- the strip's size ---------------------------------------------------------------------------------------


def test_led_count_is_the_strings_times_their_length():
    plan = [f"K{i:03d}" for i in range(60)]
    change = run([], 0, 0, plan, 2, 50)
    assert change.led_count == 100 and len(change.airports) == 100
    assert change.summary["led_count"] == {"from": 0, "to": 100}
    assert change.summary["blank_leds"] == 40


def test_the_spare_leds_of_the_last_string_are_blank():
    change = run([airport("A")], 1, 0, ["A", "B", "C"], 1, 5)
    assert codes_of(change) == ["A", "B", "C", "", ""]
    assert change.led_count == 5 and change.summary["blank_leds"] == 2


def test_a_pixel_with_no_airport_is_a_blank_led():
    change = apply.plan_changes([airport("A")], 1, 0, [{"code": "A"}, {"code": None}, {"code": "B"}], 3, 1, {})
    assert codes_of(change) == ["A", "", "B"]
    assert change.summary["blank_leds"] == 1


def test_a_plan_that_does_not_fit_its_strip_is_refused():
    with pytest.raises(ValueError, match="strings"):
        run([], 0, 0, ["A", "B", "C"], 1, 2)


def test_an_airport_twice_in_the_plan_is_refused():
    with pytest.raises(ValueError, match="twice"):
        run([], 0, 0, ["A", "A"], 1, 2)


# ---- the virtual airports -----------------------------------------------------------------------------------


def test_dropped_airports_become_virtual_in_their_old_order():
    current = [airport("A"), airport("B", "Bravo", True), airport("C"), airport("D", "Delta")]
    change = run(current, 4, 0, ["C", "A"], 1, 2)
    assert codes_of(change) == ["C", "A", "B", "D"]
    assert change.led_count == 2 and change.virtual_count == 2
    assert change.summary["became_virtual"] == ["B", "D"]
    assert change.airports[2].name == "Bravo" and change.airports[2].display is True  # nothing about it is lost


def test_a_virtual_airport_in_the_plan_becomes_a_real_one():
    current = [airport("A"), airport("B"), airport("C", "Charlie"), airport("D")]
    change = run(current, 2, 2, ["A", "C"], 1, 2)
    assert codes_of(change) == ["A", "C", "B", "D"]  # B was dropped from the strip; D was virtual already
    assert change.summary["promoted"] == ["C"] and change.summary["became_virtual"] == ["B"]
    assert change.airports[1].name == "Charlie"
    assert change.virtual_count == 2


def test_the_virtual_airports_stay_after_the_strip():
    current = [airport("A"), airport("V1"), airport("V2")]
    change = run(current, 1, 2, ["A", "B"], 1, 2)
    assert codes_of(change) == ["A", "B", "V1", "V2"]
    assert change.summary["virtual_count"] == {"from": 2, "to": 2}
    assert change.summary["became_virtual"] == []


def test_a_virtual_placeholder_with_no_airport_is_left_out():
    current = [airport("A"), airport("V1"), airport("")]
    change = run(current, 1, 2, ["A"], 1, 1)
    assert codes_of(change) == ["A", "V1"]
    assert change.virtual_count == 1 and change.summary["blank_virtual_dropped"] == 1


def test_a_code_twice_in_the_config_is_there_once():
    current = [airport("A"), airport("B"), airport("A")]
    change = run(current, 3, 0, ["A", "B"], 1, 2)
    assert codes_of(change) == ["A", "B"] and change.summary["merged_duplicates"] == 1
    again = run([airport("A"), airport("V"), airport("V")], 1, 2, ["A"], 1, 1)
    assert codes_of(again) == ["A", "V"] and again.summary["merged_duplicates"] == 1


def test_the_new_list_never_has_a_code_twice():
    current = [airport(f"K{i:03d}") for i in range(10)] + [airport("K003"), airport("K004")]
    change = run(current, 10, 2, ["K004", "K003", "K001"], 1, 3)
    listed = [a.code for a in change.airports if a.code]
    assert len(listed) == len(set(listed))


def test_over_the_limit_is_flagged():
    current = [airport(f"K{i:03d}") for i in range(600)]
    plan = [f"P{i:03d}" for i in range(500)]
    change = run(current, 600, 0, plan, 10, 50)
    assert change.summary["airports_total"] == 1100 and change.summary["over_limit"] is True
    assert change.summary["limit"] == MAX_LEDS
    fits = run(current[:300], 300, 0, plan[:100], 2, 50)
    assert fits.summary["over_limit"] is False


# ---- the summary and the token ------------------------------------------------------------------------------


def test_the_wiring_note_names_the_first_and_last_led():
    note = run([], 0, 0, ["KAAA", "KBBB", "KCCC"], 1, 10).summary["wiring_note"]
    assert "LED 1 is KAAA" in note and "LED 3 is KCCC" in note and "10 pixels" in note
    assert "no airports" in apply.wiring_note([], 5)


def test_the_summary_is_plain_json():
    import json

    change = run([airport("A"), airport("B")], 2, 0, ["B", "X"], 1, 3, {"X": "Xray"})
    json.dumps(change.summary, allow_nan=False)


def test_the_token_follows_the_plan_the_config_and_the_result():
    current = [airport("A", "Alpha"), airport("B")]
    change = run(current, 2, 0, ["B", "A"], 1, 2)
    token = apply.fingerprint(7, current, 2, 0, change)
    assert token == apply.fingerprint(7, current, 2, 0, run(current, 2, 0, ["B", "A"], 1, 2))
    assert len(token) == 64
    assert token != apply.fingerprint(8, current, 2, 0, change)  # another plan
    edited = [airport("A", "Alpha renamed"), airport("B")]  # the Chart changed after the preview
    assert token != apply.fingerprint(7, edited, 2, 0, run(edited, 2, 0, ["B", "A"], 1, 2))
    other = run(current, 2, 0, ["A", "B"], 1, 2)
    assert token != apply.fingerprint(7, current, 2, 0, other)  # another result
