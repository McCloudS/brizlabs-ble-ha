import pytest
from custom_components.brizlabs.rgb import scenes as S

SEQ = ["Rainbow", "Flow", "Up & Down", "Chase", "Shooting Star", "Pile Up", "Fall", "Fade",
       "Jump", "Breath", "Flicker", "Shuttle", "Random Flash", "Rebound", "Flutter"]

def P(x):
    """Palette label(s) without the colour-swatch prefix."""
    if isinstance(x, str):
        return S.strip_swatch(x)
    return x if x is None else [S.strip_swatch(i) for i in x]



def test_scene_names_follow_capture_tap_order_mapping():
    # Capture tap order (screenshot row-major) was ids 00,01,02,03,04,05,08,07,06,09..0e
    ids = [0, 1, 2, 3, 4, 5, 8, 7, 6, 9, 10, 11, 12, 13, 14]
    assert [S.SCENE_NAMES[i] for i in ids] == SEQ
    assert S.SCENE_NAMES[15] == "Filling"
    assert len(S.EFFECT_LIST) == len(set(S.EFFECT_LIST))


def test_name_roundtrip():
    for sid, name in S.SCENE_NAMES.items():
        assert S.scene_id_for_name(name) == sid
    with pytest.raises(ValueError):
        S.scene_id_for_name("Nope")


def test_catalog_matches_every_capture(capture):
    for item in capture["scenes"]:
        sid = int(item["scene_id_hex"], 16)
        scene = S.decode_scene(item["payload"])
        assert any(S.decode_scene(p).colors == scene.colors for p in S.CAPTURED_PALETTES[sid])


def test_catalog_has_no_extras(capture):
    captured = {(int(i["scene_id_hex"], 16), S.decode_scene(i["payload"]).colors) for i in capture["scenes"]}
    cat = {(sid, S.decode_scene(p).colors) for sid, ps in S.CAPTURED_PALETTES.items() for p in ps}
    assert cat == captured


def test_colour_labels():
    assert S.colour_label(S.Colour(0, 0, 1000)) == "White"
    assert S.colour_label(S.Colour(0, 1000, 1000)) == "Red"
    assert S.colour_label(S.Colour(288, 1000, 1000)) == "Purple"
    assert S.colour_label(S.Colour(111, 1000, 1000)) == "Hue 111"
    assert S.colour_label(S.Colour(120, 500, 1000)) == "Green 50%"
    assert S.colour_label(S.Colour(120, 1000, 500)) == "Green @50%"


def test_palette_options_unique_per_scene():
    for sid in S.SCENE_NAMES:
        opts = S.palette_options(sid)
        assert opts and len(opts) == len(set(opts))
    assert P(S.palette_options(4)) == P([label for label, _ in S.PRESET_PALETTES])
    assert P("White, Green") in P(S.palette_options(2))


def test_effect_for_values():
    assert S.effect_for_values({"work_mode": "music", "device_music": 3}) == "Energy"
    assert S.effect_for_values({"work_mode": "music"}) is None
    assert S.effect_for_values({"work_mode": "colour"}) is None
    assert S.effect_for_values({"work_mode": "scene"}) is None
    p = S.CAPTURED_PALETTES[8][0]
    assert S.effect_for_values({"work_mode": "scene", "dreamlight_scene_mode": p}) == "Fall"
    assert S.effect_for_values({"work_mode": "scene", "dreamlight_scene_mode": "garbage"}) is None


def test_music_helpers():
    assert S.MUSIC_OPTIONS[5] == "Pop"
    assert S.music_id_for_name("Music 5") == 5
    assert S.music_id_for_name("Music") == 7  # legacy alias
    with pytest.raises(ValueError):
        S.music_id_for_name("Music 8")


def test_default_scene_payload_uses_first_capture(capture):
    flow = S.default_scene_payload(1)
    assert flow == capture["scenes"][1]["payload"]
    assert S.default_scene_payload(0) == capture["scenes"][0]["payload"]


def test_apply_palette_preserves_speed_and_version():
    base = S.decode_scene(S.CAPTURED_PALETTES[1][0])
    cur = S.encode_scene(S.Scene(1, 1, 2, 33, base.colors))
    other = S.palette_options(1)[1]
    new = S.decode_scene(S.apply_palette(cur, other))
    assert (new.version, new.scene_id, new.change_mode, new.speed) == (1, 1, 2, 33)
    assert P(S.palette_label(S.encode_scene(new))) == P(other)
    assert new.colors != base.colors


def test_apply_palette_unknown_raises():
    with pytest.raises(ValueError):
        S.apply_palette(S.CAPTURED_PALETTES[1][0], "Bogus")


def test_palette_label_custom_for_uncaptured():
    custom = S.encode_scene(S.build_scene(1, [(10, 100, 100), (20, 100, 100)]))
    assert P(S.palette_label(custom)) == P("Custom: Hue 10, Hue 20")


def test_with_speed():
    p = S.CAPTURED_PALETTES[4][0]
    assert S.decode_scene(S.with_speed(p, 12)).speed == 12
    with pytest.raises(ValueError):
        S.with_speed(p, 101)
