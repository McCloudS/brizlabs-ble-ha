"""Per-entry model selection routes each platform to the right protocol."""

from types import SimpleNamespace

import pytest

from custom_components.brizlabs import light, number, select
from custom_components.brizlabs.const import CONF_MODEL, MODEL_CURTAIN, MODEL_RGB, entry_model
from tests.fakes import FakeDevice


def make(model=None, options=None):
    data = {"address": "00:11:22:33:44:55"}
    if model:
        data[CONF_MODEL] = model
    return SimpleNamespace(title="T", entry_id="e1", data=data, options=options or {})


def test_entry_model_defaults_to_curtain_for_old_entries():
    assert entry_model(make()) == MODEL_CURTAIN
    assert entry_model(make(MODEL_RGB)) == MODEL_RGB
    # options override what was chosen at setup
    assert entry_model(make(MODEL_CURTAIN, {CONF_MODEL: MODEL_RGB})) == MODEL_RGB


@pytest.mark.parametrize("model,light_cls,selects", [
    (MODEL_RGB, "custom_components.brizlabs.rgb.light",
     {"BrizlabsScenePaletteSelect", "BrizlabsMusicSelect", "BrizlabsSceneDirectionSelect"}),
    (MODEL_CURTAIN, "custom_components.brizlabs.light", {"BrizlabsMusicSelect"}),
])
async def test_platforms_dispatch_on_model(model, light_cls, selects):
    entry = make(model)
    hass = SimpleNamespace(data={"brizlabs": {"e1": FakeDevice()}})
    added = {}
    for platform in (light, number, select):
        out = []
        await platform.async_setup_entry(hass, entry, out.extend)
        added[platform.__name__.rsplit(".", 1)[1]] = out
    assert type(added["light"][0]).__module__ == light_cls
    assert {type(e).__name__ for e in added["select"]} == selects
    if model == MODEL_RGB:
        assert added["light"][0].supported_color_modes == {"hs"}


async def test_swatch_images_served_and_complete():
    from pathlib import Path
    import custom_components.brizlabs as integ
    from custom_components.brizlabs.rgb import scenes as S
    registered = []

    class Http:
        async def async_register_static_paths(self, configs):
            registered.extend(configs)

    await integ._register_static(SimpleNamespace(http=Http()))
    assert registered[0].url_path == "/brizlabs_static"
    www = Path(registered[0].path)
    names = {p.name for p in www.glob("*.svg")}
    assert len(names) == len(S.SCENE_NAMES) + len(S.PRESET_PALETTES)
    assert "scene_up_down.svg" in names and "palette_white_red_green.svg" in names
    await integ._register_static(SimpleNamespace())  # no http component: no crash
