"""
Tests for config.Config: airports in config.json (moved there once from an older airports.json), the number of
LEDs, and editing and re-ordering airports.
"""
import json
from pathlib import Path

import pytest

from metarmap.config import Config, airports_from_json, parse_code
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
    settings.airports = airports_from_json({"KHOU": {"text": "Hobby", "display": True}, "KIAH": {}, "NULL1": {},
                                            "KGLS": {"display": True}})
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
    assert {k: v for k, v in saved.items() if k != "airports"} == {k: v for k, v in before.items()
                                                                   if k != "airports_file"}
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


@pytest.mark.parametrize("count", ["0", "-3", "1001", "many", "2.5"])
def test_led_count_limits(config, count):
    with pytest.raises(ValueError):
        config.set_led_count(count)
    assert len(config.airports) == 4


def test_airports_past_the_strip_are_kept(tmp_path):
    settings = Settings()
    settings.led.count = 2
    settings.airports = airports_from_json({"KHOU": {}, "KIAH": {}, "KGLS": {}})
    settings.save(tmp_path / "config.json")
    assert codes(Config(str(tmp_path / "config.json"))) == ["KHOU", "KIAH", "KGLS"]


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
    assert [a["code"] for a in json.loads((tmp_path / "config.json").read_text())["airports"]] == \
        ["KIAH", "", "KGLS", "KHOU"]


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
