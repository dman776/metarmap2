"""
Tests for Config.apply_plan and the plan backups: one write, the keys published once, the copy of config.json beside
it, and the Undo that puts back the airports and the LED counts and nothing else.
"""

import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

from metarmap.config import MAX_LEDS, PLAN_BACKUPS, Config
from metarmap.metar import MOCK_KEY
from metarmap.settings import Airport, Settings


def airport(code, name="", display=False, **extra):
    a = Airport(code=code, name=name, display=display)
    a._extra = dict(extra)
    return a


@pytest.fixture
def config(tmp_path):
    """A map with 3 LEDs (KHOU, KIAH, KGLS) and one virtual airport (KSGR); a login and a brightness to tell apart."""
    settings = Settings()
    settings.led.count = 3
    settings.led.virtual_count = 1
    settings.web_server.password = "secret-word"
    settings.airports = [
        airport("KHOU", "Hobby", True, **{MOCK_KEY: "KHOU 011200Z 00000KT 10SM CLR 20/10 A3000"}),
        airport("KIAH", "Bush"),
        airport("KGLS"),
        airport("KSGR", "Sugar Land"),
    ]
    settings.save(tmp_path / "config.json")
    return Config(str(tmp_path / "config.json"))


def listen(config, patterns="*"):
    heard = []
    config.subscribe(patterns, heard.append)
    return heard


def codes(config):
    return [a.code for a in config.airports]


def files(tmp_path, suffix=""):
    return sorted(p.name for p in tmp_path.iterdir() if ".before-plan-" in p.name and p.name.endswith(suffix))


def backups_only(tmp_path):
    return [n for n in files(tmp_path) if not n.endswith(".summary.json")]


def new_strip():
    """The same two airports in the other order, then a blank LED."""
    return [airport("KIAH", "Bush"), airport("KHOU", "Hobby", True), airport("")]


# ---- applying -------------------------------------------------------------------------------------------------


def test_apply_replaces_the_airports_and_the_counts_in_one_write(config, tmp_path):
    new = new_strip() + [airport("KGLS"), airport("KSGR", "Sugar Land")]
    done = config.apply_plan(new, 3, 2)
    assert codes(config) == ["KIAH", "KHOU", "", "KGLS", "KSGR"]
    assert (config.data.led.count, config.data.led.virtual_count) == (3, 2)
    on_disk = json.loads((tmp_path / "config.json").read_text())
    assert [a["code"] for a in on_disk["airports"]] == ["KIAH", "KHOU", "", "KGLS", "KSGR"]
    assert on_disk["led"]["count"] == 3 and on_disk["led"]["virtual_count"] == 2
    assert done["backup"].startswith("config.json.before-plan-") and done["led_count_changed"] is False
    assert "airports.order" in done["keys"]


def test_the_changes_are_published_once_with_only_what_changed(config):
    heard = listen(config)
    config.apply_plan(new_strip() + [airport("KGLS"), airport("KSGR", "Sugar Land")], 3, 2)
    assert len(heard) == 1  # one publish: the OLED, the strip and the METAR fetch follow once
    # this list has no mock METAR on KHOU, so that goes too; led.count is the same and is not published
    assert set(heard[0]) == {
        "airports.order",
        "airports.name",
        "airports.display",
        "airports.mock",
        "led.virtual_count",
    }
    assert "airports.code" not in heard[0]  # the same airports, only in another order: nothing to fetch


def test_new_and_dropped_airports_publish_the_code_key(config):
    heard = listen(config, "airports.code")
    config.apply_plan([airport("KHOU"), airport("KEFD"), airport("KGLS"), airport("KSGR")], 3, 1)
    assert heard == [["airports.code"]]


def test_a_changed_led_count_is_published_and_asks_for_a_restart(config):
    heard = listen(config, "led.*")
    done = config.apply_plan([airport(c) for c in ("KAAA", "KBBB", "KCCC", "KDDD", "KEEE")], 5, 0)
    assert heard == [["led.count", "led.virtual_count"]]
    assert done["led_count_changed"] is True and config.data.led.count == 5


def test_a_plan_that_changes_nothing_publishes_nothing(config):
    heard = listen(config)
    config.apply_plan(list(config.airports), 3, 1)
    assert heard == []


def test_other_settings_are_not_touched(config, tmp_path):
    config.edit("led.brightness.normal", "0.3")
    config.apply_plan(new_strip() + [airport("KSGR")], 3, 1)
    on_disk = json.loads((tmp_path / "config.json").read_text())
    assert on_disk["led"]["brightness"]["normal"] == 0.3 and on_disk["web_server"]["password"] == "secret-word"


def test_a_bad_list_is_refused_and_nothing_changes(config, tmp_path):
    before = (tmp_path / "config.json").read_text()
    for new, led, virtual, text in [
        ([airport("KHOU"), airport("KHOU"), airport("")], 3, 0, "twice"),
        ([airport("KHOU")], 3, 0, "airports for"),
        ([airport("KH!!")], 1, 0, "not an airport code"),
        ([], -1, 0, "over"),
        ([airport(f"K{i:03d}") for i in range(MAX_LEDS)] + [airport("KXXX")], MAX_LEDS, 1, "over"),
    ]:
        with pytest.raises(ValueError, match=text):
            config.apply_plan(new, led, virtual)
    assert (tmp_path / "config.json").read_text() == before
    assert backups_only(tmp_path) == []  # nothing was refused after a backup was made


def test_codes_are_normalised(config):
    config.apply_plan([airport("khou"), airport(" kiah "), airport("")], 3, 0)
    assert codes(config) == ["KHOU", "KIAH", ""]


def test_a_failing_write_leaves_the_old_airports_and_publishes_nothing(config, monkeypatch):
    heard = listen(config)
    before = (codes(config), config.data.led.count, config.data.led.virtual_count)

    def broken(path):
        raise OSError("disk full")

    monkeypatch.setattr(config.data, "save", broken)
    with pytest.raises(OSError):
        config.apply_plan(new_strip() + [airport("KSGR")], 3, 1, backup=False)
    assert (codes(config), config.data.led.count, config.data.led.virtual_count) == before
    assert heard == [] and config._pending == []


def test_check_can_refuse_before_anything_is_written(config, tmp_path):
    seen = []

    def check(airports, led, virtual):
        seen.append(([a.code for a in airports], led, virtual))
        raise ValueError("it changed")

    with pytest.raises(ValueError, match="it changed"):
        config.apply_plan(new_strip() + [airport("KSGR")], 3, 1, check=check)
    assert seen == [(["KHOU", "KIAH", "KGLS", "KSGR"], 3, 1)]
    assert backups_only(tmp_path) == [] and codes(config)[0] == "KHOU"


def test_layout_gives_copies(config):
    airports, led, virtual = config.layout()
    airports[0].name = "changed"
    assert (led, virtual) == (3, 1) and config.airports[0].name == "Hobby"


# ---- the backup -----------------------------------------------------------------------------------------------


def test_apply_copies_config_json_first(config, tmp_path):
    before = (tmp_path / "config.json").read_bytes()
    done = config.apply_plan(new_strip() + [airport("KSGR")], 3, 1, summary={"moved": 2})
    backup = tmp_path / done["backup"]
    assert backup.read_bytes() == before
    assert stat.S_IMODE(backup.stat().st_mode) == stat.S_IMODE((tmp_path / "config.json").stat().st_mode)
    assert len(done["backup"]) == len("config.json.before-plan-20261113-123456")
    side = json.loads((tmp_path / (done["backup"] + ".summary.json")).read_text())
    assert side["summary"] == {"moved": 2} and side["made_at"]


def test_the_backup_has_the_same_mode_as_config_json(config, tmp_path):
    os.chmod(tmp_path / "config.json", 0o600)  # it holds the web password
    done = config.apply_plan(new_strip() + [airport("KSGR")], 3, 1)
    assert stat.S_IMODE((tmp_path / done["backup"]).stat().st_mode) == 0o600


def test_two_applies_in_one_second_get_two_backups(config, tmp_path):
    config.apply_plan(new_strip() + [airport("KSGR")], 3, 1)
    config.apply_plan([airport("KGLS"), airport("KIAH"), airport(""), airport("KSGR")], 3, 1)
    assert len(backups_only(tmp_path)) == 2


def test_only_the_newest_backups_stay(config, tmp_path):
    names = []
    for i in range(PLAN_BACKUPS + 3):
        new = [airport(f"K{i:03d}"), airport("KIAH"), airport(""), airport("KSGR")]
        names.append(config.apply_plan(new, 3, 1)["backup"])
    left = backups_only(tmp_path)
    assert len(left) == PLAN_BACKUPS and left == sorted(names)[-PLAN_BACKUPS:]
    assert len(files(tmp_path, ".summary.json")) == PLAN_BACKUPS  # and their summaries; the others went with them


def test_plan_backups_lists_the_newest_first_with_its_summary(config):
    config.apply_plan(new_strip() + [airport("KSGR")], 3, 1, summary={"n": 1})
    config.apply_plan([airport("KGLS"), airport("KIAH"), airport(""), airport("KSGR")], 3, 1, summary={"n": 2})
    listed = config.plan_backups()
    assert [b["summary"] for b in listed] == [{"n": 2}, {"n": 1}]
    assert all(os.path.exists(b["path"]) and b["made_at"] for b in listed)


def test_without_a_summary_file_the_time_comes_from_the_name(config, tmp_path):
    name = config.apply_plan(new_strip() + [airport("KSGR")], 3, 1)["backup"]
    (tmp_path / (name + ".summary.json")).unlink()
    (only,) = config.plan_backups()
    assert only["summary"] is None and only["made_at"].startswith(name[-15:-11])


def test_a_backup_that_cannot_be_made_stops_the_apply(config, tmp_path, monkeypatch):
    before = (tmp_path / "config.json").read_text()

    def broken(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr("metarmap.config.shutil.copyfileobj", broken)
    with pytest.raises(OSError):
        config.apply_plan(new_strip() + [airport("KSGR")], 3, 1)
    assert (tmp_path / "config.json").read_text() == before and codes(config)[0] == "KHOU"
    assert files(tmp_path) == []  # not even a half copy of the file that holds the password


def test_the_next_backup_name_looks_like_a_backup(config):
    assert config.next_plan_backup_name().startswith("config.json.before-plan-")


# ---- undo -----------------------------------------------------------------------------------------------------


def test_undo_puts_back_the_airports_and_the_counts_only(config, tmp_path):
    original = [(a.code, a.name, a.display, dict(a._extra)) for a in config.airports]
    config.apply_plan([airport(c) for c in ("KA01", "KB02", "KC03", "KD04", "KE05")], 5, 0)
    config.edit("led.brightness.normal", "0.2")  # a change after the apply must stay
    heard = listen(config)
    done = config.restore_plan_backup()
    assert [(a.code, a.name, a.display, dict(a._extra)) for a in config.airports] == original
    assert (config.data.led.count, config.data.led.virtual_count) == (3, 1)
    assert config.data.led.brightness.normal == 0.2
    assert done["airports"] == 4 and done["led_count"] == 3 and done["virtual_count"] == 1
    assert done["led_count_changed"] is True  # led.count went from 5 back to 3
    assert len(heard) == 1 and "led.count" in heard[0] and "airports.code" in heard[0]
    assert json.loads((tmp_path / "config.json").read_text())["web_server"]["password"] == "secret-word"


def test_a_second_undo_is_refused_and_the_backup_is_marked(config, tmp_path):
    config.apply_plan(new_strip() + [airport("KSGR")], 3, 1)
    config.restore_plan_backup()
    with pytest.raises(LookupError):
        config.restore_plan_backup()
    assert config.plan_backups() == []
    assert any(n.endswith("-undone") for n in files(tmp_path))


def test_undo_goes_back_one_apply_at_a_time(config):
    config.apply_plan([airport("KA01"), airport("KB02"), airport("KC03"), airport("KSGR")], 3, 1)
    config.apply_plan([airport("KX01"), airport("KY02"), airport("KZ03"), airport("KSGR")], 3, 1)
    config.restore_plan_backup()
    assert codes(config)[:3] == ["KA01", "KB02", "KC03"]
    config.restore_plan_backup()
    assert codes(config)[:3] == ["KHOU", "KIAH", "KGLS"]


def test_undo_can_name_the_backup_and_refuses_an_unknown_one(config):
    name = config.apply_plan(new_strip() + [airport("KSGR")], 3, 1)["backup"]
    with pytest.raises(LookupError):
        config.restore_plan_backup("config.json.before-plan-19990101-000000")
    with pytest.raises(LookupError):
        config.restore_plan_backup("../config.json")  # only this config's own backups
    assert config.restore_plan_backup(name)["backup"] == name


def test_undo_with_nothing_to_undo(config):
    with pytest.raises(LookupError):
        config.restore_plan_backup()


def test_a_damaged_backup_is_refused_and_nothing_changes(config, tmp_path):
    name = config.apply_plan(new_strip() + [airport("KSGR")], 3, 1)["backup"]
    (tmp_path / name).write_text("{not json")
    before = codes(config)
    with pytest.raises(ValueError):
        config.restore_plan_backup()
    assert codes(config) == before and len(config.plan_backups()) == 1


# ---- a backup is only there for an apply that happened ---------------------------------------------------------


def plan(i):
    """A different plan each time, with KSGR virtual."""
    return [airport(f"K{i:03d}"), airport("KIAH"), airport(""), airport("KSGR")]


def clock(monkeypatch, start):
    """Makes the config's idea of now whatever when["now"] says."""
    when = {"now": start}

    class Fake(datetime):
        @classmethod
        def now(cls, tz=None):
            return when["now"] if tz is None else when["now"].astimezone(tz)

    monkeypatch.setattr("metarmap.config.datetime", Fake)
    return when


def test_a_write_that_fails_after_the_backup_leaves_no_backup_and_no_undo(config, tmp_path, monkeypatch):
    for i in range(PLAN_BACKUPS):
        config.apply_plan(plan(i), 3, 1)
    kept = backups_only(tmp_path)
    before = (tmp_path / "config.json").read_bytes()
    state = (codes(config), config.data.led.count, config.data.led.virtual_count)
    heard = listen(config)
    real = os.replace

    def broken(src, dst, *args, **kwargs):
        if str(dst).endswith("config.json"):
            raise OSError("disk full")
        return real(src, dst, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr("metarmap.settings.os.replace", broken)
        with pytest.raises(OSError):
            config.apply_plan(plan(99), 3, 1)
    assert backups_only(tmp_path) == kept  # the new copy is gone and the old ones were not pruned to make room
    assert files(tmp_path, ".summary.json") == [n + ".summary.json" for n in kept]
    assert (tmp_path / "config.json").read_bytes() == before
    assert not (tmp_path / "config.json.tmp").exists()  # it holds the web password
    assert (codes(config), config.data.led.count, config.data.led.virtual_count) == state and heard == []
    assert config.plan_backups()[0]["file"] == kept[-1]  # an Undo is offered for the last apply that happened


def test_the_backup_stays_when_the_save_went_through_but_the_read_back_failed(config, tmp_path, monkeypatch):
    before = (tmp_path / "config.json").read_bytes()

    def broken():
        raise ValueError("cannot read it back")

    monkeypatch.setattr(config, "read", broken)
    with pytest.raises(ValueError):
        config.apply_plan(new_strip() + [airport("KSGR")], 3, 1)
    assert (tmp_path / "config.json").read_bytes() != before  # the file has the new list now
    (name,) = backups_only(tmp_path)
    assert (tmp_path / name).read_bytes() == before  # so the copy is the way back and stays


def test_a_failed_save_removes_its_temporary_file(tmp_path, monkeypatch):
    settings = Settings()
    path = tmp_path / "config.json"
    settings.save(path)

    def broken(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr("metarmap.settings.os.replace", broken)
    with pytest.raises(OSError):
        settings.save(path)
    assert not (tmp_path / "config.json.tmp").exists()


def test_a_clock_that_went_back_does_not_prune_or_hide_the_new_backup(config, tmp_path, monkeypatch):
    when = clock(monkeypatch, datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc))
    for i in range(PLAN_BACKUPS):  # five applies, a minute apart
        config.apply_plan(plan(i), 3, 1)
        when["now"] += timedelta(minutes=1)
    when["now"] = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)  # a Pi that booted before its clock was set
    name = config.apply_plan(plan(99), 3, 1)["backup"]
    assert (tmp_path / name).exists()  # not pruned in the same call
    assert config.plan_backups()[0]["file"] == name  # and the newest, for the Undo button
    assert len(backups_only(tmp_path)) == PLAN_BACKUPS  # the OLDEST went to make room
    assert config.next_plan_backup_name() > name  # the next one goes on from it
    config.restore_plan_backup()
    assert codes(config)[0] == "K004"  # undoes the apply just made, not the one before it


def test_pruning_removes_only_the_backups_own_files(config, tmp_path, monkeypatch):
    when = clock(monkeypatch, datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc))
    first = config.apply_plan(plan(0), 3, 1)["backup"]
    mine = tmp_path / (first + ".mine")
    keep = tmp_path / (first + "-keep")
    mine.write_text("a copy of my own")
    keep.write_text("another")
    for i in range(1, PLAN_BACKUPS + 1):
        when["now"] += timedelta(minutes=1)
        config.apply_plan(plan(i), 3, 1)
    assert not (tmp_path / first).exists() and not (tmp_path / (first + ".summary.json")).exists()
    assert mine.exists() and keep.exists()  # a file named like a backup, but not one, stays


def test_the_backup_is_private_from_the_first_byte(config, tmp_path, monkeypatch):
    os.chmod(tmp_path / "config.json", 0o644)
    opened = []
    real = os.open

    def spy(path, flags, mode=0o777, **kwargs):
        opened.append((str(path), flags, mode))
        return real(path, flags, mode, **kwargs)

    monkeypatch.setattr("metarmap.config.os.open", spy)
    name = config.apply_plan(plan(0), 3, 1)["backup"]
    made = [o for o in opened if o[0].endswith(name)]
    assert made and made[0][2] == 0o600 and made[0][1] & os.O_EXCL  # no moment when another user could read it
    assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o644  # then it takes the original's mode


def test_a_code_twice_is_refused_with_the_code_and_where(config):
    with pytest.raises(ValueError) as error:
        config.apply_plan([airport("KHOU"), airport("KIAH"), airport(""), airport("khou")], 3, 1)
    message = str(error.value)
    assert "KHOU" in message and "pixel 1" in message and "virtual airport 1" in message


def test_undo_renames_the_summary_with_the_backup(config, tmp_path):
    name = config.apply_plan(plan(0), 3, 1, summary={"n": 1})["backup"]
    config.restore_plan_backup()
    assert files(tmp_path) == sorted([name + "-undone", name + "-undone.summary.json"])  # no orphan summary
