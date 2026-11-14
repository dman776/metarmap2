"""
Tests for the visualizer icons as masks (metarmap.web.icon_masks, made by tools/make_icon_masks.py): one for every
icon, each a sensible 20x20 drawing, and, where rsvg-convert is installed, still what the tool would make from SHAPES.
"""

import hashlib
import importlib.util
import pathlib
import shutil

import pytest

from metarmap.visualizers.visualizer import ICONS
from metarmap.web import icons
from metarmap.web.icon_masks import MASKS, REV, SIZE

TOOL = pathlib.Path(__file__).resolve().parent.parent / "tools" / "make_icon_masks.py"
RSVG = "/usr/local/bin/rsvg-convert" if pathlib.Path("/usr/local/bin/rsvg-convert").exists() else None
RSVG = RSVG or shutil.which("rsvg-convert")
needs_rsvg = pytest.mark.skipif(not RSVG, reason="rsvg-convert isn't installed (a dev machine's tool)")


def tool():
    spec = importlib.util.spec_from_file_location("make_icon_masks", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_mask_for_every_icon():
    assert SIZE == 20
    assert set(MASKS) == set(ICONS) == set(REV)
    assert list(MASKS) == sorted(MASKS) and list(REV) == sorted(REV)  # the tool writes them sorted


@pytest.mark.parametrize("name", ICONS)
def test_mask(name):
    data = icons.mask(name)
    assert isinstance(data, bytes) and len(data) == 400
    drawn = sum(1 for a in data if a)
    solid = sum(1 for a in data if a >= 192)
    assert 40 <= drawn <= 240, drawn  # a drawing: not empty, not a filled square
    assert solid >= 10 or name == "chase", solid  # chase's dots fade, but are still there
    assert icons.mask_rev(name) == REV[name] == hashlib.sha1(data).hexdigest()[:8]


def test_masks_differ():
    assert len(set(MASKS.values())) == len(MASKS)
    assert len(set(REV.values())) == len(REV)


def test_unknown_icon():
    assert icons.mask("sun") is None and icons.mask_rev("sun") is None


def test_rainbow_is_one_color():
    """A mask has no colors: rainbow's is SOLID's three plain arcs."""
    t = tool()
    assert t.shape("rainbow") == icons.SOLID["rainbow"]
    assert t.shape("chase") == icons.SHAPES["chase"]  # its fade is the mask's alpha


def test_generated_module_round_trips():
    """The module the tool writes from these masks is the one checked in (sorted, deterministic)."""
    t = tool()
    assert t.module(MASKS) == (TOOL.parent.parent / "src" / "metarmap" / "web" / "icon_masks.py").read_text()


@needs_rsvg
@pytest.mark.parametrize("name", ICONS)
def test_masks_match_the_shapes(name):
    """icon_masks.py is up to date with SHAPES: if this fails, run tools/make_icon_masks.py. A small tolerance
    allows for another rsvg-convert version's antialiasing."""
    fresh = tool().mask(name, RSVG)
    assert len(fresh) == 400
    diffs = [abs(a - b) for a, b in zip(fresh, MASKS[name])]
    assert max(diffs) <= 48 and sum(diffs) <= 400 * 4, f"{name}: run tools/make_icon_masks.py"


@needs_rsvg
def test_rendering_is_deterministic():
    t = tool()
    assert t.mask("hourglass", RSVG) == t.mask("hourglass", RSVG)
