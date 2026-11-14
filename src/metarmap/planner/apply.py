"""
Applying a plan to the Chart (B90 part 4): what `airports` looks like after the plan, and what changes. Pure: no files,
no web, no Config; web/planner.py asks it for the preview and Config.apply_plan writes what it answers.

The airports become exactly the plan, in the plan's LED order. An airport the Chart already had keeps its name, its OLED
flag and its other keys (a mock METAR) by its code. A pixel the plan hides (a skipped pixel between two airports,
which bridges a gap so the string needs no cut) becomes a Hidden Pixel row (`skip`, no code). Then come the blank LEDs
of the last string (the strip is strings x string_len pixels; plain blanks, not Hidden Pixels: airports can be added
there later), then the virtual airports (the web map only): the airports the plan dropped, so planning never deletes
one, then the virtual ones the Chart already had. A virtual airport the plan now includes becomes a real one. The strip
is rebuilt from the plan: a Hidden Pixel the Chart has now but the plan does not hide is a plain blank (or gone) like
any other LED without an airport.
"""

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from metarmap.config import MAX_LEDS
from metarmap.settings import Airport

MAX_MOVES = 1000  # the list of moves in a summary: never longer than the Chart's pixels


@dataclass
class Change:
    """The airports after the plan (one per LED, then the virtual ones), the two counts and the summary."""

    airports: List[Airport]
    led_count: int
    virtual_count: int
    summary: Dict = field(default_factory=dict)


def norm(code):
    """A code as the Chart compares them: no spaces, upper case (a hand-edited config.json can have "kaus")."""
    return str(code or "").strip().upper()


def hidden_numbers(pixels):
    """
    The LED numbers (from 0) of the plan's hidden pixels: pixels the plan skips (`skipped`) that come before its last
    airport. A skipped pixel after the last airport has nothing to bridge: a plain blank LED.
    """
    last = max((n for n, p in enumerate(pixels) if norm(p.get("code"))), default=-1)
    return [n for n, p in enumerate(pixels) if p.get("skipped") and not norm(p.get("code")) and n < last]


def _copy(airport):
    other = Airport(code=norm(airport.code), name=airport.name, display=airport.display)
    other._extra = copy.deepcopy(airport._extra)
    return other


def plan_changes(
    current: Sequence[Airport],
    led_count: int,
    virtual_count: int,
    result_pixels: Sequence[Dict],
    string_len: int,
    strings: int,
    names: Dict[str, str],
) -> Change:
    """
    The Chart after the plan. current: the airports now (one per LED, then the virtual ones), led_count and
    virtual_count as they are now; result_pixels: the plan's `sheet.pixels` in LED order (a pixel with no `code` is a
    blank LED); strings x string_len: the strip the plan is for; names: {code: name} for the airports the plan has.
    Raises ValueError for a plan that does not fit its strip or has a code twice.
    """
    strip = int(strings) * int(string_len)
    if strip < len(result_pixels):
        raise ValueError(f"the plan has {len(result_pixels)} pixels but {strings} strings of {string_len} are {strip}")
    plan_codes = [norm(p.get("code")) for p in result_pixels if norm(p.get("code"))]
    if len(set(plan_codes)) != len(plan_codes):
        raise ValueError("the plan has an airport twice")
    in_plan = set(plan_codes)
    hidden = set(hidden_numbers(result_pixels))
    names = {norm(k): v for k, v in names.items()}

    # the first LED that has each code now (a code twice in the config keeps its first); codes are compared
    # without case and spaces, so "kaus" in a hand-edited config is the plan's KAUS
    old_at = {}
    for index, airport in enumerate(current):
        code = norm(airport.code)
        if code and code not in old_at:
            old_at[code] = index

    new_strip: List[Airport] = []
    kept = moved = 0
    moves, added, promoted = [], [], []
    for number, pixel in enumerate(result_pixels):
        code = norm(pixel.get("code"))
        if not code:
            new_strip.append(Airport(skip=number in hidden))
            continue
        old = old_at.get(code)
        if old is None:
            new = Airport(code=code, name=names.get(code, ""), display=False)
            added.append(code)
        else:
            new = _copy(current[old])
            new.code = code
            new.name = new.name or names.get(code, "")
            if old >= led_count:
                promoted.append(code)
            elif old == number:
                kept += 1
            else:
                moved += 1
                moves.append({"code": code, "from": old, "to": number})
        new_strip.append(new)
    blank = strip - len(plan_codes) - len(hidden)  # the LEDs with no airport that are not Hidden Pixels
    new_strip.extend(Airport() for _ in range(strip - len(new_strip)))

    # the virtual airports: the dropped real ones first (so a plan never deletes an airport), then the ones that were
    # already virtual, each in its old order. A code is there once: one the plan has is in the strip already
    virtual: List[Airport] = []
    in_virtual = set()
    became_virtual: List[str] = []
    merged = blank_virtual = 0
    for want_virtual in (False, True):
        for index, airport in enumerate(current):
            if (index >= led_count) != want_virtual:
                continue
            code = norm(airport.code)
            if not code:
                blank_virtual += want_virtual  # a virtual placeholder with no airport: nothing is lost without it
                continue
            if code in in_plan:
                merged += old_at[code] != index  # the same code twice in the config: the plan has it once
                continue
            if code in in_virtual:
                merged += 1
                continue
            in_virtual.add(code)
            virtual.append(_copy(airport))
            if not want_virtual:
                became_virtual.append(code)

    airports = new_strip + virtual
    new_led, new_virtual = len(new_strip), len(virtual)
    summary = {
        "kept": kept,
        "moved": moved,
        "moves": moves[:MAX_MOVES],
        "added": added,
        "became_virtual": became_virtual,
        "promoted": promoted,
        "blank_leds": blank,
        "hidden": len(hidden),
        "blank_virtual_dropped": blank_virtual,
        "merged_duplicates": merged,
        "led_count": {"from": led_count, "to": new_led},
        "virtual_count": {"from": virtual_count, "to": new_virtual},
        "airports_total": len(airports),
        "over_limit": len(airports) > MAX_LEDS,
        "limit": MAX_LEDS,
        "wiring_note": wiring_note(result_pixels, new_led),
    }
    summary["unchanged"] = (
        not summary["added"]
        and not summary["moved"]
        and not summary["became_virtual"]
        and not summary["promoted"]
        and led_count == new_led
        and virtual_count == new_virtual
        and key(airports) == key(list(current)[: led_count + virtual_count])
    )
    return Change(airports, new_led, new_virtual, summary)


def wiring_note(pixels, led_count):
    """
    The sentence the confirmation shows: the strip has to be wired as planned. `pixels` is the plan's `sheet.pixels`
    in LED order: the LED numbers it names are positions in the chain, so a pixel with no airport (a hidden or spare
    one) still counts.
    """
    coded = [(number, norm(p.get("code"))) for number, p in enumerate(pixels) if norm(p.get("code"))]
    if not coded:
        return "The plan has no airports: every LED would be left blank."
    (first, first_code), (last, last_code) = coded[0], coded[-1]
    hidden = [n + 1 for n in hidden_numbers(pixels)]
    hidden_note = ""
    if hidden:
        which = ", ".join(f"LED {n}" for n in hidden[:-1]) + (" and " if len(hidden) > 1 else "") + f"LED {hidden[-1]}"
        hidden_note = (
            f" {which} {'is a hidden pixel' if len(hidden) == 1 else 'are hidden pixels'}: wire "
            f"{'it' if len(hidden) == 1 else 'them'} into the string, but "
            f"{'it shows' if len(hidden) == 1 else 'they show'} no airport."
        )
    return (
        f"The strip must be wired in this order: LED {first + 1} is {first_code}, LED {last + 1} is {last_code}, "
        f"{led_count} pixels in all.{hidden_note} Apply only when your pixels are connected like this, or the LEDs "
        "will light for the wrong airports."
    )


def key(airports):
    """What identifies a list of airports for a comparison: code, name, OLED flag, Hidden Pixel and other keys, in
    order."""
    return [
        [a.code, a.name, bool(a.display), bool(a.skip), json.dumps(a._extra, sort_keys=True, default=str)]
        for a in airports
    ]


def fingerprint(job_id, current, led_count, virtual_count, change):
    """
    A token for this exact preview: the plan (job id), the Chart's airports now and the airports it would have. Apply
    only goes ahead with a token that still matches, so a change made after the preview (by anyone) is not
    overwritten by a summary the user did not see.
    """
    text = json.dumps(
        {
            "job": job_id,
            "now": [key(list(current)[: led_count + virtual_count]), led_count, virtual_count],
            "then": [key(change.airports), change.led_count, change.virtual_count],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode()).hexdigest()
