"""
The build sheet: everything a builder needs from a plan, as plain JSON-serializable data (the Web UI draws it). The
route, where to cut and how much wire to splice in, the cables for the joins, a shopping list, and the string voltage
and power feeds. Pure: no web or network code.
"""

import math
from dataclasses import dataclass

MM_PER_INCH = 25.4

# the voltage by pixel count (rules of thumb): a 5 V string has to be fed more often than a 12 V one carries the same
# power at under half the current
MAX_5V_PIXELS = 100
MAX_12V_PIXELS = 300
FEED_EVERY = {5: 100, 12: 200}  # pixels between power feeds when the voltage is the recommended one

# the supply sizes (amps) that are easy to buy
SUPPLY_AMPS = {5: (2, 3, 5, 10, 20, 30, 40), 12: (1, 2, 3, 5, 8, 10, 15, 20, 30)}


@dataclass
class PowerSettings:
    brightness: float = 0.5  # the Chart's led.brightness.normal
    ma_white_5v: float = (
        60.0  # full-white current of one pixel on a 5 V string (editable; verify against the strings bought)
    )
    ma_white_12v: float = 25.0  # the same on a 12 V string (editable)
    margin: float = 1.25  # supply headroom

    def __post_init__(self):
        if not (math.isfinite(self.brightness) and 0 <= self.brightness <= 1):
            raise ValueError(f"brightness must be a number from 0 to 1, not {self.brightness!r}")
        for name in ("ma_white_5v", "ma_white_12v"):
            value = getattr(self, name)
            if not (math.isfinite(value) and value > 0):
                raise ValueError(f"{name} must be a number above 0, not {value!r}")
        if not (math.isfinite(self.margin) and self.margin >= 1):
            raise ValueError(f"margin must be a number of 1 or more, not {self.margin!r}")


def build_sheet(plan, settings, power=None, board_in=None) -> dict:
    """
    The build sheet of a layout.Plan made with layout.Settings. power: a PowerSettings (the defaults if None).
    board_in: the board's (width, height) in inches as the user gave them, shown as they are; else they are worked out
    from the millimetres.
    """
    power = power or PowerSettings()
    items = plan.items
    every = settings.string_len
    gaps = {gap.index: gap for gap in plan.gaps}
    width_in, height_in = board_in if board_in else (settings.board_w / MM_PER_INCH, settings.board_h / MM_PER_INCH)

    pixels = [
        {
            "index": k,
            "number": k + 1,
            "code": item.code,
            "skipped": item.skipped,
            "x": _r(item.x, 2),
            "y": _r(item.y, 2),
            "orig_x": None if item.orig_x is None else _r(item.orig_x, 2),
            "orig_y": None if item.orig_y is None else _r(item.orig_y, 2),
            "moved_mm": _r(item.moved_mm),
            "string": k // every + 1,
            "position": k % every + 1,
        }
        for k, item in enumerate(items)
    ]

    route = []
    for k in range(len(items) - 1):
        a, b = items[k], items[k + 1]
        length = math.hypot(b.x - a.x, b.y - a.y)
        if (k + 1) % every == 0:
            entry = {"kind": "join", "status": "join", "extension_mm": 0.0, "cut": False}
        else:
            gap = gaps.get(k)
            status = gap.status if gap else "ok"
            entry = {
                "kind": "wire",
                "status": status,
                "extension_mm": _r(gap.extension_mm) if gap and status == "extension" else 0.0,
                "cut": status == "extension",
            }
        entry.update(
            {
                "from_index": k,
                "to_index": k + 1,
                "length_mm": _r(length),
                "slack_mm": _r(settings.pitch - length) if length < settings.pitch and entry["kind"] == "wire" else 0.0,
            }
        )
        route.append(entry)

    cuts = []
    for entry in route:
        if not entry["cut"]:
            continue
        i, j = entry["from_index"], entry["to_index"]
        cuts.append(
            {
                "between": [i, j],
                "string": i // every + 1,
                "codes": [items[i].code, items[j].code],
                "length_mm": entry["length_mm"],
                "extension_mm": entry["extension_mm"],
                "how": f"cut between pixel {i + 1} ({_label(items[i])}) and {j + 1} ({_label(items[j])}), "
                f"splice in {entry['extension_mm']:.0f} mm",
            }
        )

    joins = [
        {
            "between": list(join["between"]),
            "string_a": join["between"][0] // every + 1,
            "string_b": join["between"][1] // every + 1,
            "length_mm": _r(join["length_mm"]),
            "note": "a standard extension cable of this length covers the join; it needs no cut",
        }
        for join in plan.joins
    ]

    strings = []
    for n, indexes in enumerate(plan.strings):
        last = n == len(plan.strings) - 1
        strings.append(
            {
                "number": n + 1,
                "first": indexes[0],
                "last": indexes[-1],
                "pixels": len(indexes),
                "full": len(indexes) == every,
                "spare_pixels": plan.spare_pixels if last else 0,
            }
        )

    skipped = sum(1 for item in items if item.skipped)
    shopping = {
        "airports": len(items) - skipped,
        "skipped": skipped,
        "pixels": len(items),
        "strings": len(plan.strings),
        "spare_pixels": plan.spare_pixels,
        "extensions": plan.extensions,
        "extension_wire_mm": _r(sum(cut["extension_mm"] for cut in cuts)),
        "splices": 2 * plan.extensions,
        "joins": len(joins),
        "join_cable_mm": _r(sum(join["length_mm"] for join in joins)),
        "slack_gaps": plan.slack_gaps,
        "moved": plan.moved,
        "dropped": len(plan.drops),
        "clipped": len(plan.clipped),
    }

    problems = {
        "crowded": [list(cluster) for cluster in plan.crowded],
        "drops": [{"code": drop.code, "crowding": drop.crowding} for drop in plan.drops],
        "clipped": list(plan.clipped),
        "skips_wanted": plan.skips_wanted,
        "skips_note": _skips_note(plan, every),
        "ok": plan.extensions == 0 and not plan.crowded,
    }

    first = items[0] if items else None
    return {
        "board": {
            "width_mm": _r(settings.board_w),
            "height_mm": _r(settings.board_h),
            "width_in": _r(width_in, 2),
            "height_in": _r(height_in, 2),
        },
        "settings": {
            "pitch_mm": settings.pitch,
            "tolerance": settings.tolerance,
            "min_gap_mm": settings.min_gap,
            "max_move_mm": settings.max_move,
            "string_len": every,
            "allow_skips": settings.allow_skips,
        },
        "pixels": pixels,
        "start": None
        if first is None
        else {
            "x": _r(first.x, 2),
            "y": _r(first.y, 2),
            "index": 0,
            "code": first.code,
            "corner": settings.start_corner,
        },
        "route": route,
        "cuts": cuts,
        "joins": joins,
        "strings": strings,
        "shopping": shopping,
        "problems": problems,
        "power": power_advice(len(items), power, every),
    }


def power_advice(pixels, power=None, string_len=50) -> dict:
    """
    The string voltage, supply and power feeds for a chain of `pixels` pixels. The numbers are rules of thumb that
    PowerSettings lets the user change. string_len is where the strings join, which the feeds snap to.
    """
    power = power or PowerSettings()
    if pixels < 0:
        raise ValueError(f"pixels must be 0 or more, not {pixels!r}")
    ma = {5: power.ma_white_5v, 12: power.ma_white_12v}

    if pixels <= MAX_5V_PIXELS:
        voltage = 5
        reason = (
            f"{pixels} pixels is small enough for 5 V: one supply, and the wire in the strings carries the current "
            "without a noticeable drop."
        )
    elif pixels <= MAX_12V_PIXELS:
        voltage = 12
        reason = (
            f"{pixels} pixels: 12 V carries the same power at under half the current of 5 V, so the strings dim less "
            "toward their ends and need fewer power feeds."
        )
    else:
        voltage = 12
        reason = (
            f"{pixels} pixels is a long chain: use 12 V and feed power at every string join, so no string carries the "
            "current of the ones before it."
        )

    options = []
    for volts in (5, 12):
        amps = pixels * ma[volts] * power.brightness / 1000
        supply = _supply(volts, amps * power.margin)
        options.append(
            {
                "voltage": volts,
                "ma_white": ma[volts],
                "amps": _r(amps, 2),
                "watts": _r(amps * volts, 1),
                "supply_amps": supply,
                "supply_watts": _r(supply * volts, 1),
                "recommended": volts == voltage,
            }
        )
    chosen = next(option for option in options if option["recommended"])

    return {
        "voltage": voltage,
        "reason": reason,
        "pixels": pixels,
        "ma_per_pixel": ma[voltage],
        "brightness": power.brightness,
        "margin": power.margin,
        "estimated_amps": chosen["amps"],
        "options": options,
        "supply_amps": chosen["supply_amps"],
        "supply_watts": chosen["supply_watts"],
        "feed_points": _feed_points(pixels, voltage, string_len, every_string=pixels > MAX_12V_PIXELS),
        "notes": [
            "These numbers are rules of thumb; the current per pixel and the brightness are editable. Check the "
            "current of the strings you buy.",
            "The Pi's 3.3 V data pin usually needs a level shifter for both 5 V and 12 V strings: check the string's "
            "datasheet.",
            "Never mix voltages in one chain.",
            f"The Chart shows mostly single colors at brightness {power.brightness:g}, so the real average current is "
            "well below full white.",
            "24 V is not recommended: few 50-count pixel strings are sold at 24 V, and the gain over 12 V is small.",
        ],
    }


def _feed_points(pixels, voltage, string_len, every_string):
    """The pixel indexes to feed power at: the first, then every so often, each at the start of a string."""
    if pixels <= 0:
        return []
    if every_string:
        return list(range(0, pixels, string_len))
    step = FEED_EVERY[voltage]
    points = [0]
    for target in range(step, pixels, step):
        snapped = int(target / string_len + 0.5) * string_len  # the nearest join
        if 0 < snapped < pixels and snapped not in points:
            points.append(snapped)
    return points


def _supply(voltage, amps):
    """The smallest common supply size (amps) that carries `amps`; a multiple of the largest beyond the list."""
    if amps <= 0:
        return 0
    sizes = SUPPLY_AMPS[voltage]
    for size in sizes:
        if amps <= size:
            return size
    return math.ceil(amps / sizes[-1]) * sizes[-1]


def _skips_note(plan, string_len):
    wanted = plan.skips_wanted
    if not wanted:
        return ""
    pixel = "hidden pixel" if wanted == 1 else "hidden pixels"
    if plan.spare_pixels >= wanted:
        return f"{wanted} {pixel} would remove the extensions left; the last string has {plan.spare_pixels} spare."
    return (
        f"{wanted} {pixel} would remove the extensions left, but the last string has only {plan.spare_pixels} spare: "
        f"one more string of {string_len} would allow them."
    )


def _label(item):
    return item.code if item.code else "hidden pixel"


def _r(value, digits=1):
    """A float rounded for the page (and never a -0.0)."""
    return round(value, digits) + 0.0
