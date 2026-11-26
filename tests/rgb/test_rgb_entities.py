import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError

from custom_components.brizlabs.rgb import scenes as S
from custom_components.brizlabs.rgb.light import BrizlabsLight
from custom_components.brizlabs.rgb.number import BrizlabsNumber, BrizlabsSceneSpeed
from custom_components.brizlabs.rgb.select import BrizlabsMusicSelect, BrizlabsScenePaletteSelect
from tests.rgb.fakes import FakeDevice, entry, scene_values

def P(x):
    """Original palette name(s) for dropdown label(s)."""
    if isinstance(x, str):
        return S.palette_name(x) or x
    return x if x is None else [S.palette_name(i) or i for i in x]



def wire(ent):
    ent.written = 0

    def w():
        ent.written += 1
    ent.async_write_ha_state = w
    ent.async_on_remove = lambda f: None
    return ent


# ---- light -------------------------------------------------------------
def test_light_reports_effect_from_state_not_constant():
    dev = FakeDevice(values=scene_values(8))
    light = BrizlabsLight(dev, entry())
    assert light.effect == "Fall"
    dev.values = scene_values(0)
    assert light.effect == "Rainbow"
    dev.values = {"work_mode": "music", "device_music": 4}
    assert light.effect == "Roll"
    dev.values = {"work_mode": "colour"}
    assert light.effect is None


def test_light_effect_list_has_all_scenes_and_music():
    light = BrizlabsLight(FakeDevice(), entry())
    for n in ("Rainbow", "Flow", "Fall", "Fade", "Flutter", "Filling", "Rock & Roll", "Kpop"):
        assert n in light.effect_list
    # legacy "Music N" aliases are accepted by turn_on but hidden from the UI list
    assert not [e for e in light.effect_list if e.startswith("Music")]
    assert len(light.effect_list) == len(set(light.effect_list))


def test_light_unique_id_unchanged():
    assert BrizlabsLight(FakeDevice("00:11:22:33:44:55"), entry()).unique_id == "001122334455"


@pytest.mark.asyncio
async def test_light_turn_on_scene_effect_sends_captured_default():
    dev = FakeDevice()
    await BrizlabsLight(dev, entry()).async_turn_on(effect="Fade")
    assert dev.sent == [{"switch_led": True, "work_mode": "scene",
                         "dreamlight_scene_mode": S.CAPTURED_PALETTES[7][0]}]


@pytest.mark.asyncio
async def test_light_turn_on_flow_unchanged_payload():
    from custom_components.brizlabs.const import FLOW_SCENE  # legacy constant kept
    dev = FakeDevice()
    await BrizlabsLight(dev, entry()).async_turn_on(effect="Flow")
    assert dev.sent[0]["work_mode"] == "scene"
    assert S.decode_scene(dev.sent[0]["dreamlight_scene_mode"]).scene_id == 1
    assert S.decode_scene(FLOW_SCENE).scene_id == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("effect,music", [("Music 3", 3), ("Music", 7)])
async def test_light_turn_on_music(effect, music):
    dev = FakeDevice()
    await BrizlabsLight(dev, entry()).async_turn_on(effect=effect)
    assert dev.sent == [{"switch_led": True, "work_mode": "music", "device_music": music}]


@pytest.mark.asyncio
async def test_light_unknown_effect_rejected():
    dev = FakeDevice()
    with pytest.raises(ValueError):
        await BrizlabsLight(dev, entry()).async_turn_on(effect="Nope")
    assert dev.sent == []


@pytest.mark.asyncio
async def test_light_no_optimistic_state():
    dev = FakeDevice(values={"work_mode": "colour"})
    light = BrizlabsLight(dev, entry())
    await light.async_turn_on(effect="Fall")
    assert light.effect is None  # only hardware report changes it


def test_light_keeps_segment_painting_helper():
    from custom_components.brizlabs.rgb.light import paint_colour
    assert paint_colour(120, 100, 100, [0, 2], 20).startswith("00010014" + "01")


# ---- palette select ----------------------------------------------------
def test_palette_select_options_follow_current_scene():
    dev = FakeDevice(values=scene_values(2))
    sel = BrizlabsScenePaletteSelect(dev, entry())
    assert P(sel.options) == P(S.palette_options(2))
    assert P(sel.current_option) == P("White, Green")  # legacy extra, not one of the 15 presets
    assert P(sel.current_option) in P(sel.options)
    dev.values = scene_values(1, 1)
    assert P(sel.options) == P(S.palette_options(1))
    assert P(sel.current_option) == P("Rainbow 3")


def test_palette_select_unavailable_or_empty_outside_scene():
    dev = FakeDevice(values={"work_mode": "music", "device_music": 1})
    sel = BrizlabsScenePaletteSelect(dev, entry())
    assert sel.current_option is None
    assert sel.available is False


def test_palette_select_shows_custom_palette_as_current():
    custom = S.encode_scene(S.build_scene(1, [(10, 100, 100), (20, 100, 100)]))
    dev = FakeDevice(values={"work_mode": "scene", "dreamlight_scene_mode": custom})
    sel = BrizlabsScenePaletteSelect(dev, entry())
    assert P(sel.current_option) == "Custom: Red · Orange"
    assert P(sel.current_option) in P(sel.options)


@pytest.mark.asyncio
async def test_palette_select_preserves_speed_scene_and_brightness():
    base = S.decode_scene(S.CAPTURED_PALETTES[1][0])
    cur = S.encode_scene(S.Scene(0, 1, 2, 33, base.colors))
    dev = FakeDevice(values={"work_mode": "scene", "bright_value": 40, "dreamlight_scene_mode": cur})
    sel = wire(BrizlabsScenePaletteSelect(dev, entry()))
    target = "Rainbow 1"
    await sel.async_select_option(target)
    assert len(dev.sent) == 1 and set(dev.sent[0]) == {"switch_led", "work_mode", "dreamlight_scene_mode"}
    assert dev.sent[0]["work_mode"] == "scene"
    new = S.decode_scene(dev.sent[0]["dreamlight_scene_mode"])
    assert (new.scene_id, new.speed) == (1, 33)
    assert P(S.palette_label(dev.sent[0]["dreamlight_scene_mode"])) == P(target)
    assert "bright_value" not in dev.sent[0]
    # not optimistic: selection unchanged until hardware reports
    assert P(sel.current_option) == P("Rainbow 2")
    dev.report(dreamlight_scene_mode=dev.sent[0]["dreamlight_scene_mode"])
    assert P(sel.current_option) == P(target)


@pytest.mark.asyncio
async def test_palette_select_follows_app_update():
    dev = FakeDevice(values=scene_values(3))
    sel = wire(BrizlabsScenePaletteSelect(dev, entry()))
    await sel.async_added_to_hass()
    dev.report(**scene_values(3, 1))
    assert sel.written == 1 and P(sel.current_option) == "Purple, Green"


@pytest.mark.asyncio
async def test_palette_select_rejects_invalid_and_not_in_scene():
    dev = FakeDevice(values=scene_values(2))
    sel = BrizlabsScenePaletteSelect(dev, entry())
    with pytest.raises(HomeAssistantError):
        await sel.async_select_option("Bogus")
    dev2 = FakeDevice(values={"work_mode": "music", "device_music": 0})
    with pytest.raises(HomeAssistantError):
        await BrizlabsScenePaletteSelect(dev2, entry()).async_select_option("White, Green")
    assert dev.sent == [] and dev2.sent == []


# ---- music select ------------------------------------------------------
def test_music_select():
    dev = FakeDevice(values={"work_mode": "music", "device_music": 5})
    sel = BrizlabsMusicSelect(dev, entry())
    assert sel.options == S.MUSIC_OPTIONS and sel.current_option == "Pop"
    dev.values = scene_values(1)
    assert sel.current_option is None


@pytest.mark.asyncio
async def test_music_select_sends_and_validates():
    dev = FakeDevice()
    sel = BrizlabsMusicSelect(dev, entry())
    await sel.async_select_option("Music 2")
    assert dev.sent == [{"switch_led": True, "work_mode": "music", "device_music": 2}]
    with pytest.raises(HomeAssistantError):
        await sel.async_select_option("Music 9")


def test_select_unique_ids_distinct_and_stable():
    d = FakeDevice("AA:BB:CC:DD:EE:FF")
    a, b = BrizlabsScenePaletteSelect(d, entry()), BrizlabsMusicSelect(d, entry())
    assert a.unique_id == "AA:BB:CC:DD:EE:FF_scene_palette"
    assert b.unique_id == "AA:BB:CC:DD:EE:FF_music_mode"


# ---- speed number ------------------------------------------------------
def test_existing_number_ids_unchanged():
    d = FakeDevice()
    assert BrizlabsNumber(d, entry(), "sensitivity", 0, 100).unique_id == f"{d.address}_sensitivity"
    assert BrizlabsNumber(d, entry(), "lightpixel_number_set", 1, 200).unique_id == f"{d.address}_lightpixel_number_set"


@pytest.mark.asyncio
async def test_scene_speed_number():
    dev = FakeDevice(values=scene_values(8))
    n = BrizlabsSceneSpeed(dev, entry())
    assert n.native_value == 50 and n.available
    await n.async_set_native_value(77)
    sent = dev.sent[0]
    assert sent["work_mode"] == "scene"
    new = S.decode_scene(sent["dreamlight_scene_mode"])
    assert new.speed == 77 and new.colors == S.decode_scene(dev.values["dreamlight_scene_mode"]).colors
    assert n.native_value == 50  # no optimism
    dev.values = {"work_mode": "music", "device_music": 1}
    assert not n.available and n.native_value is None
    with pytest.raises(HomeAssistantError):
        await n.async_set_native_value(10)


# ---- per-device isolation ---------------------------------------------
@pytest.mark.asyncio
async def test_devices_are_isolated():
    a = FakeDevice("00:11:22:33:44:55", scene_values(8))
    b = FakeDevice("00:11:22:33:44:66", {"work_mode": "music", "device_music": 2})
    la, lb = BrizlabsLight(a, entry("Test Light")), BrizlabsLight(b, entry("Other"))
    sa, sb = wire(BrizlabsScenePaletteSelect(a, entry())), wire(BrizlabsScenePaletteSelect(b, entry()))
    await sa.async_added_to_hass(); await sb.async_added_to_hass()
    a.report(**scene_values(4))
    assert (sa.written, sb.written) == (1, 0)
    assert (la.effect, lb.effect) == ("Shooting Star", "Classical")
    await BrizlabsMusicSelect(b, entry()).async_select_option("Music 6")
    assert a.sent == [] and b.sent[0]["device_music"] == 6


# ---- set_scene properties + schema -------------------------------------
def test_scene_properties_builder():
    props = S.set_scene_properties("Fade", [(0, 100, 100), (240, 100, 100)], speed=20)
    assert props["switch_led"] is True and props["work_mode"] == "scene"
    sc = S.decode_scene(props["dreamlight_scene_mode"])
    assert (sc.scene_id, sc.speed) == (7, 20) and len(sc.colors) == 2
    assert "bright_value" not in props
    assert S.set_scene_properties("Fade", [(0, 100, 100)], brightness=30)["bright_value"] == 30
    with pytest.raises(ValueError):
        S.set_scene_properties("Music 1", [(0, 100, 100)])
    with pytest.raises(ValueError):
        S.set_scene_properties("Fade", [(0, 100, 100)], brightness=0)


def test_set_scene_schema():
    from custom_components.brizlabs import SET_RGB_SCENE_SCHEMA
    ok = SET_RGB_SCENE_SCHEMA({"address": "aa", "effect": "Fall",
                           "colors": [{"hue": 10, "saturation": 100}, {"hue": 20, "saturation": 50, "value": 40}]})
    assert ok["speed"] == 50 and ok["colors"][0]["value"] == 100
    for bad in ({"address": "a", "effect": "Nope", "colors": [{"hue": 1, "saturation": 1}]},
                {"address": "a", "effect": "Fall", "colors": []},
                {"address": "a", "effect": "Fall", "colors": [{"hue": 400, "saturation": 1}]},
                {"address": "a", "effect": "Fall", "colors": [{"hue": 1, "saturation": 1}] * 8},
                {"address": "a", "effect": "Fall", "colors": [{"hue": 1, "saturation": 1}], "speed": 101},
                {"address": "a", "effect": "Fall"}):
        with pytest.raises(vol.Invalid):
            SET_RGB_SCENE_SCHEMA(bad)


@pytest.mark.asyncio
async def test_palette_select_current_custom_option_is_noop():
    custom = S.encode_scene(S.build_scene(1, [(10, 100, 100), (20, 100, 100)]))
    dev = FakeDevice(values={"work_mode": "scene", "dreamlight_scene_mode": custom})
    sel = wire(BrizlabsScenePaletteSelect(dev, entry()))
    await sel.async_select_option(sel.current_option)  # must not raise
    assert dev.sent == [] and dev.values["dreamlight_scene_mode"] == custom
    # a stale Custom label that is no longer current is still rejected
    with pytest.raises(HomeAssistantError):
        await sel.async_select_option("Custom: Hue 99")
    assert dev.sent == []


def test_palette_options_never_empty_without_scene():
    sel = BrizlabsScenePaletteSelect(FakeDevice(values={"work_mode": "colour"}), entry())
    assert not sel.available
    assert P(sel.options) == P([label for label, _ in S.PRESET_PALETTES])
