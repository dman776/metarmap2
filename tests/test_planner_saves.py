"""
Tests for the saved plans' files (metarmap.planner.saves): names, the cap, atomic files, and files that are damaged,
huge or edited by hand (ignored, never an error). No web, no Planner.
"""

import json
import os
import stat
import threading

import pytest

from metarmap.planner import saves
from metarmap.planner.saves import PlanSaves, SaveError, clean_name

PARAMS = {"chart": "Houston"}
RESULT = {"message": "Planned 3 airports"}
SUMMARY = {"chart": "Houston", "airports": 3}


@pytest.fixture
def store(tmp_path):
    return PlanSaves(str(tmp_path / "planner-saves"))


def keep(store, name="Houston 2026-11-25", **kw):
    return store.save(name, kw.get("params", PARAMS), kw.get("result", RESULT), kw.get("summary", SUMMARY))


def files(store):
    return sorted(os.listdir(store.folder)) if os.path.isdir(store.folder) else []


def refusal(call, *args, **kwargs):
    with pytest.raises(SaveError) as e:
        call(*args, **kwargs)
    return e.value


# ---- names ------------------------------------------------------------------------------------------------------


def test_a_name_is_trimmed_and_its_spaces_collapsed():
    assert clean_name("  Houston   2026-11-25 ") == "Houston 2026-11-25"
    assert clean_name("Café") == "Café"  # NFC
    assert clean_name("Wall plan") == "Wall plan"  # any space becomes one space
    assert clean_name("Zurich ✈ über") == "Zurich ✈ über"


@pytest.mark.parametrize(
    "bad",
    [
        None,
        42,
        ["a"],
        "",
        "   ",
        "../x",
        "..\\x",
        "a/b",
        "a\\b",
        "x" * 61,
        "tab\there",
        "line\nbreak",
        "nul\x00byte",
        "bell\x07",
        "bidi‮evil",  # a format character
        "sep arator",
        "\ud800",  # a lone surrogate
    ],
)
def test_bad_names_are_refused(bad):
    e = refusal(clean_name, bad)
    assert e.reason == "invalid" and e.status == 400 and str(e)


def test_the_longest_name_is_kept_and_windows_reserved_names_are_only_text(store):
    assert clean_name("x" * 60) == "x" * 60
    for name in ("CON", "nul", "COM1", "aux.txt", "..", "."):
        saved = keep(store, name)
        assert saves.valid_id(saved["id"])
    assert all(saves.ID.match(n[: -len(saves.SUFFIX)]) for n in files(store))  # the files never carry a name


# ---- save and list ----------------------------------------------------------------------------------------------


def test_save_writes_one_private_free_readable_file(store):
    saved = keep(store)
    assert saved["name"] == "Houston 2026-11-25" and saved["summary"] == SUMMARY and saved["format"] == 1
    assert files(store) == [saved["id"] + ".jsonl"]
    path = os.path.join(store.folder, saved["id"] + ".jsonl")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644
    with open(path) as f:
        lines = f.read().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["id"] == saved["id"]
    assert json.loads(lines[1]) == {"params": PARAMS, "result": RESULT}


def test_the_folder_is_made_when_it_is_missing(store):
    assert store.listing() == []  # no folder yet: an empty list, not an error
    keep(store)
    assert os.path.isdir(store.folder)


def test_a_listing_is_newest_first(store, monkeypatch):
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)

    class Clock:
        offset = 0

        @classmethod
        def now(cls, tz=None):
            return base + timedelta(seconds=cls.offset)

    monkeypatch.setattr(saves, "datetime", Clock)
    for i, name in enumerate(["first", "second", "third"]):
        Clock.offset = i * 10
        keep(store, name)
    assert [s["name"] for s in store.listing()] == ["third", "second", "first"]


def test_a_duplicate_name_is_refused_without_case(store):
    keep(store, "Houston")
    e = refusal(keep, store, "houston")
    assert e.reason == "exists" and e.status == 409
    assert refusal(keep, store, "  HOUSTON  ").reason == "exists"
    assert len(store.listing()) == 1 and len(files(store)) == 1


def test_the_count_is_capped(store):
    for i in range(saves.MAX_SAVES):
        keep(store, f"plan {i}")
    e = refusal(keep, store, "one more")
    assert e.reason == "full" and e.status == 409 and str(saves.MAX_SAVES) in str(e)
    store.delete(store.listing()[0]["id"])
    keep(store, "one more")  # a free place again
    assert len(store.listing()) == saves.MAX_SAVES


def test_a_plan_over_the_size_limit_is_refused(store, monkeypatch):
    monkeypatch.setattr(saves, "MAX_BYTES", 2000)
    e = refusal(keep, store, "big", result={"blob": "x" * 5000})
    assert e.reason == "too_big" and files(store) == []


def test_something_that_is_not_json_is_refused_as_failed(store):
    e = refusal(keep, store, "odd", result={"x": object()})
    assert e.reason == "failed" and files(store) == []


def test_a_write_that_fails_leaves_no_file_and_no_temporary(store, monkeypatch):
    keep(store, "kept")
    before = files(store)

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(saves.os, "replace", broken)
    e = refusal(keep, store, "doomed")
    assert e.reason == "failed" and e.status == 500
    assert files(store) == before  # no half file, no .tmp left behind


def test_a_save_is_synced_to_disk_the_file_then_its_folder(store, monkeypatch):
    synced = []
    real = os.fsync

    def spy(fd):
        synced.append("folder" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        real(fd)

    monkeypatch.setattr(saves.os, "fsync", spy)
    keep(store)
    assert synced[0] == "file"
    if hasattr(os, "O_DIRECTORY"):
        assert synced == ["file", "folder"]


def test_the_file_is_synced_before_it_is_moved_into_place(store, monkeypatch):
    order = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(saves.os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(saves.os, "replace", lambda a, b: (order.append("replace"), real_replace(a, b))[1])
    keep(store)
    assert order[:2] == ["fsync", "replace"]


def test_a_folder_that_cannot_be_synced_is_not_a_failed_save(store, monkeypatch):
    real = os.fsync

    def folder_fails(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("not supported")
        real(fd)

    monkeypatch.setattr(saves.os, "fsync", folder_fails)
    saved = keep(store)
    assert store.read(saved["id"])[1] == PARAMS


def test_a_file_that_cannot_be_synced_leaves_nothing(store, monkeypatch):
    def broken(fd):
        raise OSError("io error")

    monkeypatch.setattr(saves.os, "fsync", broken)
    e = refusal(keep, store, "doomed")
    assert e.reason == "failed" and files(store) == []


def test_a_folder_that_cannot_be_made_is_a_failure_not_a_crash(tmp_path):
    blocker = tmp_path / "planner-saves"
    blocker.write_text("a file where the folder should be")
    store = PlanSaves(str(blocker))
    assert store.listing() == []
    assert refusal(keep, store).reason == "failed"


# ---- read -------------------------------------------------------------------------------------------------------


def test_read_gives_back_what_was_saved(store):
    saved = keep(store)
    header, params, result = store.read(saved["id"])
    assert header["name"] == "Houston 2026-11-25" and params == PARAMS and result == RESULT


@pytest.mark.parametrize(
    "bad", ["", "x", "../x", "20261125-120000-zzzzzzzz", "20261125-120000-0123456", None, 5, "a/b"]
)
def test_an_id_that_is_not_one_of_ours_is_not_found(store, bad):
    keep(store)
    for call in (store.read, store.delete):
        e = refusal(call, bad)
        assert e.reason == "not_found" and e.status == 404
    assert refusal(store.rename, bad, "name").reason == "not_found"


def test_an_id_that_is_not_there_is_not_found(store):
    assert refusal(store.read, "20261125-120000-0123abcd").reason == "not_found"
    assert refusal(store.rename, "20261125-120000-0123abcd", "x").status == 404
    assert refusal(store.delete, "20261125-120000-0123abcd").status == 404


def damage(store, saved, write):
    path = os.path.join(store.folder, saved["id"] + ".jsonl")
    with open(path, "wb") as f:
        f.write(write if isinstance(write, bytes) else write.encode())
    return path


def test_files_with_a_bad_header_are_not_listed_and_not_read(store):
    saved = keep(store, "good")
    other = keep(store, "bad")
    header = json.dumps({"format": 1, "id": other["id"], "name": "bad", "saved_at": "x", "summary": {}})
    body = '\n{"params":{},"result":{}}\n'
    cases = {
        "empty": b"",
        "not json": b"not json at all\n{}\n",
        "bad utf8": b"\xff\xfe\n\xff\n",
        "deep": b"[" * 100000 + b"\n{}\n",
        "wrong id inside": (header.replace(other["id"], saved["id"]) + body).encode(),
        "header without name": b'{"format":1,"id":"%s","saved_at":"x","summary":{}}\n{}\n' % other["id"].encode(),
        "empty name": (header.replace('"bad"', '""') + body).encode(),
        "summary not a dict": (header.replace("{}}", "5}") + body).encode(),
        "no format": (header.replace('"format": 1, ', "") + body).encode(),
        "huge header": b'{"x":"' + b"a" * 20000 + b'"}\n{}\n',
    }
    for label, content in cases.items():
        damage(store, other, content)
        assert [s["name"] for s in store.listing()] == ["good"], label
        assert refusal(store.read, other["id"]).reason in ("unreadable", "format"), label


def test_a_good_header_over_a_damaged_body_is_listed_but_cannot_be_loaded(store):
    other = keep(store, "bad")
    header = json.dumps({"format": 1, "id": other["id"], "name": "bad", "saved_at": "x", "summary": {}})
    cases = {
        "header only": (header + "\n").encode(),
        "body is a list": (header + "\n[]\n").encode(),
        "body cut short": (header + '\n{"params": {"chart"').encode(),
        "body bad utf8": header.encode() + b"\n\xff\xfe\n",
    }
    for label, content in cases.items():
        damage(store, other, content)
        assert [s["name"] for s in store.listing()] == ["bad"], label  # so it can be renamed or deleted
        assert refusal(store.read, other["id"]).reason == "unreadable", label


def test_params_and_result_must_be_objects(store):
    saved = keep(store)
    header = json.dumps({"format": 1, "id": saved["id"], "name": "n", "saved_at": "x", "summary": {}})
    damage(store, saved, header + '\n{"params": 5, "result": {}}\n')
    assert refusal(store.read, saved["id"]).reason == "unreadable"
    damage(store, saved, header + '\n{"params": {}}\n')
    assert refusal(store.read, saved["id"]).reason == "unreadable"


def test_another_format_is_a_clear_refusal_and_still_listed(store):
    saved = keep(store)
    header = json.dumps({"format": 2, "id": saved["id"], "name": "n", "saved_at": "x", "summary": {}})
    damage(store, saved, header + '\n{"params": {}, "result": {}}\n')
    e = refusal(store.read, saved["id"])
    assert e.reason == "format" and "different version" in str(e)
    assert [s["format"] for s in store.listing()] == [2]  # listed, so it can be deleted or renamed


def test_a_file_over_the_size_limit_is_ignored(store, monkeypatch):
    saved = keep(store)
    monkeypatch.setattr(saves, "MAX_BYTES", 100)
    assert store.listing() == []
    assert refusal(store.read, saved["id"]).reason == "unreadable"
    assert refusal(store.rename, saved["id"], "x").reason == "unreadable"


def test_other_files_in_the_folder_are_ignored(store):
    keep(store, "mine")
    for name in ("notes.txt", ".save-abc.tmp", "20261125-120000-0123abcd.json", "20261125-120000-0123abcd.jsonl.bak"):
        with open(os.path.join(store.folder, name), "w") as f:
            f.write("{}")
    os.mkdir(os.path.join(store.folder, "20261125-120000-0123abcf.jsonl"))  # a folder with a good name
    assert [s["name"] for s in store.listing()] == ["mine"]
    assert refusal(store.read, "20261125-120000-0123abcf").reason == "unreadable"


# ---- rename and delete ------------------------------------------------------------------------------------------


def test_rename_changes_only_the_name(store):
    saved = keep(store, "old", params={"a": 1}, result={"b": [2]})
    renamed = store.rename(saved["id"], "  new   name ")
    assert renamed["name"] == "new name" and renamed["id"] == saved["id"] and renamed["saved_at"] == saved["saved_at"]
    header, params, result = store.read(saved["id"])
    assert header["name"] == "new name" and params == {"a": 1} and result == {"b": [2]}
    assert stat.S_IMODE(os.stat(os.path.join(store.folder, saved["id"] + ".jsonl")).st_mode) == 0o644
    assert len(files(store)) == 1  # no copy left behind


def test_rename_to_a_name_that_is_taken_clashes_but_a_case_change_of_itself_is_fine(store):
    one, two = keep(store, "one"), keep(store, "two")
    assert refusal(store.rename, one["id"], "TWO").reason == "exists"
    assert store.rename(one["id"], "ONE")["name"] == "ONE"
    assert store.rename(one["id"], "ONE")["name"] == "ONE"  # the same name again
    assert {s["name"] for s in store.listing()} == {"ONE", "two"}
    assert two["id"] in {s["id"] for s in store.listing()}


def test_rename_validates_the_name_and_keeps_the_file_on_failure(store):
    saved = keep(store, "keep me")
    for bad in ("", "../x", "a/b", "x" * 100, None):
        assert refusal(store.rename, saved["id"], bad).reason == "invalid"
    assert store.read(saved["id"])[0]["name"] == "keep me"


def test_a_failed_rename_leaves_the_old_file(store, monkeypatch):
    saved = keep(store, "keep me")
    monkeypatch.setattr(saves.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
    assert refusal(store.rename, saved["id"], "other").reason == "failed"
    monkeypatch.undo()
    assert store.read(saved["id"])[0]["name"] == "keep me" and len(files(store)) == 1


def test_delete_removes_the_file_and_frees_the_name(store):
    saved = keep(store, "gone")
    store.delete(saved["id"])
    assert files(store) == [] and store.listing() == []
    assert refusal(store.delete, saved["id"]).reason == "not_found"
    keep(store, "gone")  # the name is free again


def test_a_damaged_plan_can_still_be_deleted(store):
    saved = keep(store)
    damage(store, saved, b"junk")
    store.delete(saved["id"])
    assert files(store) == []


# ---- restart and threads ----------------------------------------------------------------------------------------


def test_a_new_store_on_the_same_folder_sees_the_plans(store):
    saved = keep(store, "survives")
    again = PlanSaves(store.folder)
    assert [s["name"] for s in again.listing()] == ["survives"]
    assert again.read(saved["id"])[2] == RESULT


def test_parallel_saves_never_pass_the_cap_or_repeat_a_name(store):
    failures = []

    def work(i):
        try:
            keep(store, f"plan {i % 40}")  # 40 names, tried 120 times
        except SaveError as e:
            failures.append(e.reason)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(120)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    names = [s["name"] for s in store.listing()]
    assert len(names) == len(set(names)) == 40 and set(failures) == {"exists"} and len(failures) == 80
    assert not [n for n in files(store) if n.endswith(".tmp")]


def test_parallel_saves_over_the_cap(store):
    results = []

    def work(i):
        try:
            keep(store, f"plan {i}")
            results.append("ok")
        except SaveError as e:
            results.append(e.reason)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(saves.MAX_SAVES + 20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == saves.MAX_SAVES and results.count("full") == 20
    assert len(store.listing()) == saves.MAX_SAVES


# ---- ids, links, and numbers ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "20261125-120000-0123abcd\n",  # a trailing newline
        "20261125-120000-0123abcd ",
        "\uff12\uff10261125-120000-0123abcd",  # fullwidth digits
        "20261125-120000-0123ABCD",
        "20261125-120000-0123abc",
    ],
)
def test_an_id_must_be_exactly_ascii_digits_and_lower_case_hex(store, bad):
    assert not saves.valid_id(bad)
    assert refusal(store.read, bad).reason == "not_found"
    assert refusal(store.delete, bad).reason == "not_found"
    assert refusal(store.rename, bad, "x").reason == "not_found"
    assert saves.valid_id("20261125-120000-0123abcd")


def test_a_link_to_a_file_is_not_a_saved_plan(store, tmp_path):
    saved = keep(store, "real")
    outside = tmp_path / "elsewhere.jsonl"
    path = os.path.join(store.folder, saved["id"] + ".jsonl")
    os.replace(path, outside)
    os.symlink(outside, path)
    assert store.listing() == []
    assert refusal(store.read, saved["id"]).reason == "unreadable"
    assert refusal(store.rename, saved["id"], "other").reason == "unreadable"
    assert outside.exists()
    store.delete(saved["id"])  # removes the link, never what it points at
    assert outside.exists() and not os.path.lexists(path)


def test_deep_nesting_in_the_body_is_unreadable_not_a_crash(store):
    saved = keep(store)
    header = json.dumps({"format": 1, "id": saved["id"], "name": "n", "saved_at": "x", "summary": {}})
    damage(store, saved, header + '\n{"params": ' + "[" * 200000 + "\n")
    assert [s["name"] for s in store.listing()] == ["n"]
    assert refusal(store.read, saved["id"]).reason == "unreadable"


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_numbers_that_are_not_finite_make_a_file_unreadable(store, bad):
    good = keep(store, "good")
    other = keep(store, "other")

    def header(summary):
        return json.dumps({"format": 1, "id": other["id"], "name": "n", "saved_at": "x", "summary": summary})

    body = '\n{"params": {}, "result": {}}\n'
    # in the header: not listed, and the good plan still is
    damage(store, other, header({"airports": 0}).replace("0}", bad + "}") + body)
    assert [s["name"] for s in store.listing()] == ["good"]
    assert refusal(store.read, other["id"]).reason == "unreadable"
    store.delete(other["id"])  # a damaged file can still be removed by its id
    # in the body: listed, cannot be loaded
    damage(store, other, header({}) + '\n{"params": {}, "result": {"lat": ' + bad + "}}\n")
    assert [s["name"] for s in store.listing()] == ["good", "n"] or [s["name"] for s in store.listing()] == [
        "n",
        "good",
    ]
    assert refusal(store.read, other["id"]).reason == "unreadable"
    assert good["id"] in {s["id"] for s in store.listing()}


def test_a_huge_integer_is_refused_quickly(store):
    import time

    saved = keep(store)
    header = json.dumps({"format": 1, "id": saved["id"], "name": "n", "saved_at": "x", "summary": {}})
    damage(store, saved, header + '\n{"params": {}, "result": {"n": ' + "9" * (5 * 1024 * 1024) + "}}\n")
    started = time.monotonic()
    assert refusal(store.read, saved["id"]).reason == "unreadable"
    assert time.monotonic() - started < 2


def test_the_size_limit_is_checked_before_the_file_is_read(store, monkeypatch):
    saved = keep(store)
    monkeypatch.setattr(saves, "MAX_BYTES", 100)

    def never(*args, **kwargs):
        raise AssertionError("a file over the limit was parsed")

    monkeypatch.setattr(saves.json, "loads", never)
    assert store.listing() == []
    assert refusal(store.read, saved["id"]).reason == "unreadable"
