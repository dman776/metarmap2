"""
Tests for config.Config: airports in config.json (moved there once from an older airports.json), the number of
LEDs, and editing and re-ordering airports.
"""

import json
from pathlib import Path

import pytest

from metarmap.config import MAX_LEDS, Config, airports_from_json, parse_code
from metarmap.settings import Settings

REPO = Path(__file__).parent.parent

OLD_AIRPORTS = {
    "KHOU": {"text": "Hobby", "display": True},
    "NULL1": {"text": "", "display": False},
    "KIAH": {"text": 0, "display": False},
    "KGLS": {"text": "Galveston", "display": True, "visits": 3},
}


def codes(config):
    return [a.code for a in config.airports]


@pytest.fixture
def old_map(tmp_path, monkeypatch):
    """An older map's folder: config.json (with airports_file) and airports.json, as the service runs it."""
    monkeypatch.chdir(tmp_path)
    settings = json.loads((REPO / "config.json").read_text())
    del settings["airports"]
    settings["airports_file"] = "airports.json"
    settings["led"]["count"] = 6
    (tmp_path / "config.json").write_text(json.dumps(settings, indent=4))
    (tmp_path / "airports.json").write_text(json.dumps(OLD_AIRPORTS, indent=4))
    return tmp_path


@pytest.fixture
def config(tmp_path):
    settings = Settings()
    settings.led.count = 4
    settings.airports = airports_from_json(
        {"KHOU": {"text": "Hobby", "display": True}, "KIAH": {}, "NULL1": {}, "KGLS": {"display": True}}
    )
    settings.save(tmp_path / "config.json")
    return Config(str(tmp_path / "config.json"))


# ---- moving airports.json into config.json --------------------------------------------------------------------


def test_airports_move_into_config_json(old_map):
    before = json.loads((old_map / "config.json").read_text())
    config = Config("config.json")

    saved = json.loads((old_map / "config.json").read_text())
    assert "airports_file" not in saved
    assert saved["airports"] == [
        {"code": "KHOU", "name": "Hobby", "display": True},
        {"code": "", "name": "", "display": False},  # NULL1 was a placeholder
        {"code": "KIAH", "name": "", "display": False},  # "text": 0 in older files
        {"code": "KGLS", "name": "Galveston", "display": True, "visits": 3},  # other keys are kept
    ]
    # every other setting is unchanged
    assert {k: v for k, v in saved.items() if k != "airports"} == {
        k: v for k, v in before.items() if k != "airports_file"
    }
    assert json.loads((old_map / "airports.json").read_text()) == OLD_AIRPORTS  # kept as a backup
    assert codes(config) == ["KHOU", "", "KIAH", "KGLS", "", ""]  # padded to led.count (6)


def test_the_move_happens_once(old_map):
    Config("config.json")
    (old_map / "airports.json").write_text(json.dumps({"KXXX": {}}))  # e.g. an old backup restored by an update
    assert codes(Config("config.json"))[0] == "KHOU"


def test_no_airports_json(old_map):
    (old_map / "airports.json").unlink()
    config = Config("config.json")
    assert codes(config) == [""] * 6
    assert "airports" not in json.loads((old_map / "config.json").read_text())  # nothing saved; it can try again


def test_the_repo_config_has_its_airports():
    raw = json.loads((REPO / "config.json").read_text())
    assert "airports_file" not in raw
    assert len(raw["airports"]) == raw["led"]["count"]


def test_airports_round_trip(config, tmp_path):
    config.edit("display_screen.delay", "3")
    assert Config(str(tmp_path / "config.json")).airports == config.airports
    assert config.airports[0].name == "Hobby"


def test_airports_are_not_a_single_setting(config):
    with pytest.raises(KeyError):
        config.edit("airports", "[]")


# ---- the number of LEDs ---------------------------------------------------------------------------------------


def test_more_leds_get_no_airport(config):
    config.set_led_count("6")
    assert config.data.led.count == 6
    assert codes(config) == ["KHOU", "KIAH", "", "KGLS", "", ""]


def test_fewer_leds_drop_the_last_airports(config):
    config.edit("led.count", "2")  # the Settings page's led.count goes the same way
    assert config.data.led.count == 2
    assert codes(config) == ["KHOU", "KIAH"]


def test_no_leds_leaves_only_virtual_airports(tmp_path):
    settings = Settings()
    settings.led.count = 2
    settings.airports = airports_from_json({"KHOU": {}, "KIAH": {}, "KGLS": {}})
    settings.save(tmp_path / "config.json")
    config = Config(str(tmp_path / "config.json"))
    config.set_led_count("0")
    assert config.data.led.count == 0 and codes(config) == ["KGLS"] and config.is_virtual(0)


@pytest.mark.parametrize("count", ["-3", "1001", "many", "2.5"])
def test_led_count_limits(config, count):
    with pytest.raises(ValueError):
        config.set_led_count(count)
    assert len(config.airports) == 4


def test_airports_past_the_strip_are_kept(tmp_path):
    settings = Settings()
    settings.led.count = 2
    settings.airports = airports_from_json({"KHOU": {}, "KIAH": {}, "KGLS": {}})
    settings.save(tmp_path / "config.json")
    config = Config(str(tmp_path / "config.json"))
    assert codes(config) == ["KHOU", "KIAH", "KGLS"]
    # they were on the web map only already: now they're virtual airports
    assert config.data.led.virtual_count == 1 and config.is_virtual(2) and not config.is_virtual(1)


# ---- virtual airports -----------------------------------------------------------------------------------------


def test_virtual_airports_come_after_the_leds(config):
    config.edit("led.virtual_count", "2")
    assert config.data.led.virtual_count == 2
    assert codes(config) == ["KHOU", "KIAH", "", "KGLS", "", ""]
    assert [config.is_virtual(p) for p in range(6)] == [False] * 4 + [True] * 2


def test_led_count_keeps_the_virtual_airports(config):
    config.set_virtual_count(1)
    config.set_airport(4, "code", "KDWH")
    config.set_led_count(5)  # a new LED goes at the end of the strip, before the virtual airport
    assert codes(config) == ["KHOU", "KIAH", "", "KGLS", "", "KDWH"]
    config.set_led_count(2)  # the last LEDs' airports go; the virtual one stays
    assert codes(config) == ["KHOU", "KIAH", "KDWH"]
    assert config.is_virtual(2)


def test_fewer_virtual_airports_drop_the_last(config):
    config.set_virtual_count(2)
    config.set_airport(5, "code", "KDWH")
    config.set_virtual_count(1)
    assert codes(config) == ["KHOU", "KIAH", "", "KGLS", ""]
    config.set_virtual_count(0)
    assert len(config.airports) == 4


def test_leds_and_virtual_airports_share_the_limit(config):
    """Every airport is part of each METAR fetch: MAX_LEDS is for both together."""
    config.set_virtual_count(MAX_LEDS - 4)
    with pytest.raises(ValueError, match="1000 airports in all"):
        config.set_led_count(5)
    with pytest.raises(ValueError):
        config.set_virtual_count(MAX_LEDS - 3)
    config.set_led_count(3)  # lowering one makes room for the other
    config.set_virtual_count(MAX_LEDS - 3)
    assert len(config.airports) == MAX_LEDS


@pytest.mark.parametrize("count", ["-1", "many", "1.5"])
def test_virtual_count_limits(config, count):
    with pytest.raises(ValueError):
        config.set_virtual_count(count)
    assert len(config.airports) == 4 and config.data.led.virtual_count == 0


# ---- editing --------------------------------------------------------------------------------------------------


def test_set_code(config):
    config.set_airport(2, "code", " kdwh ")
    assert codes(config)[2] == "KDWH"
    config.set_airport("0", "code", "-")
    assert codes(config)[0] == ""


@pytest.mark.parametrize("code", ["K", "KHOUSTON", "K-HO", "K HO"])
def test_bad_codes(config, code):
    with pytest.raises(ValueError):
        config.set_airport(0, "code", code)
    assert codes(config)[0] == "KHOU"


def test_set_name_and_display(config):
    config.set_airport(1, "name", "Bush")
    config.set_airport(1, "display", "true")
    assert (config.airports[1].name, config.airports[1].display) == ("Bush", True)
    config.set_airport(1, "name", "-")
    assert config.airports[1].name == ""
    with pytest.raises(ValueError):
        config.set_airport(1, "display", "maybe")
    with pytest.raises(ValueError):
        config.set_airport(1, "colour", "red")


@pytest.mark.parametrize("pixel", [-1, 4, "x"])
def test_no_such_led(config, pixel):
    with pytest.raises((IndexError, ValueError)):
        config.set_airport(pixel, "code", "KDWH")


def test_the_same_airport_on_two_leds(config):
    config.set_airport(2, "code", "KHOU")
    assert codes(config) == ["KHOU", "KIAH", "KHOU", "KGLS"]


# ---- re-ordering ----------------------------------------------------------------------------------------------


def test_move_up_and_down(config):
    config.move_airport(3, 0)
    assert codes(config) == ["KGLS", "KHOU", "KIAH", ""]
    config.move_airport(0, 1)
    assert codes(config) == ["KHOU", "KGLS", "KIAH", ""]
    assert config.airports[1].display is True  # the name and OLED flag move with it


def test_move_saves(config, tmp_path):
    config.move_airport(0, 3)
    assert [a["code"] for a in json.loads((tmp_path / "config.json").read_text())["airports"]] == [
        "KIAH",
        "",
        "KGLS",
        "KHOU",
    ]


def test_move_out_of_range(config):
    with pytest.raises(IndexError):
        config.move_airport(0, 4)
    with pytest.raises(IndexError):
        config.move_airport(-1, 0)
    assert codes(config) == ["KHOU", "KIAH", "", "KGLS"]


# ---- the older by-code edits ----------------------------------------------------------------------------------


def test_rename_by_code(config):
    config.edit_airport("KIAH", "KDWH")
    assert codes(config) == ["KHOU", "KDWH", "", "KGLS"]
    with pytest.raises(KeyError):
        config.edit_airport("KXXX", "KDWH")


def test_properties_by_code(config):
    config.edit_airport_property("KIAH", "text", "Bush")
    config.edit_airport_property("KIAH", "display", "true")
    config.edit_airport_property("KIAH", "visits", "true")
    airport = config.airports[1]
    assert (airport.name, airport.display, airport._extra) == ("Bush", True, {"visits": True})


def test_parse_code():
    assert parse_code("kgls") == "KGLS"
    assert parse_code("") == parse_code("-") == ""
    assert parse_code("6r3") == "6R3"


# ---- changes from parallel web requests -----------------------------------------------------------------------


def test_parallel_changes_all_land(config, tmp_path):
    import threading

    config.set_led_count(40)
    threads = [threading.Thread(target=config.set_airport, args=(i, "code", f"K{i:03d}")) for i in range(40)]
    threads += [threading.Thread(target=config.set_airport, args=(i, "name", f"Airport {i}")) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    saved = json.loads((tmp_path / "config.json").read_text())
    assert [a["code"] for a in saved["airports"]] == [f"K{i:03d}" for i in range(40)]
    assert [a["name"] for a in saved["airports"]] == [f"Airport {i}" for i in range(40)]
    assert codes(config) == [f"K{i:03d}" for i in range(40)]


def test_save_keeps_the_file_mode_and_leaves_no_temp_file(config, tmp_path):
    path = tmp_path / "config.json"
    path.chmod(0o600)
    config.set_airport(0, "code", "KDWH")
    assert path.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "config.json.tmp").exists()


# ---- names ------------------------------------------------------------------------------------------------------


def test_fill_names_only_fills_empty_ones(config, tmp_path):
    assert config.fill_names({"KHOU": "Houston/Hobby Arpt", "KIAH": "Houston/Bush Intcntl", "KGLS": "Galveston"}) == 2
    assert [a.name for a in config.airports] == ["Hobby", "Houston/Bush Intcntl", "", "Galveston"]  # Hobby was typed
    assert json.loads((tmp_path / "config.json").read_text())["airports"][1]["name"] == "Houston/Bush Intcntl"
    assert config.fill_names({"KIAH": "Other"}) == 0


def test_a_new_code_clears_the_old_name(config):
    config.set_airport(0, "code", "KDWH")
    assert config.airports[0].name == ""  # "Hobby" was KHOU's
    config.set_airport(1, "name", "Bush")
    config.set_airport(1, "code", "kiah")  # the same code: the name stays
    assert config.airports[1].name == "Bush"


# ---- change events ----------------------------------------------------------------------------------------------


def listen(config, patterns="*"):
    """Every publish a subscriber to `patterns` gets, as a list of key lists."""
    heard = []
    config.subscribe(patterns, heard.append)
    return heard


def test_an_edit_publishes_its_key(config):
    heard = listen(config)
    config.edit("led.pin", "13")
    assert heard == [["led.pin"]]


def test_an_edit_that_changes_nothing_publishes_nothing(config):
    heard = listen(config)
    config.edit("led.pin", str(config.data.led.pin))
    assert heard == []


def test_a_rejected_edit_publishes_nothing(config):
    heard = listen(config)
    with pytest.raises(ValueError):
        config.edit("led.pin", "7")
    with pytest.raises(KeyError):
        config.edit("led.nothing", "1")
    assert heard == []


def test_a_setting_only_config_json_changes_is_refused(config):
    with pytest.raises(ValueError):
        config.edit("dev_mode", "true")
    with pytest.raises(KeyError):  # gone: visualizer.active is an id now
        config.edit("visualizer.numbering", "1")


def test_patterns(config):
    exact, quiet, several = (
        listen(config, "led.pin"),
        listen(config, "led.quiet_hours.*"),
        listen(config, ("tfr.nearby_nm", "led.quiet_hours.end")),
    )
    config.edit("led.pin", "13")
    config.edit("led.quiet_hours.start", "22:00")
    config.edit("led.quiet_hours.end", "06:00")
    config.edit("tfr.nearby_nm", "20")
    assert exact == [["led.pin"]]
    assert quiet == [["led.quiet_hours.start"], ["led.quiet_hours.end"]]
    assert several == [["led.quiet_hours.end"], ["tfr.nearby_nm"]]


def test_subscribers_run_in_order(config):
    order = []
    config.subscribe("*", lambda keys: order.append("first"))
    config.subscribe("*", lambda keys: order.append("second"))
    config.edit("led.pin", "13")
    assert order == ["first", "second"]


def test_one_change_with_several_keys_is_one_publish(config):
    heard = listen(config)
    config.set_airport(0, "code", "KDWH")  # KHOU had a name, which goes with it
    assert heard == [["airports.code", "airports.name"]]


def test_a_nested_change_publishes_once(config):
    heard = listen(config)
    config.edit_airport("KIAH", "KDWH")  # edit_airport -> set_airport, both locked
    assert heard == [["airports.code"]]


def test_subscribers_run_after_the_lock_is_released(config):
    import threading

    seen = []

    def check(keys):
        # another thread can take the lock: the change is finished and saved
        t = threading.Thread(target=lambda: seen.append(config._lock.acquire(timeout=1) and config._lock.release()))
        t.start()
        t.join()
        with open(config._file) as f:
            seen.append(json.load(f)["led"]["pin"])

    config.subscribe("led.pin", check)
    config.edit("led.pin", "13")
    assert seen == [None, 13]  # acquire() worked (release() returns None), and the file has the new pin


def test_a_subscriber_can_change_the_config(config):
    config.subscribe("led.pin", lambda keys: config.edit("led.order", "RGB"))
    heard = listen(config, "led.order")
    config.edit("led.pin", "13")
    assert config.data.led.order == "RGB"
    assert heard == [["led.order"]]


def test_a_failing_subscriber_is_logged_and_the_others_run(config, caplog):
    heard = []

    def fail(keys):
        raise RuntimeError("boom")

    config.subscribe("*", fail)
    config.subscribe("*", heard.append)
    config.edit("led.pin", "13")
    assert config.data.led.pin == 13
    assert heard == [["led.pin"]]
    (record,) = [r for r in caplog.records if r.name == "metarmap.config"]
    assert record.levelname == "ERROR" and record.getMessage() == "after changing led.pin: boom"
    assert record.exc_info[0] is RuntimeError  # with its traceback


@pytest.mark.parametrize(
    "change, keys",
    [
        (lambda c: c.set_airport(1, "code", "KDWH"), ["airports.code"]),
        (lambda c: c.set_airport(0, "name", "Houston Hobby"), ["airports.name"]),
        (lambda c: c.set_airport(1, "display", "true"), ["airports.display"]),
        (lambda c: c.move_airport(0, 2), ["airports.order"]),
        (lambda c: c.fill_names({"KIAH": "Bush"}), ["airports.name"]),
        (lambda c: c.edit_airport_property("KHOU", "visits", "3"), ["airports.other"]),
        (lambda c: c.set_led_count(5), ["led.count"]),
        (lambda c: c.set_virtual_count(2), ["led.virtual_count"]),
        (lambda c: c.edit("led.count", "3"), ["led.count"]),
        (lambda c: c.set_login("Pilot", "secret"), ["web_server.user", "web_server.password"]),
    ],
)
def test_airport_and_other_changes_publish(config, change, keys):
    heard = listen(config)
    change(config)
    assert heard == [keys]


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.set_airport(0, "code", "KHOU"),
        lambda c: c.set_airport(0, "name", "Hobby"),
        lambda c: c.set_airport(0, "display", "true"),
        lambda c: c.move_airport(1, 1),
        lambda c: c.fill_names({"KHOU": "Not used: Hobby has a name"}),
        lambda c: c.set_led_count(4),
        lambda c: c.set_virtual_count(0),
        lambda c: c.set_login("metar"),
    ],
)
def test_airport_changes_that_change_nothing_publish_nothing(config, change):
    heard = listen(config)
    change(config)
    assert heard == []


def test_mock_metars_publish(config):
    config.data.dev_mode = True
    heard = listen(config)
    metar = "METAR KHOU 272353Z 18010KT 10SM CLR 25/15 A3000"
    config.set_mock_metar(0, metar)
    config.set_mock_metar(0, metar)  # the same again: nothing changes
    config.set_mock_metar(0, "")
    assert heard == [["airports.mock"], ["airports.mock"]]
    config.set_mock_metar(0, metar)
    heard.clear()
    config.set_airport(0, "code", "KDWH")  # the mock was the old airport's
    assert heard == [["airports.code", "airports.name", "airports.mock"]]


# ---- spoken ATIS tunings (the Pronunciation page) --------------------------------------------------------------


def test_tunings_are_saved_as_a_whole_list(config, tmp_path):
    heard = listen(config, "speech.*")
    config.set_tunings(
        [{"text": " mnstr ", "say": " monster ", "airport": ""}, {"text": "trssh", "say": "thresh", "airport": "khou"}]
    )
    saved = Config(str(tmp_path / "config.json")).data.speech.tunings  # read back from config.json
    assert [(t.text, t.say, t.airport) for t in saved] == [("MNSTR", "monster", ""), ("TRSSH", "thresh", "KHOU")]
    config.set_tunings([{"text": "MNSTR", "say": "monster"}, {"text": "TRSSH", "say": "thresh", "airport": "KHOU"}])
    assert heard == [["speech.tunings"]]  # the same list again changes nothing
    config.set_tunings([])
    assert config.data.speech.tunings == []


@pytest.mark.parametrize(
    "items, said",
    [
        ("MNSTR", "a list"),
        ([{"text": "", "say": "x"}], "tuning 1"),
        ([{"text": "A" * 41, "say": "x"}], "up to 40"),
        ([{"text": "<B>", "say": "x"}], "isn't text an ATIS has"),
        ([{"text": "MNSTR", "say": "  "}], "say MNSTR as what"),
        ([{"text": "MNSTR", "say": "a § b"}], "say MNSTR as what"),
        ([{"text": "MNSTR", "say": "x", "airport": "HOUSTON"}], "isn't an airport code"),
        ([{"text": "MNSTR", "say": "x"}, {"text": "mnstr", "say": "y"}], "tuning 2: MNSTR is there twice"),
    ],
)
def test_tunings_that_cant_be_used(config, items, said):
    with pytest.raises(ValueError) as e:
        config.set_tunings(items)
    assert said in str(e.value)
    assert config.data.speech.tunings == []


def test_hand_edited_tunings_that_cant_be_used_are_left_out(tmp_path):
    from metarmap.settings import Settings

    settings = Settings.from_dict(
        {
            "speech": {
                "tunings": [
                    {"text": "mnstr", "say": "monster"},
                    {"text": "X", "say": ""},
                    {"text": "MNSTR", "say": "again"},
                ]
            }
        }
    )
    assert [(t.text, t.say) for t in settings.speech.tunings] == [("MNSTR", "monster")]
