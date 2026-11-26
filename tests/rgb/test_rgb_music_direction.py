import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError

import custom_components.brizlabs as integ
from custom_components.brizlabs.rgb import scenes as S
from custom_components.brizlabs.rgb.light import BrizlabsLight
from custom_components.brizlabs.rgb.select import BrizlabsMusicSelect, BrizlabsSceneDirectionSelect
from tests.rgb.fakes import FakeDevice, entry, scene_values

MUSIC = ["Rock & Roll", "Jazz", "Classical", "Energy", "Roll", "Pop", "Rock", "Kpop"]


# ---- music names ------------------------------------------------------
def test_music_names_and_ids_match_ordered_capture(ordered):
    assert S.MUSIC_OPTIONS == MUSIC
    assert [e["id"] for e in ordered["music_events"]] == list(range(8))
    for ev, name in zip(ordered["music_events"], MUSIC):
        assert S.effect_for_values({"work_mode": "music", "device_music": ev["id"]}) == name


@pytest.mark.parametrize("name,i", [(n, i) for i, n in enumerate(MUSIC)] +
                         [(f"Music {i}", i) for i in range(8)] + [("Music", 7)])
def test_music_id_accepts_names_and_legacy(name, i):
    assert S.music_id_for_name(name) == i


def test_music_id_rejects_unknown():
    for bad in ("Music 8", "Nope", "rock"):
        with pytest.raises(ValueError):
            S.music_id_for_name(bad)


def test_effect_list_has_names_and_legacy_unique_and_no_scene_clash():
    assert len(S.EFFECT_LIST) == len(set(S.EFFECT_LIST))
    for n in MUSIC:
        assert n in S.EFFECT_LIST
    for n in ["Music", "Music 0", "Music 7"]:
        assert n in S.LEGACY_EFFECTS and n not in S.EFFECT_LIST
    assert not set(MUSIC) & set(S.SCENE_NAMES.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("effect,music", [("Kpop", 7), ("Rock & Roll", 0), ("Music 3", 3), ("Music", 7)])
async def test_light_turn_on_music_names_and_legacy(effect, music):
    dev = FakeDevice()
    await BrizlabsLight(dev, entry()).async_turn_on(effect=effect)
    assert dev.sent == [{"switch_led": True, "work_mode": "music", "device_music": music}]


def test_light_and_select_report_names():
    dev = FakeDevice(values={"work_mode": "music", "device_music": 6})
    assert BrizlabsLight(dev, entry()).effect == "Rock"
    sel = BrizlabsMusicSelect(dev, entry())
    assert sel.options == MUSIC and sel.current_option == "Rock"


# ---- direction codec ---------------------------------------------------
def test_direction_constants_and_fixture_pair(ordered):
    assert (S.DIRECTION_RIGHT, S.DIRECTION_LEFT) == (0, 1)
    ev = ordered["scene_events"]
    left, right = ev[17]["payload"], ev[18]["payload"]
    assert S.direction_label(left) == "Left" and S.direction_label(right) == "Right"
    assert S.decode_scene(left).direction == 1 and S.decode_scene(right).direction == 0
    # only byte 0 differs
    assert left[2:] == right[2:]
    assert S.with_direction(right, "Left") == left
    assert S.with_direction(left, "Right") == right


def test_direction_roundtrip_all_ordered_events(ordered):
    for ev in ordered["scene_events"]:
        s = S.decode_scene(ev["payload"])
        assert S.encode_scene(s) == ev["payload"]
        assert S.with_direction(ev["payload"], S.direction_label(ev["payload"])) == ev["payload"]


def test_with_direction_changes_only_header_byte0(ordered):
    for ev in ordered["scene_events"]:
        for label, byte in (("Left", "01"), ("Right", "00")):
            assert S.with_direction(ev["payload"], label) == byte + ev["payload"][2:]


def test_with_direction_invalid():
    for bad in ("Up", "left", "", None):
        with pytest.raises(ValueError):
            S.with_direction(S.default_scene_payload(1), bad)
    with pytest.raises(ValueError):
        S.with_direction("garbage", "Left")


def test_direction_label_unknown_byte_is_none():
    assert S.direction_label("0201023200b403e803e800000000") is None
    assert S.direction_label("zz") is None


def test_build_scene_direction_param():
    p = S.encode_scene(S.build_scene(1, [(0, 100, 100)], direction="Left"))
    assert p.startswith("0101")
    assert S.encode_scene(S.build_scene(1, [(0, 100, 100)])).startswith("0001")  # default Right
    with pytest.raises(ValueError):
        S.build_scene(1, [(0, 100, 100)], direction="Sideways")


def test_palette_and_speed_preserve_direction_and_header(ordered):
    left = ordered["scene_events"][17]["payload"]
    assert S.apply_palette(left, "Red")[:8] == left[:8]
    assert S.with_speed(left, 9)[:2] == "01"
    assert S.with_speed(left, 9)[4:6] == left[4:6]
    assert S.with_speed(left, 9)[2:4] == left[2:4]


def test_set_scene_properties_direction():
    props = S.set_scene_properties("Flow", [(0, 100, 100)], direction="Left")
    assert props["dreamlight_scene_mode"].startswith("0101")
    props = S.set_scene_properties("Flow", [(0, 100, 100)])
    assert props["dreamlight_scene_mode"].startswith("0001")


def test_set_scene_schema_direction():
    base = {"address": "a", "effect": "Fall", "colors": [{"hue": 1, "saturation": 1}]}
    assert integ.SET_RGB_SCENE_SCHEMA({**base, "direction": "Left"})["direction"] == "Left"
    assert "direction" not in integ.SET_RGB_SCENE_SCHEMA(base)
    with pytest.raises(vol.Invalid):
        integ.SET_RGB_SCENE_SCHEMA({**base, "direction": "Up"})


@pytest.mark.asyncio
async def test_set_scene_service_direction():
    from types import SimpleNamespace
    from tests.test_setup_services import make_hass
    hass = make_hass()
    await integ.async_setup(hass, {})
    fn, schema = hass.services.reg[("brizlabs", "set_rgb_scene")]
    a, b = FakeDevice("00:11:22:33:44:55"), FakeDevice("00:11:22:33:44:66")
    hass.data["brizlabs"] = {"1": a, "2": b}
    await fn(SimpleNamespace(data=schema({"address": "00:11:22:33:44:55", "effect": "Flow", "direction": "Left",
                                          "colors": [{"hue": 0, "saturation": 100}]})))
    assert a.sent[0]["dreamlight_scene_mode"].startswith("0101") and b.sent == []


def test_services_yaml_documents_direction():
    import pathlib
    text = (pathlib.Path(integ.__file__).parent / "services.yaml").read_text()
    assert "direction:" in text and "Left" in text and "Right" in text


# ---- direction select ---------------------------------------------------
def _wire(ent):
    ent.written = 0

    def w():
        ent.written += 1
    ent.async_write_ha_state = w
    ent.async_on_remove = lambda f: None
    return ent


def test_direction_select_basics(ordered):
    right = ordered["scene_events"][18]["payload"]
    dev = FakeDevice(values={"work_mode": "scene", "dreamlight_scene_mode": right})
    sel = BrizlabsSceneDirectionSelect(dev, entry())
    assert sel.unique_id == "00:11:22:33:44:55_scene_direction"
    assert sel.options == ["Left", "Right"] and sel.current_option == "Right" and sel.available
    dev.values = {"work_mode": "music", "device_music": 1}
    assert not sel.available and sel.current_option is None


@pytest.mark.asyncio
async def test_direction_select_sends_only_header_change_no_optimism(ordered):
    right = ordered["scene_events"][18]["payload"]
    dev = FakeDevice(values={"work_mode": "scene", "bright_value": 33, "dreamlight_scene_mode": right})
    sel = _wire(BrizlabsSceneDirectionSelect(dev, entry()))
    await sel.async_added_to_hass()
    await sel.async_select_option("Left")
    assert dev.sent == [{"switch_led": True, "work_mode": "scene",
                         "dreamlight_scene_mode": "01" + right[2:]}]
    assert sel.current_option == "Right"
    dev.report(dreamlight_scene_mode=dev.sent[0]["dreamlight_scene_mode"])
    assert sel.current_option == "Left" and sel.written == 1


@pytest.mark.asyncio
async def test_direction_select_errors():
    dev = FakeDevice(values=scene_values(1))
    sel = BrizlabsSceneDirectionSelect(dev, entry())
    with pytest.raises(HomeAssistantError):
        await sel.async_select_option("Up")
    dev2 = FakeDevice(values={"work_mode": "music", "device_music": 0})
    with pytest.raises(HomeAssistantError):
        await BrizlabsSceneDirectionSelect(dev2, entry()).async_select_option("Left")
    assert dev.sent == [] and dev2.sent == []


@pytest.mark.asyncio
async def test_direction_select_unknown_byte_unavailable_current_none():
    dev = FakeDevice(values={"work_mode": "scene", "dreamlight_scene_mode": "0201023200b403e803e800000000"})
    sel = BrizlabsSceneDirectionSelect(dev, entry())
    assert sel.current_option is None
    await sel.async_select_option("Left")  # explicit user choice may overwrite the unknown byte
    assert dev.sent[0]["dreamlight_scene_mode"].startswith("0101")


@pytest.mark.asyncio
async def test_palette_speed_selects_preserve_direction_on_device(ordered):
    from custom_components.brizlabs.rgb.number import BrizlabsSceneSpeed
    from custom_components.brizlabs.rgb.select import BrizlabsScenePaletteSelect
    left = ordered["scene_events"][17]["payload"]
    dev = FakeDevice(values={"work_mode": "scene", "dreamlight_scene_mode": left})
    await BrizlabsScenePaletteSelect(dev, entry()).async_select_option("Blue")
    await BrizlabsSceneSpeed(dev, entry()).async_set_native_value(10)
    for sent in dev.sent:
        assert sent["dreamlight_scene_mode"].startswith("0101") and "bright_value" not in sent


@pytest.mark.asyncio
async def test_per_device_direction_independence(ordered):
    left, right = ordered["scene_events"][17]["payload"], ordered["scene_events"][18]["payload"]
    a = FakeDevice("00:11:22:33:44:55", {"work_mode": "scene", "dreamlight_scene_mode": right})
    b = FakeDevice("00:11:22:33:44:66", {"work_mode": "scene", "dreamlight_scene_mode": right})
    sa, sb = _wire(BrizlabsSceneDirectionSelect(a, entry())), _wire(BrizlabsSceneDirectionSelect(b, entry()))
    await sa.async_added_to_hass(); await sb.async_added_to_hass()
    await sa.async_select_option("Left")
    assert b.sent == []
    a.report(dreamlight_scene_mode=left)
    assert (sa.current_option, sb.current_option, sa.written, sb.written) == ("Left", "Right", 1, 0)


def test_platform_setup_adds_direction_select():
    import asyncio
    from types import SimpleNamespace
    from custom_components.brizlabs import select as sel_mod
    dev = FakeDevice()
    hass = SimpleNamespace(data={"brizlabs": {"e1": dev}})
    added = []
    asyncio.run(sel_mod.async_setup_entry(hass, entry(), added.extend))
    assert {type(e).__name__ for e in added} == {"BrizlabsScenePaletteSelect", "BrizlabsMusicSelect",
                                                 "BrizlabsSceneDirectionSelect"}
