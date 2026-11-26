# BrizLabs Micro String Lights (Home Assistant, local Bluetooth)

Custom integration v0.9.0, for BrizLabs RY micro string lights over BLE through Home Assistant's Bluetooth stack (local adapters and ESPHome/Shelly Bluetooth proxies). No cloud.

**Fork notice:** this repository is the maintained fork of [tgmstudios/brizlabs-ha](https://github.com/tgmstudios/brizlabs-ha). v0.4 replaces the scene codec after an HCI capture of the official iOS app showed the real protocol (`scene_select`); the corresponding upstream PR is [tgmstudios/brizlabs-ha#1](https://github.com/tgmstudios/brizlabs-ha/pull/1). Verified on a 500-LED curtain strand. The upstream `dreamlight_scene_mode` codec may be correct for other BrizLabs products; this fork targets hardware that reports `scene_select`.

**Status:** v0.4.0. The scene protocol was captured from the official iOS app over Bluetooth HCI and re-verified on real hardware: every scene, brightness level, colour/white balance, speed, loop sequence, and music mode in this integration maps to a frame the app itself sends. 61 automated tests replay the captured app traffic against a fake device. Unofficial, not affiliated with BrizLabs or Tuya.

## Installation
### HACS (custom repository)
Requires [HACS](https://www.hacs.dev/). This repository is **not** in the HACS default catalog, so add it manually:

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Fail-Safe&repository=brizlabs-ble-ha&category=integration)

1. HACS → ⋮ (top right) → **Custom repositories**, or use the badge above.
2. Repository: `https://github.com/Fail-Safe/brizlabs-ble-ha`, Type: **Integration**, then **Add**.
3. Find **BrizLabs Micro String Lights** in HACS, **Download**, and restart Home Assistant.
4. Settings → Devices & services → **Add integration** → BrizLabs Micro String Lights.
Requires the Home Assistant Bluetooth integration with at least one *connectable* scanner in range of the light: a local adapter or an ESPHome Bluetooth proxy with active connections enabled. Declared Home Assistant minimum (`hacs.json`) is 2026.8.2; tested on 2026.8.2 and 2026.11.3 (bleak 3.0.2).

### Manual
Copy `custom_components/brizlabs` into your Home Assistant `config/custom_components/` directory, restart, then add the integration.

HACS installs from the latest GitHub release if one exists, otherwise from the default branch. Packaging checks (HACS validation, hassfest, tests) run in GitHub Actions.

## Two light models
BrizLabs sells RY string lights that speak two different protocols. Pick the model when adding the light, or change it later under the integration's **Configure** button.

- **RGB** ("Micro String Lights RGB" in the app: colour wheel, colour schemes, scenes such as Rainbow, Flow, Chase): uses `work_mode` / `paint_colour_data` / `dreamlight_scene_mode`, the protocol from [tgmstudios/brizlabs-ha](https://github.com/tgmstudios/brizlabs-ha). Entities: light with HS colour, brightness and 16 scene + 8 music effects; scene palette, direction and music mode selects; scene speed, music sensitivity and pixel count numbers. Services `brizlabs.set_rgb_scene` (custom 1-7 colour scenes) and `brizlabs.paint_segments`.
- **Curtain** (scenes named C1/C2 Steady On, Color Mixture, ...): uses `scene_select`, documented below.

Entries created before v0.6.0 default to Curtain. Verified on an RGB micro string: solid colour via `paint_colour_data` confirmed on hardware.

## What changed in v0.9.0
- The RGB string acknowledges a bare state request (`ble recv all data success`) without sending its state; it only pushes `thing.property.report` when something changes. On connect the integration now tries several request formats once each, remembers the one the light answers (logged at info level), and only polls when one works.
- The RGB light restores its last Home Assistant state after a restart, so it no longer comes back as off/unknown; reports pushed by the light update it from there.

## What changed in v0.8.0
- RGB palette labels name the colours in order (`White · Red · Green`, `Yellow · Lime · Cyan · Purple · Sky blue`) instead of emoji squares. The original names and the v0.7.0 emoji labels are still accepted.
- State sync: on connect the integration asks for the light's state until it answers (3 tries), accepts more report shapes, and RGB lights are re-read every 60 s so changes from the app or remote show up. Received reports are logged at debug level.

## What changed in v0.7.0
- RGB palette dropdown labels start with colour squares (e.g. `🟥🟩 Red + Green`). Plain names without the squares are still accepted by `select.select_option`.
- Picture tiles for every RGB scene and palette are served by the integration at `/brizlabs_static/scene_<name>.svg` and `/brizlabs_static/palette_<name>.svg` (regenerate with `python3 scripts/make_swatches.py`). Use them in `picture` cards with a `tap_action`.

## What changed in v0.6.0
- RGB model added alongside the curtain model, selected per light (config flow + options flow; changing it reloads the entry).
- RGB scene 16 is named `Filling` (from the iOS app grid). Legacy `Music N` effect names are still accepted but hidden from the effect list.

## What changed in v0.5.0
- The connection now goes through `homeassistant.components.bluetooth` and `bleak-retry-connector` instead of talking to BlueZ over D-Bus at `/org/bluez/hci0`. Lights reached through ESPHome Bluetooth proxies now work, and HA picks whichever connectable scanner hears the light best.
- Bluetooth discovery: lights advertising as `RY` with service `0000a101-...` show up under *Discovered*, and the setup form lists them. Manual MAC entry is still available.
- The connection reacts to the disconnect callback immediately instead of polling every 5 seconds.
- The light holds a persistent connection, so it uses one of the proxy's active-connection slots (ESPHome proxies have 3 by default).

## What changed in v0.4.0
v0.3 controlled scenes through `dreamlight_scene_mode` / `work_mode` payloads inferred from a related product. An HCI capture of the official app proved the actual protocol is different: scenes are a single `scene_select` string, `work_mode` is never written, and brightness, colour/white balance, and speed all ride inside `scene_select`. v0.4.0 replaces the old codec end to end. The palette and direction selects, `paint_segments`, HS colour, and the pixel-count number are removed (they belong to the old codec and the device ignores them). Light unique IDs are unchanged, so existing automations keep working.

## Entities
- **Light** – on/off, brightness, and an *effect* list: the 14 app scene tiles (`C1 Steady On`, `C2 Steady On`, `Color Mixture`, `Fade`, `C1 Breath`, `C2 Breath`, `C1 Flash`, `C2 Flash`, `Chasing-Flash 1`, `Chasing-Flash 2`, `Sequential`, `Alternating Flash`, `Slow-Glow`, `In Waves`), plus `Loop` and `Music`. Choosing an effect sends the same frame the app sends when the tile is tapped. Setting brightness while a scene is active updates the brightness field inside `scene_select` (the app's own behaviour); with no scene active it falls back to `bright_value`.
- **White mix** (number, 0–100 %) – the colour↔white balance field of the active scene (0 = full colour, 100 = full white). Available while a scene is active.
- **Scene speed** (number, 1–4) – animation speed of the active scene. Available while a scene is active.
- **Music sensitivity** (number, 0–100) – microphone sensitivity for music mode.
- **Music mode** (select) – `Rock & Roll`, `Jazz`, `Classical`, `Energy`, `Roll`, `Pop`, `Rock`, `Kpop` (`device_music` 0–7, verified by ordered capture). Usable whenever the device is connected; the selection is tracked locally because the device never reports `device_music` back.

## Services
- `brizlabs.set_scene` – `address`, `effect` (scene name), optional `brightness` (0–1000), `mix` (0–1000), `speed` (0–4), and `combine` (loop sequence as concatenated scene hex ids, e.g. `2021`; defaults to all 14 scenes).
- `brizlabs.set_properties` – send raw device properties (advanced; no validation).

## Protocol notes (`scene_select`)
Every scene change is one `thing.property.set` carrying `scene_select`: 17 hex characters — `scene(2) brightness(4) white_mix(4) speed(2) reserved(5)`. Scene ids are `20`–`2d` for the grid and `1e` for loop; brightness and mix are 0–1000; speed is 0 for the steady scenes and 1–4 otherwise; the reserved tail is always `00000`. Loop additionally writes `scene_combine` (the hex-concatenated ids to cycle). Music mode is a bare `device_music` write; on/off is `switch_led`. The device's own reports are unreliable (they claim stale values and omit `device_music`), so the integration tracks what it sends.

## Known limits
- The device accepts only one Bluetooth central at a time; the official app and Home Assistant cannot both be connected.
- Scene names come from the app's tile labels in grid order; effect names could change if a firmware/app revision reorders the grid.
- Tests use a fake device replaying captured app traffic; run with `pip install pytest pytest-asyncio homeassistant bleak` then `python -m pytest`.

## License
No license file is included and none has been chosen; visibility of this repository alone does not grant reuse rights.
