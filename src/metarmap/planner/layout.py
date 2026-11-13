"""
The Chart Planner's layout: where each airport's pixel goes on the board, in what order the strings visit them, and
which airports to drop when too many crowd one spot. A string is a fixed run of string_len pixels (50), so every string
but the last is full and the joins between strings sit at fixed places in the order. Everything is in millimetres on
the board (origin top left, x right, y down). It has no web or network code, so it runs the same on a Pi and in the
tests.
"""

import heapq
import math
import random
from dataclasses import dataclass, field, replace
from typing import Callable, List, NamedTuple, Optional, Sequence


class Cancelled(Exception):
    """Raised when the cancel callable given to plan(), recommend() or sweep_sizes() says to stop."""


def _stop(cancel):
    """Raises Cancelled if the caller asked to stop; called at the loop boundaries (a sweep, a pass, a pin added)."""
    if cancel is not None and cancel():
        raise Cancelled()


# inside a long loop (a pass over every pin, the pairs of a sweep) cancel is asked once per this many steps, so a stop
# is seen within a fraction of a second even for a thousand pins, not only at the end of a whole pass
CHECK_EVERY = 16


def _stop_every(cancel, step, every=CHECK_EVERY):
    """_stop for loops with many short steps: asks cancel on every `every`-th step."""
    if cancel is not None and step % every == 0:
        _stop(cancel)


# a gap over the limit costs this much (more than any excess can add up to), so extensions are counted first
EXTENSION_COST = 10000.0
# a little cost per mm, so among orders with the same extensions the shorter wire wins (the search needs a slope)
LENGTH_WEIGHT = 0.001
# a gap shorter than this fraction of the pitch leaves a lot of wire to hide
SLACK_FRACTION = 0.5
# a pin moved less than this many mm isn't counted as moved
MOVED_MM = 0.05

RELAX_SWEEPS = 300  # the most sweeps declutter makes before it gives up
STALL_SWEEPS = 20  # ... or the sweeps in a row that no longer bring the pins closer to a solution
NEIGHBOURS = 8  # how many nearest pins 2-opt and Or-opt try to connect a pin to
RESTARTS = 3  # starting orders tried (the first is deterministic, the others use the seed)
PASSES = 40  # the most improvement passes over an order
EPS = 1e-9
# a pair this close to min_gap (mm) is not called crowded: the push-apart sweeps can stall a hair short of it, and the
# placement that picks the pins to keep (try_add) is not stalled the same way, so both must call the same pairs crowded
GAP_TOLERANCE = 0.1
NUDGE_MM = 0.5  # how far declutter first moves a pin that sits exactly where an earlier one does
CORNERS = {"tl": (0, 0), "tr": (1, 0), "bl": (0, 1), "br": (1, 1)}
GOLDEN_ANGLE = 2.399963  # radians; spreads the directions in which pins at the very same spot are pushed apart


@dataclass
class Pin:
    """An airport to place: where it truly is on the board, and how much it matters."""

    code: str
    x: float
    y: float
    rank: float = 0.0  # higher = more important
    must_keep: bool = False


@dataclass
class Settings:
    board_w: float
    board_h: float
    pitch: float = 80.0  # wire between two pixels on a string
    tolerance: float = 0.05  # a gap up to pitch * (1 + tolerance) still fits
    min_gap: float = 18.0  # the closest two pixels fit on the board
    max_move: float = 18.0  # the furthest a pixel may sit from its airport's true spot
    string_len: int = 50
    allow_skips: bool = False  # may a hidden pixel bridge a gap instead of an extension?
    start_corner: Optional[str] = None  # "tl", "tr", "bl", "br": the first pixel is the one nearest it
    seed: int = 0

    def __post_init__(self):
        for name in ("board_w", "board_h", "pitch"):
            value = getattr(self, name)
            if not (math.isfinite(value) and value > 0):
                raise ValueError(f"{name} must be a number above 0, not {value!r}")
        if not (math.isfinite(self.tolerance) and self.tolerance > -1):
            raise ValueError(f"tolerance must be a number above -1, not {self.tolerance!r}")
        for name in ("min_gap", "max_move"):
            value = getattr(self, name)
            if not (math.isfinite(value) and value >= 0):
                raise ValueError(f"{name} must be a number of 0 or more, not {value!r}")
        if not (isinstance(self.string_len, int) and not isinstance(self.string_len, bool) and self.string_len >= 1):
            raise ValueError(f"string_len must be a whole number of 1 or more, not {self.string_len!r}")
        if self.start_corner is not None and self.start_corner not in CORNERS:
            raise ValueError(f"start_corner must be one of {', '.join(CORNERS)} or None, not {self.start_corner!r}")

    @property
    def limit(self):
        """The longest gap a string reaches."""
        return self.pitch * (1 + self.tolerance)


@dataclass
class Item:
    """One pixel of the plan: an airport (code), or a hidden skipped pixel (code None)."""

    code: Optional[str]
    x: float
    y: float
    moved_mm: float = 0.0
    orig_x: Optional[float] = None
    orig_y: Optional[float] = None

    @property
    def skipped(self):
        return self.code is None


@dataclass
class Gap:
    """The wire between items[index] and items[index + 1] inside one string."""

    index: int
    length_mm: float
    status: str  # "ok", "slack" (a lot of wire to hide) or "extension" (the wire is too short)
    extension_mm: float = 0.0  # how much wire to add (the length over the pitch), for an extension


@dataclass
class Drop:
    """An airport the plan suggests dropping, and the airport it crowds that stays."""

    code: str
    crowding: str


@dataclass
class Plan:
    items: List[Item] = field(default_factory=list)
    # item indexes. Every string but the last is full (string_len pixels), so the joins are at fixed places; the join
    # of two strings is free (an extension cable goes there)
    strings: List[List[int]] = field(default_factory=list)
    gaps: List[Gap] = field(default_factory=list)
    crowded: List[List[str]] = field(default_factory=list)  # codes of the clusters too tight to space out
    drops: List[Drop] = field(default_factory=list)
    clipped: List[str] = field(default_factory=list)  # codes of the pins that began off the board (put on its edge)
    # the joins between strings: {"index": the join's number from 0, "length_mm": the cable it needs, "between": the
    # two item indexes it connects}
    joins: List[dict] = field(default_factory=list)
    extensions: int = 0
    slack_gaps: int = 0
    skips: int = 0
    # the hidden pixels that would bridge the extensions left, each gap taken alone: only a gap that has room for its
    # pixels (min_gap from everything) and none of them at the first or last slot of a string counts, so a gap that no
    # pixel can help (a fixed join or crowding in the way) is not wanted. Filled in with allow_skips off too
    skips_wanted: int = 0
    spare_pixels: int = 0  # dark pixels at the end of the last string, past the last item
    moved: int = 0


class SizeResult(NamedTuple):
    width_mm: float
    extensions: int
    crowded: int  # clusters too tight to space out at this size
    drops: int  # airports to drop to fix them


def plan(pins: Sequence[Pin], settings: Settings, cancel: Optional[Callable[[], bool]] = None) -> Plan:
    """
    Spaces the pins out, orders them into strings and measures every gap. Every string but the last is full, so the
    free joins are at fixed places in the order; the last one may end in spare pixels. Same input and seed, same plan.
    A pin that begins off the board is put on its edge first (listed in clipped), so max_move counts from there. A
    position that isn't a finite number, or two pins with the same code, is a ValueError. cancel is an optional callable
    that says True when the caller wants it to stop: it is asked between sweeps, passes and pins, and then Cancelled is
    raised.
    """
    pins = list(pins)
    _check_pins(pins)
    result = Plan()
    if not pins:
        return result
    for k, pin in enumerate(pins):
        x, y = min(max(pin.x, 0.0), settings.board_w), min(max(pin.y, 0.0), settings.board_h)
        if (x, y) != (pin.x, pin.y):
            pins[k] = replace(pin, x=x, y=y)
            result.clipped.append(pin.code)
    xs, ys, close = _declutter([p.x for p in pins], [p.y for p in pins], settings, cancel)
    result.crowded = _clusters(pins, close)
    if close:
        result.drops = _suggest_drops(pins, settings, cancel)
    items = []
    for k in _order(xs, ys, settings, cancel):
        pin = pins[k]
        moved = math.hypot(xs[k] - pin.x, ys[k] - pin.y)
        items.append(Item(pin.code, xs[k], ys[k], moved, pin.x, pin.y))
    if settings.allow_skips:
        items = _place_skips(items, settings, cancel)
    result.items = items
    result.strings = _strings(len(items), settings.string_len)
    _measure(result, settings)
    return result


def sweep_sizes(
    make_pins: Callable[[float], Sequence[Pin]],
    widths_mm: Sequence[float],
    settings_for: Callable[[float], Settings],
    cancel: Optional[Callable[[], bool]] = None,
) -> List[SizeResult]:
    """
    Plans each trial board width and lists them best first: fewest crowded, then drops, then extensions. cancel works as
    in plan().
    """
    results = []
    for width in widths_mm:
        _stop(cancel)
        planned = plan(make_pins(width), settings_for(width), cancel)
        results.append(SizeResult(width, planned.extensions, len(planned.crowded), len(planned.drops)))
    return sorted(results, key=lambda r: (r.crowded, r.drops, r.extensions, r.width_mm))


def fill_strings(n: int, string_len: int = 50) -> int:
    """n rounded up to whole strings (at least one), so no string is left part empty."""
    return max(1, -(-n // string_len)) * string_len


def recommend(
    candidates: Sequence[Pin],
    settings: Settings,
    target: Optional[int] = None,
    coverage: float = 0.0,
    cancel: Optional[Callable[[], bool]] = None,
):
    """
    A set of the candidates that fits the board without crowding. The must_keep pins come first; then the most
    important ones, each only if it can sit min_gap from the chosen ones within max_move. coverage (0..1) trades
    importance for a pin far from the chosen ones (0: importance first, ties go to the farther one). target None takes
    as many as fit. cancel works as in plan(), and is asked before each pin is added.
    """
    _check_pins(candidates)
    kept = [p for p in candidates if p.must_keep]
    pool = [p for p in candidates if not p.must_keep]
    placed = _seeded(kept, settings)
    top = max((p.rank for p in candidates), default=0.0)
    ranks = [p.rank / top if top > 0 else 0.0 for p in pool]
    coverage = min(max(coverage, 0.0), 1.0)
    nearest = [min((_dist(p, q) for q in kept), default=math.inf) for p in pool]
    left = [True] * len(pool)  # candidates not yet tried; one that doesn't fit never will, as chosen only grows
    while target is None or len(placed.pins) < target:
        _stop(cancel)
        far = max((d for d, o in zip(nearest, left) if o and d != math.inf), default=0.0)
        keys = []  # the best score first; the tiny extra term breaks a tie in favour of the farther one, then the order
        for rank, d, o in zip(ranks, nearest, left):
            cover = 1.0 if d == math.inf or far <= 0 else d / far
            keys.append((1 - coverage) * rank + coverage * cover + 1e-9 * cover if o else -math.inf)
        pin = None
        while pin is None:
            _stop(cancel)
            best = keys.index(max(keys))
            if keys[best] == -math.inf:
                return list(placed.pins)
            keys[best] = -math.inf
            left[best] = False
            if placed.try_add(pool[best], settings):
                pin = pool[best]
        nearest = [min(d, _dist(p, pin)) for d, p in zip(nearest, pool)]
    return list(placed.pins)


def _check_pins(pins):
    """Refuses a position that isn't a finite number and two pins with the same code."""
    seen = set()
    for pin in pins:
        if not (math.isfinite(pin.x) and math.isfinite(pin.y)):
            raise ValueError(f"pin {pin.code!r} has no usable position: ({pin.x!r}, {pin.y!r})")
        if pin.code in seen:
            raise ValueError(f"two pins have the code {pin.code!r}")
        seen.add(pin.code)


def _seeded(kept, settings):
    """A _Placed holding the must_keep pins: they stay even if they crowd each other; the others keep clear of them."""
    placed = _Placed(settings)
    if kept:
        xs, ys, _close = _declutter([p.x for p in kept], [p.y for p in kept], settings)
        for pin, x, y in zip(kept, xs, ys):
            placed.add(pin, x, y)
    return placed


class _Placed:
    """The chosen pins and where each is placed, in a grid, so the ones near a spot are found quickly."""

    def __init__(self, settings):
        self.gap = settings.min_gap
        self.floor = settings.min_gap - GAP_TOLERANCE  # closer than this is a clash (see GAP_TOLERANCE)
        self.reach = max(settings.min_gap + 2 * settings.max_move, 1.0)  # no pin placed further than this clashes
        self.board = (settings.board_w, settings.board_h)
        self.cells = {}
        self.pins = []
        self.x = []
        self.y = []

    def add(self, pin, x, y):
        self.cells.setdefault(self._cell(pin), []).append(len(self.pins))
        self.pins.append(pin)
        self.x.append(x)
        self.y.append(y)

    def _cell(self, pin):
        return (int(pin.x // self.reach), int(pin.y // self.reach))

    def near(self, pin):
        """Indexes of the chosen pins whose true spot is within reach of pin's."""
        cx, cy = self._cell(pin)
        return [
            i
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for i in self.cells.get((cx + dx, cy + dy), ())
            if _dist(pin, self.pins[i]) < self.reach
        ]

    def try_add(self, pin, settings):
        """Chooses pin if it can be spaced from the chosen ones near it, moving them within max_move if need be."""
        x = min(max(pin.x, 0.0), self.board[0])
        y = min(max(pin.y, 0.0), self.board[1])
        near = self.near(pin)
        if all(math.hypot(x - self.x[i], y - self.y[i]) >= self.floor - EPS for i in near):
            self.add(pin, x, y)  # nobody has to move
            return True
        group = [self.pins[i] for i in near] + [pin]
        xs, ys, close = _declutter([p.x for p in group], [p.y for p in group], settings)
        if close:
            return False
        inside = set(near)
        for k, i in enumerate(near):  # a pin that moved must clear the chosen ones outside the group too
            for j in self.near(self.pins[i]):
                if j not in inside and math.hypot(xs[k] - self.x[j], ys[k] - self.y[j]) < self.floor - EPS:
                    return False
        for k, i in enumerate(near):
            self.x[i], self.y[i] = xs[k], ys[k]
        self.add(pin, xs[-1], ys[-1])
        return True


def _dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def _gap_cost(length, limit):
    return (EXTENSION_COST + length - limit if length > limit else 0.0) + LENGTH_WEIGHT * length


def _worth(pin):
    """What decides which of two crowding pins stays: the greater one."""
    return (pin.must_keep, pin.rank, pin.code)


def _close_pairs(xs, ys, min_gap):
    """(distance, i, j) of every pair closer than min_gap, closest first. A grid keeps it from comparing every pair."""
    if min_gap <= 0:
        return []
    cells = {}
    for k in range(len(xs)):
        cells.setdefault((int(xs[k] // min_gap), int(ys[k] // min_gap)), []).append(k)
    pairs = []
    limit = min_gap - EPS
    for (cx, cy), members in cells.items():
        for n, i in enumerate(members):
            for j in members[n + 1 :]:
                d = math.hypot(xs[i] - xs[j], ys[i] - ys[j])
                if d < limit:
                    pairs.append((d, i, j) if i < j else (d, j, i))
        for dx, dy in ((1, -1), (1, 0), (1, 1), (0, 1)):  # the other neighbouring cells, each pair of cells once
            others = cells.get((cx + dx, cy + dy))
            if others:
                for i in members:
                    for j in others:
                        d = math.hypot(xs[i] - xs[j], ys[i] - ys[j])
                        if d < limit:
                            pairs.append((d, i, j) if i < j else (d, j, i))
    return sorted(pairs)


def _declutter(xs, ys, settings, cancel=None):
    """
    Pushes pins apart until all are min_gap apart, none further than max_move from where it began and none off the
    board. Returns the new xs, ys and the pairs still too close (a spot with more pins than fit around it), which it
    reports after the sweeps stop making progress rather than looping on.
    """
    gap, cap = settings.min_gap, settings.max_move
    ox = [min(max(x, 0.0), settings.board_w) for x in xs]
    oy = [min(max(y, 0.0), settings.board_h) for y in ys]
    px, py = ox[:], oy[:]
    seen = set()
    for k in range(len(px)):  # pins at the very same spot would be pushed in cancelling directions: part them a little
        if (px[k], py[k]) in seen:
            px[k] += math.cos(k * GOLDEN_ANGLE) * NUDGE_MM
            py[k] += math.sin(k * GOLDEN_ANGLE) * NUDGE_MM
        seen.add((px[k], py[k]))
    best, stalled = math.inf, 0
    for _ in range(RELAX_SWEEPS):
        _stop(cancel)
        pairs = _close_pairs(px, py, gap)
        if not pairs:
            break
        total = sum(gap - d for d, _i, _j in pairs)
        if total < best - 1e-3:
            best, stalled = total, 0
        else:
            stalled += 1
            if stalled >= STALL_SWEEPS:
                break
        for step, (_d, i, j) in enumerate(pairs, 1):
            _stop_every(cancel, step, 512)  # a sweep over a crowded thousand can have hundreds of thousands of pairs
            dx, dy = px[j] - px[i], py[j] - py[i]
            d = math.hypot(dx, dy)
            if d >= gap:  # an earlier push in this sweep already spaced them
                continue
            if d < EPS:  # at the very same spot: push apart in a direction that differs per pin
                ux, uy = math.cos(i * GOLDEN_ANGLE), math.sin(i * GOLDEN_ANGLE)
            else:
                ux, uy = dx / d, dy / d
            push = (gap * 1.0005 - d) / 2
            px[i] -= ux * push
            py[i] -= uy * push
            px[j] += ux * push
            py[j] += uy * push
        for k in range(len(px)):  # keep each pin within max_move of its spot, then on the board
            mx, my = px[k] - ox[k], py[k] - oy[k]
            d = math.hypot(mx, my)
            if d > cap:
                px[k], py[k] = ox[k] + mx * cap / d, oy[k] + my * cap / d
            px[k] = min(max(px[k], 0.0), settings.board_w)
            py[k] = min(max(py[k], 0.0), settings.board_h)
    return px, py, _close_pairs(px, py, max(gap - GAP_TOLERANCE, 0.0))


def _clusters(pins, close):
    """The pins' codes grouped by the too-close pairs that join them, each group sorted, the groups by first code."""
    parent = list(range(len(pins)))

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for _d, i, j in close:
        parent[find(i)] = find(j)
    groups = {}
    for _d, i, j in close:
        for k in (i, j):
            groups.setdefault(find(k), set()).add(pins[k].code)
    return sorted(sorted(codes) for codes in groups.values())


def _suggest_drops(pins, settings, cancel=None):
    """
    Airports to drop so the rest can be spaced out: the pins are taken most important first (a must_keep one always
    stays), each kept only if it can sit min_gap from the ones kept within max_move of its spot. The ones that can't
    are the drops, the least important first, each naming the nearest airport that stays. It is a greedy choice, so it
    can drop a pin that would have fitted back in once the others were placed (the pins kept always fit, though).
    """
    placed = _seeded([p for p in pins if p.must_keep], settings)
    rest = sorted((p for p in pins if not p.must_keep), key=_worth, reverse=True)
    dropped = []
    for p in rest:
        _stop(cancel)
        if not placed.try_add(p, settings):
            dropped.append(p)
    return [Drop(p.code, min(placed.pins, key=lambda q: (_dist(p, q), q.code)).code) for p in reversed(dropped)]


def _order(xs, ys, settings, cancel=None):
    """
    The order that visits every pin with the fewest gaps over the limit (then the least wire). The joins between strings
    are at fixed places in the order (after every string_len-th pin) and cost nothing, so a long gap suits a join.
    """
    n = len(xs)
    if n <= 1:
        return list(range(n))
    limit = settings.limit

    def edge(a, b):
        if a is None or b is None:
            return 0.0  # the ends of a path have no wire beyond them
        return _gap_cost(math.hypot(xs[a] - xs[b], ys[a] - ys[b]), limit)

    def cost_of(order):
        """The cost of a whole order: every gap but the free joins, which are at fixed places."""
        return sum(edge(a, b) for k, (a, b) in enumerate(zip(order, order[1:])) if (k + 1) % settings.string_len)

    nbrs = _neighbours(xs, ys, min(NEIGHBOURS, n - 1), cancel)
    rng = random.Random(settings.seed)
    corner = settings.start_corner
    if corner:
        cx, cy = CORNERS[corner][0] * settings.board_w, CORNERS[corner][1] * settings.board_h
        fixed = min(range(n), key=lambda k: (math.hypot(xs[k] - cx, ys[k] - cy), k))
    else:
        mx, my = sum(xs) / n, sum(ys) / n
        fixed = None
        first = max(range(n), key=lambda k: (math.hypot(xs[k] - mx, ys[k] - my), -k))
    best, best_cost = None, math.inf
    for attempt in range(RESTARTS):
        _stop(cancel)
        if fixed is not None:
            start = fixed
        elif attempt == 0:
            start = first
        else:
            start = rng.randrange(n)
        order = _nearest_path(xs, ys, start, rng, 0.0 if attempt == 0 else 0.2, cancel)
        order = _improve(order, edge, nbrs, fixed is not None, settings.string_len, cancel)
        cost = cost_of(order)
        if cost < best_cost - EPS:
            best, best_cost = order, cost
    return best


def _neighbours(xs, ys, k, cancel=None):
    result = []
    for a in range(len(xs)):
        _stop_every(cancel, a, 32)
        result.append(
            heapq.nsmallest(
                k,
                (b for b in range(len(xs)) if b != a),
                key=lambda b, a=a: (xs[a] - xs[b]) ** 2 + (ys[a] - ys[b]) ** 2,
            )
        )
    return result


def _nearest_path(xs, ys, start, rng, noise, cancel=None):
    """A path that always goes to the nearest pin not yet visited (now and then the second nearest, if noise)."""
    order = [start]
    left = [k for k in range(len(xs)) if k != start]
    while left:
        _stop_every(cancel, len(left), 32)
        last = order[-1]
        near = heapq.nsmallest(
            2, range(len(left)), key=lambda k: (xs[left[k]] - xs[last]) ** 2 + (ys[left[k]] - ys[last]) ** 2
        )
        pick = near[1] if len(near) > 1 and noise and rng.random() < noise else near[0]
        order.append(left.pop(pick))
    return order


def _improve(order, edge, nbrs, fixed_first, every, cancel=None):
    """
    2-opt and Or-opt on an open path, trying only each pin's nearest neighbours, until a pass finds nothing better.
    The path is padded with None at both ends (an end has no wire beyond it), so the moves treat the ends like any
    other place. fixed_first keeps the first pin where it is. The join between two strings (the edge after every
    `every`-th pin) is free, so a move is judged on the cost of the whole path with those edges left out: the gain_*
    helpers say how the free edges' cost changes, as a move shifts or turns the edges that sit at the joins.
    """
    n = len(order)
    t = [None] + list(order) + [None]
    pos = {}

    def reindex():
        for k, item in enumerate(t):
            if item is not None:
                pos[item] = k

    def free_edges(lo, hi):
        """The free join edges between edge lo and edge hi; edge m joins t[m] and t[m + 1]."""
        return range(max(every, -(-lo // every) * every), min(hi, n - 1) + 1, every)

    def gain_2opt(i, j):
        """How much more the free edges cost once t[i + 1..j] is reversed (their cost then, less their cost now)."""
        total = 0.0
        for m in free_edges(i, j):
            if m == i:
                new = edge(t[i], t[j])
            elif m == j:
                new = edge(t[i + 1], t[j + 1])
            else:  # an edge inside the stretch lands at the mirrored place
                u = i + j - m
                new = edge(t[u], t[u + 1])
            total += new - edge(t[m], t[m + 1])
        return total

    def gain_or(s, e, k, reverse):
        """The same for moving t[s..e] between t[k] and t[k + 1] (turned round if reverse)."""
        length = e - s + 1
        seg = t[s : e + 1][::-1] if reverse else t[s : e + 1]
        total = 0.0
        for m in free_edges(s - 1, k) if k > e else free_edges(k, e):
            if k > e:  # the stretch moves later: the pins between it and k shift back by its length
                if m == s - 1:
                    new = edge(t[s - 1], t[e + 1])
                elif m <= k - length - 1:
                    new = edge(t[m + length], t[m + length + 1])
                elif m == k - length:
                    new = edge(t[k], seg[0])
                elif m < k:
                    r = m - (k - length + 1)
                    new = edge(seg[r], seg[r + 1])
                else:
                    new = edge(seg[-1], t[k + 1])
            else:  # the stretch moves earlier: the pins between k and it shift on by its length
                if m == k:
                    new = edge(t[k], seg[0])
                elif m < k + length:
                    r = m - k - 1
                    new = edge(seg[r], seg[r + 1])
                elif m == k + length:
                    new = edge(seg[-1], t[k + 1])
                elif m < e:
                    new = edge(t[m - length], t[m - length + 1])
                else:
                    new = edge(t[s - 1], t[e + 1])
            total += new - edge(t[m], t[m + 1])
        return total

    reindex()
    first = 2 if fixed_first else 1  # the first place an Or-opt segment may start
    low = 1 if fixed_first else 0  # the first edge an Or-opt segment may be put in
    for _ in range(PASSES):
        _stop(cancel)
        improved = False
        for step, a in enumerate(list(t[1 : n + 1]), 1):  # 2-opt: reverse the stretch between two neighbours
            _stop_every(cancel, step)
            for c in nbrs[a]:
                p, q = pos[a], pos[c]
                i, j = (p, q) if p < q else (q, p)
                delta = edge(t[i], t[j]) + edge(t[i + 1], t[j + 1]) - edge(t[i], t[i + 1]) - edge(t[j], t[j + 1])
                if delta - gain_2opt(i, j) < -EPS:
                    t[i + 1 : j + 1] = t[i + 1 : j + 1][::-1]
                    reindex()
                    improved = True
        for j in range(1, n + 1):  # reverse a start (only if the first pin may change)
            _stop_every(cancel, j, 64)
            if not fixed_first and edge(t[1], t[j + 1]) - edge(t[j], t[j + 1]) - gain_2opt(0, j) < -EPS:
                t[1 : j + 1] = t[1 : j + 1][::-1]
                reindex()
                improved = True
        for i in range(1, n):  # reverse an end
            _stop_every(cancel, i, 64)
            if edge(t[i], t[n]) - edge(t[i], t[i + 1]) - gain_2opt(i, n) < -EPS:
                t[i + 1 : n + 1] = t[i + 1 : n + 1][::-1]
                reindex()
                improved = True
        for length in (1, 2, 3):  # Or-opt: move a stretch of up to three pins somewhere better
            s = first
            while s + length - 1 <= n:
                _stop_every(cancel, s)
                e = s + length - 1
                seg = t[s : e + 1]
                prev, nxt = t[s - 1], t[e + 1]
                saved = edge(prev, seg[0]) + edge(seg[-1], nxt) - edge(prev, nxt)
                if saved > EPS:
                    best = None
                    for end in (seg[0], seg[-1]):
                        for c in nbrs[end]:
                            pc = pos[c]
                            if s <= pc <= e:
                                continue
                            for k in (pc - 1, pc):
                                if k < low or s - 1 <= k <= e:
                                    continue
                                u, v = t[k], t[k + 1]
                                base = edge(u, v)
                                for reverse in (False, True):
                                    a0, a1 = (seg[-1], seg[0]) if reverse else (seg[0], seg[-1])
                                    cost = edge(u, a0) + edge(a1, v) - base - gain_or(s, e, k, reverse)
                                    if cost - saved < -EPS and (best is None or cost < best[0]):
                                        best = (cost, k, reverse)
                    if best:
                        _, k, reverse = best
                        rest = t[:s] + t[e + 1 :]
                        at = k if k < s else k - length
                        rest[at + 1 : at + 1] = seg[::-1] if reverse else seg
                        t[:] = rest
                        reindex()
                        improved = True
                s += 1
        if not improved:
            break
    return t[1 : n + 1]


def _strings(count, string_len):
    """The item indexes cut into strings of string_len pixels: every string but the last is full."""
    return [list(range(start, min(start + string_len, count))) for start in range(0, count, string_len)]


def _extensions(items, settings):
    """How many wires inside a string (not at a join, which is free) are too short for their gap."""
    every = settings.string_len
    return sum(
        1
        for k, (a, b) in enumerate(zip(items, items[1:]))
        if (k + 1) % every and math.hypot(b.x - a.x, b.y - a.y) > settings.limit + EPS
    )


def _skips_ok(items, string_len):
    """False if a hidden pixel is the first or last of its string: at a join it bridges nothing."""
    return not any(item.skipped and (k % string_len in (0, string_len - 1)) for k, item in enumerate(items))


def _place_skips(items, settings, cancel=None):
    """
    items with hidden pixels in the gaps that would need an extension, using only the spare slots of the last string
    (so no string is added). A hidden pixel shifts the pins after it, which moves the joins relative to them: a long gap
    that sat on a join (free) stops being free once a pixel goes in before it. So each step adds the pixel that leaves
    the fewest extensions even when that is no fewer than now, and the chain with the fewest extensions seen on the way
    is kept. A gap too long for the spare slots, or whose pixels would land at a join, stays an extension.
    """
    every = settings.string_len
    spare = -(-len(items) // every) * every - len(items)
    best_items, best_count = items, _extensions(items, settings)
    while spare > 0 and best_count:
        _stop(cancel)
        step = None
        for k, (a, b) in enumerate(zip(items, items[1:])):
            if (k + 1) % every == 0 or math.hypot(b.x - a.x, b.y - a.y) <= settings.limit + EPS:
                continue
            hidden = _bridge(a, b, items, settings)
            if not hidden or len(hidden) > spare:
                continue
            trial = items[: k + 1] + hidden + items[k + 1 :]
            if not _skips_ok(trial, every):
                continue
            key = (_extensions(trial, settings), len(hidden), k)
            if step is None or key < step[0]:
                step = (key, trial)
        if step is None:
            break
        spare -= len(step[1]) - len(items)
        items = step[1]
        if step[0][0] < best_count:
            best_items, best_count = items, step[0][0]
    return best_items


def _bridge(a, b, items, settings):
    """
    Hidden pixels between a and b, so every wire between them reaches; None if none can be put at least min_gap from
    everything. They go along the straight line, or a little off it where something is in the way.
    """
    limit = settings.limit
    d = math.hypot(b.x - a.x, b.y - a.y)
    count = math.ceil(d / limit) - 1
    ux, uy = (b.x - a.x) / d, (b.y - a.y) / d
    placed = []
    for j in range(1, count + 1):
        spot = None
        for side in (0, 10, -10, 20, -20, 30, -30):
            for along in (0.0, 0.05, -0.05, 0.1, -0.1):
                t = (j / (count + 1) + along) * d
                x, y = a.x + ux * t - uy * side, a.y + uy * t + ux * side
                before = placed[-1] if placed else a
                if (
                    0 <= x <= settings.board_w
                    and 0 <= y <= settings.board_h
                    and math.hypot(x - before.x, y - before.y) <= limit
                    and all(math.hypot(x - o.x, y - o.y) >= settings.min_gap - 1e-6 for o in items + placed)
                ):
                    spot = Item(None, x, y)
                    break
            if spot:
                break
        if spot is None:
            return None
        placed.append(spot)
    if math.hypot(b.x - placed[-1].x, b.y - placed[-1].y) > limit:
        return None
    return placed


def _skips_wanted(result, settings):
    """
    The hidden pixels that would bridge the extensions left, each gap taken alone: a gap counts only if its pixels
    fit (min_gap from everything) and none would be the first or last of a string. More pixels in one gap shift the
    joins for the others, so with several gaps this is an estimate.
    """
    items = result.items
    wanted = 0
    for gap in result.gaps:
        if gap.status != "extension":
            continue
        k = gap.index
        hidden = _bridge(items[k], items[k + 1], items, settings)
        if hidden and _skips_ok(items[: k + 1] + hidden + items[k + 1 :], settings.string_len):
            wanted += len(hidden)
    return wanted


def _measure(result, settings):
    """Fills in the gaps inside each string and the counts."""
    items = result.items
    slack = settings.pitch * SLACK_FRACTION
    for string in result.strings:
        for a, b in zip(string, string[1:]):
            d = math.hypot(items[b].x - items[a].x, items[b].y - items[a].y)
            if d > settings.limit + EPS:
                result.gaps.append(Gap(a, d, "extension", d - settings.pitch))
                result.extensions += 1
            elif d < slack:
                result.gaps.append(Gap(a, d, "slack"))
                result.slack_gaps += 1
            else:
                result.gaps.append(Gap(a, d, "ok"))
    result.skips = sum(1 for item in items if item.skipped)
    result.moved = sum(1 for item in items if item.moved_mm > MOVED_MM)
    result.skips_wanted = _skips_wanted(result, settings)
    if items:
        result.spare_pixels = len(result.strings) * settings.string_len - len(items)
    for k in range(len(result.strings) - 1):
        last = result.strings[k][-1]
        d = math.hypot(items[last + 1].x - items[last].x, items[last + 1].y - items[last].y)
        result.joins.append({"index": k, "length_mm": d, "between": (last, last + 1)})
