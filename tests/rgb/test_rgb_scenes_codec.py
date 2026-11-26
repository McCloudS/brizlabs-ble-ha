import pytest
from custom_components.brizlabs.rgb import scenes


def test_fixture_shape(capture):
    assert len(capture["scenes"]) == 29
    assert len(capture["reports"]) == 71


def test_roundtrip_all_29_captured_payloads(capture):
    for item in capture["scenes"]:
        state = scenes.decode_scene(item["payload"])
        assert scenes.encode_scene(state) == item["payload"], item
        assert f"{state.scene_id:02x}" == item["scene_id_hex"]


def test_header_and_units_decoded():
    s = scenes.decode_scene("00000264000003e803e800000000001e03e803e800000000")
    assert (s.version, s.scene_id, s.change_mode, s.speed) == (0, 0, 2, 100)
    assert [(c.hue, c.saturation, c.value, c.white, c.temp) for c in s.colors] == [
        (0, 1000, 1000, 0, 0), (30, 1000, 1000, 0, 0)]


def test_speed_is_only_difference_between_captured_flow_variants(capture):
    payloads = [p["payload"] for p in capture["scenes"] if p["scene_id_hex"] == "01"][1:5]
    states = [scenes.decode_scene(p) for p in payloads]
    assert len({s.colors for s in states}) == 1
    assert sorted(s.speed for s in states) == [0x2b, 0x39, 0x3e, 0x44]


@pytest.mark.parametrize("bad", ["", "zz", "0001", "00010232" + "00", "0001023200b403e803e8000000", "00010232" + "0" * 20 + "0"])
def test_decode_rejects_malformed(bad):
    with pytest.raises(ValueError):
        scenes.decode_scene(bad)


def test_decode_rejects_zero_colours():
    with pytest.raises(ValueError):
        scenes.decode_scene("00010232")


def test_build_scene_arbitrary_colours():
    s = scenes.build_scene(0x01, [(120, 100, 100), (0, 0, 50)], speed=50)
    assert scenes.encode_scene(s) == "00010232" + "007803e803e800000000" + "0000000001f400000000"
    assert scenes.decode_scene(scenes.encode_scene(s)) == s


@pytest.mark.parametrize("kwargs", [
    dict(scene_id=16, colors=[(0, 100, 100)]),
    dict(scene_id=1, colors=[]),
    dict(scene_id=1, colors=[(0, 100, 100)] * 8),
    dict(scene_id=1, colors=[(361, 100, 100)]),
    dict(scene_id=1, colors=[(0, 101, 100)]),
    dict(scene_id=1, colors=[(0, 100, -1)]),
    dict(scene_id=1, colors=[(0, 100, 100)], speed=101),
])
def test_build_scene_validation(kwargs):
    with pytest.raises(ValueError):
        scenes.build_scene(**kwargs)
