"""Estimated flight category breathing is optional without changing inferred colors."""

import pytest

from metarmap.models import Look
from metarmap.settings import Settings
from metarmap.visualizers import flightcategory, style
from metarmap.visualizers import visualizer


@pytest.mark.parametrize(
    "fields, category",
    [
        ({"visibilitySM": 10.0}, "VFR"),
        ({"visibilitySM": 5.0}, "MVFR"),
        ({"visibilitySM": 2.5}, "IFR"),
        ({"visibilitySM": 0.75}, "LIFR"),
    ],
)
@pytest.mark.parametrize("enabled", [True, False])
def test_estimated_category_effect_and_color(enabled, fields, category):
    settings = Settings()
    settings.visualizer.estimated_category_breathing = enabled
    report = {"flightCategory": None, **fields}
    color = flightcategory.COLORS[category]
    expected = (
        Look.pulse(color, period=flightcategory.ESTIMATE_PERIOD, low=style.LIGHT_LOW) if enabled else Look.solid(color)
    )
    assert flightcategory.look(report, settings) == expected


@pytest.mark.parametrize("enabled", [True, False])
def test_estimated_legend_matches_setting(enabled):
    settings = Settings()
    settings.visualizer.estimated_category_breathing = enabled
    item = next(i for i in flightcategory.legend(settings) if i["label"] == "Estimated")
    assert item["effect"] == ("pulse" if enabled else "solid")
    assert ("breathing" in item["detail"].lower()) == enabled
    assert item["colors"]  # inferred category is still colored


def test_reported_category_is_solid_regardless_of_toggle():
    settings = Settings()
    for enabled in (True, False):
        settings.visualizer.estimated_category_breathing = enabled
        assert flightcategory.look({"flightCategory": "IFR"}, settings) == Look.solid(flightcategory.COLORS["IFR"])


def test_toggle_default_and_save_roundtrip():
    settings = Settings()
    assert settings.visualizer.estimated_category_breathing is True
    assert settings.set("visualizer.estimated_category_breathing", "false") is False
    assert Settings.from_dict(settings.to_dict()).visualizer.estimated_category_breathing is False
    assert settings.set("visualizer.estimated_category_breathing", "true") is True
    with pytest.raises(ValueError):
        settings.set("visualizer.estimated_category_breathing", "not-a-boolean")


def test_missing_data_blink_setting_remains_independent():
    settings = Settings()
    settings.visualizer.estimated_category_breathing = False
    settings.visualizer.missing_data_blink = False
    assert (
        visualizer.look(
            flightcategory,
            {"flightCategory": None},
            settings,
        )
        == Look.off()
    )
    assert flightcategory.look({"flightCategory": None, "visibilitySM": 10.0}, settings) == Look.solid(
        flightcategory.COLORS["VFR"]
    )
