import pytest
from custom_components.brizlabs.rgb import scenes as S

LABELS = ["Green gradient", "Rainbow 1", "Rainbow 2", "Rainbow 3", "Red", "Green", "Blue", "Cyan",
          "Purple", "Orange", "Purple + Orange", "White + Red", "Red + Green", "White + Blue",
          "White + Red + Green"]

def P(x):
    """Palette label(s) without the colour-swatch prefix."""
    if isinstance(x, str):
        return S.strip_swatch(x)
    return x if x is None else [S.strip_swatch(i) for i in x]



def test_ordered_fixture_is_clean(ordered):
    assert ordered["errors"] == [] and ordered["pending"] == []
    assert len(ordered["reports"]) == 31
    assert len(ordered["scene_events"]) == 21 and len(ordered["music_events"]) == 8


def test_preset_labels_in_capture_order():
    assert [label for label, _ in S.PRESET_PALETTES] == LABELS


def test_presets_match_capture_events_1_to_15_exactly(ordered):
    events = ordered["scene_events"][1:16]
    assert len(events) == 15
    for (label, colors), ev in zip(S.PRESET_PALETTES, events):
        assert colors == S.decode_scene(ev["payload"]).colors, label


def test_green_gradient_keeps_exact_saturation():
    colors = dict(S.PRESET_PALETTES)["Green gradient"]
    assert [(c.hue, c.saturation, c.value) for c in colors] == [(111, 1000, 1000), (111, 515, 1000), (111, 0, 1000)]


def test_event_0_and_restore_are_not_presets(ordered):
    # opening flow palette (event 0) equals Rainbow 2 colours only because the app was on it already
    first = S.decode_scene(ordered["scene_events"][0]["payload"]).colors
    assert first == dict(S.PRESET_PALETTES)["Rainbow 2"]


@pytest.mark.parametrize("sid", sorted(S.SCENE_NAMES))
def test_every_scene_offers_all_fifteen_presets_first(sid):
    assert P(S.palette_options(sid)[:15]) == P(LABELS)


@pytest.mark.parametrize("sid", sorted(S.SCENE_NAMES))
def test_options_unique_and_no_duplicate_colours(sid):
    opts = S.palette_options(sid)
    assert len(opts) == len(set(opts))
    base = S.default_scene_payload(sid)
    colors = [S.decode_scene(S.apply_palette(base, o)).colors for o in opts]
    assert len(colors) == len(set(colors))


def test_legacy_extras_only_when_not_a_preset():
    preset_colors = {c for _, c in S.PRESET_PALETTES}
    for sid, payloads in S.CAPTURED_PALETTES.items():
        extras = S.palette_options(sid)[15:]
        wanted = []
        for p in payloads:
            cols = S.decode_scene(p).colors
            if cols not in preset_colors and cols not in wanted:
                wanted.append(cols)
        assert len(extras) == len(wanted), sid
    # the 7-colour Rainbow (scene 0) is kept as an extra
    assert len(S.palette_options(0)) > 15


@pytest.mark.parametrize("sid", sorted(S.SCENE_NAMES))
@pytest.mark.parametrize("speed", [0, 62, 100])
@pytest.mark.parametrize("direction", [0, 1])
def test_apply_each_preset_keeps_scene_speed_direction(sid, speed, direction):
    base = S.decode_scene(S.default_scene_payload(sid))
    cur = S.encode_scene(S.Scene(direction, sid, base.change_mode, speed, base.colors))
    for label, colors in S.PRESET_PALETTES:
        new = S.decode_scene(S.apply_palette(cur, label))
        assert (new.version, new.scene_id, new.change_mode, new.speed) == (direction, sid, base.change_mode, speed)
        assert new.colors == colors
        assert P(S.palette_label(S.encode_scene(new))) == P(label)


def test_palette_label_recognises_preset_in_any_scene(ordered):
    for (label, _), ev in zip(S.PRESET_PALETTES, ordered["scene_events"][1:16]):
        assert P(S.palette_label(ev["payload"])) == P(label)


def test_legacy_label_aliases_still_apply():
    flow = S.default_scene_payload(1)
    # old per-scene labels for colour lists that are now presets
    assert S.decode_scene(S.apply_palette(flow, "Red, Green")).colors == dict(S.PRESET_PALETTES)["Red + Green"]
    assert S.decode_scene(S.apply_palette(flow, "Cyan")).colors == dict(S.PRESET_PALETTES)["Cyan"]


def test_custom_still_custom():
    custom = S.encode_scene(S.build_scene(1, [(10, 100, 100), (20, 100, 100)]))
    assert P(S.palette_label(custom)) == P("Custom: Hue 10, Hue 20")


def test_dropdown_labels_carry_colour_swatch_and_round_trip():
    flow = S.default_scene_payload(1)
    opts = S.palette_options(1)
    assert opts[12] == "\U0001F7E5\U0001F7E9 Red + Green"
    assert opts[11] == "⬜\U0001F7E5 White + Red"
    for opt in opts:
        # the swatch label and the plain name select the same colours
        assert S.apply_palette(flow, opt) == S.apply_palette(flow, S.strip_swatch(opt))
        assert S.palette_label(S.apply_palette(flow, opt)) == opt
    assert S.strip_swatch("Red + Green") == "Red + Green"
