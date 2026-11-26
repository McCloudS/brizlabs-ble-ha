"""Pure codec for the BrizLabs ``dreamlight_scene_mode`` hex payload.

Layout proven from the Pi capture of the Android app (29 payloads, scenes 00-0f):

* 4-byte header: direction (0 Right, 1 Left; proven by the ordered capture and
  exposed as ``Scene.version`` for compatibility), scene id, change mode (always 0x02 = Tuya "gradual"),
  speed (0-100; the only byte that differed between otherwise identical
  captures of scene 01).
* N x 10-byte colour units: H, S, V, white brightness, colour temperature, each
  big-endian uint16 (H 0-360, the rest 0-1000), matching the Tuya common-scene
  ``scene_data`` unit layout.  Captures only ever used 1-7 units.

The Tuya doc lists a different (interval/duration) header; the captured 4-byte
header is what this device actually uses, so it is decoded empirically.
"""

from __future__ import annotations

from dataclasses import dataclass

HEADER_BYTES = 4
UNIT_BYTES = 10
MAX_COLOURS = 7  # largest count observed in captures
MAX_SPEED = 100
DEFAULT_CHANGE_MODE = 2
DIRECTION_RIGHT = 0
DIRECTION_LEFT = 1
DIRECTIONS = {"Left": DIRECTION_LEFT, "Right": DIRECTION_RIGHT}
DIRECTION_OPTIONS = ["Left", "Right"]


@dataclass(frozen=True)
class Colour:
    hue: int
    saturation: int  # 0-1000
    value: int  # 0-1000
    white: int = 0
    temp: int = 0


@dataclass(frozen=True)
class Scene:
    version: int
    scene_id: int
    change_mode: int
    speed: int
    colors: tuple[Colour, ...]

    @property
    def direction(self) -> int:
        """Header byte 0: 0 = Right, 1 = Left (``version`` kept as legacy name)."""
        return self.version


def direction_byte(direction) -> int:
    try:
        return DIRECTIONS[direction]
    except (KeyError, TypeError):
        raise ValueError(f"direction must be one of {DIRECTION_OPTIONS}") from None


def direction_label(payload: str) -> str | None:
    try:
        byte = decode_scene(payload).direction
    except (ValueError, TypeError):
        return None
    return {v: k for k, v in DIRECTIONS.items()}.get(byte)


def with_direction(payload: str, direction: str) -> str:
    byte = direction_byte(direction)
    s = decode_scene(payload)
    return encode_scene(Scene(byte, s.scene_id, s.change_mode, s.speed, s.colors))


def decode_scene(payload: str) -> Scene:
    try:
        raw = bytes.fromhex(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError("scene payload is not hex") from exc
    body = len(raw) - HEADER_BYTES
    if body < UNIT_BYTES or body % UNIT_BYTES:
        raise ValueError("scene payload has invalid length")
    units = []
    for i in range(HEADER_BYTES, len(raw), UNIT_BYTES):
        h, s, v, w, t = (int.from_bytes(raw[i + j:i + j + 2], "big") for j in range(0, 10, 2))
        if h > 360 or max(s, v, w, t) > 1000:
            raise ValueError("scene colour unit out of range")
        units.append(Colour(h, s, v, w, t))
    return Scene(raw[0], raw[1], raw[2], raw[3], tuple(units))


def encode_scene(scene: Scene) -> str:
    out = bytes([scene.version, scene.scene_id, scene.change_mode, scene.speed])
    for c in scene.colors:
        out += b"".join(x.to_bytes(2, "big") for x in (c.hue, c.saturation, c.value, c.white, c.temp))
    return out.hex()


def build_scene(scene_id, colors, speed=50, version=0, change_mode=DEFAULT_CHANGE_MODE,
                direction=None) -> Scene:
    """Build a scene from (hue 0-360, saturation 0-100, value 0-100) triples."""
    if direction is not None:
        version = direction_byte(direction)
    if not 0 <= scene_id <= 15:
        raise ValueError("scene id must be 0-15")
    if not 0 <= speed <= MAX_SPEED:
        raise ValueError("speed must be 0-100")
    colors = list(colors)
    if not 1 <= len(colors) <= MAX_COLOURS:
        raise ValueError(f"scene needs 1-{MAX_COLOURS} colours")
    units = []
    for hue, sat, val in colors:
        if not (0 <= hue <= 360 and 0 <= sat <= 100 and 0 <= val <= 100):
            raise ValueError("colour out of range (hue 0-360, saturation/value 0-100)")
        units.append(Colour(round(hue), round(sat * 10), round(val * 10)))
    return Scene(version, scene_id, change_mode, speed, tuple(units))


# --- Scene / music naming -------------------------------------------------
# Names are the Android app's screenshot grid (row-major).  The ID->name map is
# PROVISIONAL: it comes from the order the scenes were tapped during capture
# (ids 00,01,02,03,04,05,08,07,06,09..0e), NOT from numeric grid order, and has
# not been confirmed against Tuya docs (they publish no per-id names).
SCENE_NAMES: dict[int, str] = {
    0x00: "Rainbow", 0x01: "Flow", 0x02: "Up & Down", 0x03: "Chase",
    0x04: "Shooting Star", 0x05: "Pile Up", 0x08: "Fall", 0x07: "Fade",
    0x06: "Jump", 0x09: "Breath", 0x0A: "Flicker", 0x0B: "Shuttle",
    0x0C: "Random Flash", 0x0D: "Rebound", 0x0E: "Flutter",
    0x0F: "Filling",  # 16th app tile; name confirmed from the iOS app grid
}
# Music names VERIFIED by the ordered capture (device_music 0..7 in tap order).
MUSIC_OPTIONS = ["Rock & Roll", "Jazz", "Classical", "Energy", "Roll", "Pop", "Rock", "Kpop"]
LEGACY_MUSIC_NAMES = [f"Music {i}" for i in range(8)]  # v0.2 names, still accepted
LEGACY_MUSIC_EFFECT = "Music"  # earlier release alias for device_music 7
# Effects shown in the UI: app scene tiles in grid order, then music modes.
EFFECT_LIST = ([SCENE_NAMES[i] for i in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x08, 0x07, 0x06,
                                         0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F)]
               + MUSIC_OPTIONS)
# Older effect names still accepted by turn_on / services.
LEGACY_EFFECTS = LEGACY_MUSIC_NAMES + [LEGACY_MUSIC_EFFECT]
_NAME_TO_ID = {v: k for k, v in SCENE_NAMES.items()}


def scene_id_for_name(name: str) -> int:
    try:
        return _NAME_TO_ID[name]
    except KeyError:
        raise ValueError(f"Unknown scene effect: {name}") from None


def music_id_for_name(name: str) -> int:
    if name == LEGACY_MUSIC_EFFECT:
        return 7
    if name in MUSIC_OPTIONS:
        return MUSIC_OPTIONS.index(name)
    if name in LEGACY_MUSIC_NAMES:
        return LEGACY_MUSIC_NAMES.index(name)
    raise ValueError(f"Unknown music mode: {name}")

# Captured palettes: first-seen payload per distinct colour list (from tests/fixtures capture).
CAPTURED_PALETTES: dict[int, tuple[str, ...]] = {
    0x00: (
        "00000264000003e803e800000000001e03e803e800000000003c03e803e800000000007803e803e80000000000b403e803e80000000000f003e803e800000000012003e803e800000000",
    ),
    0x01: (
        "0001023e006f03e803e800000000004103e803e80000000000b403e803e800000000013103e803e80000000000d103e803e800000000",
        "0001023e000803e803e800000000001e03e803e800000000003d03e803e800000000013f03e803e800000000006603e803e800000000",
    ),
    0x02: (
        "000202320000000003e800000000007803e803e800000000",
    ),
    0x03: (
        "000302520000000003e800000000000003e803e800000000",
        "00030252012003e803e800000000007803e803e800000000",
    ),
    0x04: (
        "0004023200b403e803e800000000",
    ),
    0x05: (
        "0005023200b403e803e800000000",
    ),
    0x06: (
        "0006023200b403e803e800000000",
    ),
    0x07: (
        "00070232001e03e803e800000000000003e803e800000000007803e803e800000000003c03e803e80000000000f003e803e800000000",
    ),
    0x08: (
        "00080232001e03e803e800000000000003e803e800000000007803e803e800000000003c03e803e80000000000f003e803e800000000",
    ),
    0x09: (
        "000902320000000003e800000000000003e803e800000000",
        "00090232001e03e803e800000000000003e803e800000000007803e803e800000000003c03e803e80000000000f003e803e800000000",
    ),
    0x0a: (
        "000a02320000000003e800000000000003e803e800000000",
        "000a02320000000003e800000000000003e803e800000000007803e803e800000000",
    ),
    0x0b: (
        "000b02320000000003e800000000007803e803e800000000",
        "000b0232012003e803e800000000007803e803e800000000",
    ),
    0x0c: (
        "000c02320000000003e800000000000003e803e800000000007803e803e800000000",
        "000c0232001e03e803e800000000000003e803e800000000007803e803e800000000003c03e803e80000000000f003e803e800000000",
    ),
    0x0d: (
        "000d02320000000003e80000000000f003e803e800000000",
        "000d02320000000003e800000000000003e803e800000000007803e803e800000000",
    ),
    0x0e: (
        "000e02320000000003e80000000000f003e803e800000000",
        "000e0232000003e803e800000000007803e803e800000000",
    ),
    0x0f: (
        "000f023d0000000003e80000000000f003e803e800000000",
        "000f023d001e03e803e800000000000003e803e800000000007803e803e800000000003c03e803e80000000000f003e803e800000000",
    ),
}

# --- Labels / palettes ----------------------------------------------------
_HUE_NAMES = {0: "Red", 30: "Orange", 60: "Yellow", 120: "Green", 180: "Cyan",
              240: "Blue", 288: "Purple", 360: "Red"}


def colour_label(c: Colour) -> str:
    if c.saturation == 0:
        return "White"
    name = _HUE_NAMES.get(c.hue, f"Hue {c.hue}")
    if c.saturation < 1000:
        return f"{name} {round(c.saturation / 10)}%"
    if c.value < 1000:
        return f"{name} @{round(c.value / 10)}%"
    return name


def _colors_label(colors) -> str:
    return ", ".join(colour_label(c) for c in colors)


def _c(h, s=1000):
    return Colour(h, s, 1000)


# Fifteen app preset palettes, GLOBAL: the same colour lists are offered for
# every scene.  Taken verbatim (hue/saturation 0-1000/value) from the ordered
# capture (tests/fixtures/ordered-presets-capture.json, events
# 56.117-79.225 s).  Labels are descriptive, not app text (swatches are unlabeled).
PRESET_PALETTES: tuple[tuple[str, tuple[Colour, ...]], ...] = (
    ("Green gradient", (_c(111), _c(111, 515), _c(111, 0))),
    ("Rainbow 1", (_c(62), _c(92), _c(179), _c(294), _c(203))),
    ("Rainbow 2", (_c(111), _c(65), _c(180), _c(305), _c(209))),
    ("Rainbow 3", (_c(8), _c(30), _c(61), _c(319), _c(102))),
    ("Red", (_c(0),)),
    ("Green", (_c(120),)),
    ("Blue", (_c(240),)),
    ("Cyan", (_c(180),)),
    ("Purple", (_c(288),)),
    ("Orange", (_c(30),)),
    ("Purple + Orange", (_c(288), _c(30))),
    ("White + Red", (_c(0, 0), _c(0))),
    ("Red + Green", (_c(0), _c(120))),
    ("White + Blue", (_c(0, 0), _c(240))),
    ("White + Red + Green", (_c(0, 0), _c(0), _c(120))),
)
_PRESET_COLORS = {label: colors for label, colors in PRESET_PALETTES}


def _extra_palettes(scene_id: int) -> list[tuple[str, tuple[Colour, ...]]]:
    """Older captured palettes of a scene that are not among the 15 presets."""
    preset_sets = set(_PRESET_COLORS.values())
    found: list[tuple[Colour, ...]] = []
    for payload in CAPTURED_PALETTES.get(scene_id, ()):
        colors = decode_scene(payload).colors
        if colors not in preset_sets and colors not in found:
            found.append(colors)
    out, used = [], set(_PRESET_COLORS)
    for colors in found:
        base = _colors_label(colors)
        label, n = base, 1
        while label in used:
            n += 1
            label = f"{base} ({n})"
        used.add(label)
        out.append((label, colors))
    return out


def _palettes(scene_id: int) -> list[tuple[str, tuple[Colour, ...]]]:
    return list(PRESET_PALETTES) + _extra_palettes(scene_id)


def palette_options(scene_id: int) -> list[str]:
    """Labels offered for a scene: the 15 global presets, then legacy extras."""
    return [label for label, _ in _palettes(scene_id)]


def palette_label(payload: str) -> str | None:
    """Label of the palette in ``payload``; ``Custom: ...`` if not a known one."""
    try:
        scene = decode_scene(payload)
    except (ValueError, TypeError):
        return None
    for label, colors in _palettes(scene.scene_id):
        if colors == scene.colors:
            return label
    return f"Custom: {_colors_label(scene.colors)}"


def _legacy_palette_colors(label: str):
    """Colours for a pre-0.3 per-scene label (e.g. ``Red, Green``), if any."""
    for payloads in CAPTURED_PALETTES.values():
        for payload in payloads:
            colors = decode_scene(payload).colors
            if _colors_label(colors) == label:
                return colors
    return None


def apply_palette(current_payload: str, label: str) -> str:
    """Swap the colours of the current scene for a preset/extra palette, keeping
    the scene id, speed, change mode and header direction byte."""
    current = decode_scene(current_payload)
    colors = dict(_palettes(current.scene_id)).get(label)
    if colors is None:
        legacy = _legacy_palette_colors(label)
        # accept an old label only if it still maps to an offered palette
        if legacy is not None and legacy in [c for _, c in _palettes(current.scene_id)]:
            colors = legacy
    if colors is None:
        raise ValueError(f"Unknown palette for scene {current.scene_id:02x}: {label}")
    return encode_scene(Scene(current.version, current.scene_id, current.change_mode,
                              current.speed, colors))


def with_speed(payload: str, speed: int) -> str:
    if not 0 <= speed <= MAX_SPEED:
        raise ValueError("speed must be 0-100")
    s = decode_scene(payload)
    return encode_scene(Scene(s.version, s.scene_id, s.change_mode, speed, s.colors))


def default_scene_payload(scene_id: int) -> str:
    """First captured payload (app default palette and speed) for a scene."""
    try:
        return CAPTURED_PALETTES[scene_id][0]
    except KeyError:
        raise ValueError(f"No captured payload for scene {scene_id:02x}") from None


def effect_for_values(values: dict) -> str | None:
    """Effect name derived purely from reported device state."""
    mode = values.get("work_mode")
    if mode == "music":
        music = values.get("device_music")
        return MUSIC_OPTIONS[music] if isinstance(music, int) and 0 <= music < 8 else None
    if mode == "scene":
        try:
            return SCENE_NAMES.get(decode_scene(values.get("dreamlight_scene_mode", "")).scene_id)
        except (ValueError, TypeError):
            return None
    return None


def set_scene_properties(effect: str, colors, speed: int = 50, brightness: int | None = None,
                         direction: str | None = None) -> dict:
    """Property dict for a scene effect with an arbitrary ordered colour list.

    ``colors`` are (hue 0-360, saturation 0-100, value 0-100) triples.
    """
    scene_id = scene_id_for_name(effect)
    payload = encode_scene(build_scene(scene_id, colors, speed, direction=direction))
    props = {"switch_led": True, "work_mode": "scene", "dreamlight_scene_mode": payload}
    if brightness is not None:
        if not 1 <= brightness <= 100:
            raise ValueError("brightness must be 1-100")
        props["bright_value"] = brightness
    return props
