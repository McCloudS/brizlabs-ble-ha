"""Service registration and the persistent BLE connection."""

import asyncio
import logging
import time
import uuid
from pathlib import Path

import voluptuous as vol
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from . import scenes
from .rgb import scenes as rgb_scenes
from .const import DOMAIN, NOTIFY_UUID, WRITE_UUID
from .protocol import Decoder, encode

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["light", "number", "select"]

_COLOUR_SCHEMA = vol.Schema({
    vol.Required("hue"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
    vol.Required("saturation"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    vol.Optional("value", default=100): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
})
SET_RGB_SCENE_SCHEMA = vol.Schema({
    vol.Required("address"): str,
    vol.Required("effect"): vol.In(sorted(rgb_scenes.SCENE_NAMES.values())),
    vol.Required("colors"): vol.All([_COLOUR_SCHEMA], vol.Length(min=1, max=rgb_scenes.MAX_COLOURS)),
    vol.Optional("speed", default=50): vol.All(vol.Coerce(int), vol.Range(min=0, max=rgb_scenes.MAX_SPEED)),
    vol.Optional("brightness"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    vol.Optional("direction"): vol.In(rgb_scenes.DIRECTION_OPTIONS),
})
PAINT_SEGMENTS_SCHEMA = vol.Schema({
    vol.Required("address"): str,
    vol.Required("segments"): [vol.Coerce(int)],
    vol.Required("hue"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
    vol.Required("saturation"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    vol.Optional("value", default=100): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    vol.Optional("segment_count", default=20): vol.All(vol.Coerce(int), vol.Range(min=1, max=127)),
})
SET_SCENE_SCHEMA = vol.Schema({
    vol.Required("address"): str,
    vol.Required("effect"): vol.In(scenes.EFFECT_LIST),
    vol.Optional("brightness"): vol.All(vol.Coerce(int), vol.Range(min=0, max=scenes.MAX_LEVEL)),
    vol.Optional("mix"): vol.All(vol.Coerce(int), vol.Range(min=0, max=scenes.MAX_LEVEL)),
    vol.Optional("speed"): vol.All(vol.Coerce(int), vol.Range(min=0, max=scenes.MAX_SPEED)),
    vol.Optional("combine"): vol.All(str, vol.Length(min=2, max=28)),
})


STATIC_URL = "/brizlabs_static"
RGB_POLL_SECONDS = 60


async def _register_static(hass):
    """Serve the dashboard swatch images shipped in www/ at /brizlabs_static/."""
    http = getattr(hass, "http", None)
    if http is None:
        return
    from homeassistant.components.http import StaticPathConfig
    await http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "www"), True)])


async def async_setup(hass, config):
    await _register_static(hass)
    def _device(call):
        address = call.data["address"].upper()
        device = next((d for d in hass.data.get(DOMAIN, {}).values() if d.address == address), None)
        if device is None:
            raise ValueError(f"No BrizLabs device configured at {address}")
        return device

    async def set_properties(call):
        await _device(call).send(call.data["properties"])

    async def set_scene(call):
        props = scenes.scene_properties(call.data["effect"], call.data.get("brightness"),
                                        call.data.get("mix"), call.data.get("speed"))
        if "combine" in call.data:
            props["scene_combine"] = call.data["combine"]
        await _device(call).send(props)

    async def set_rgb_scene(call):
        colors = [(c["hue"], c["saturation"], c["value"]) for c in call.data["colors"]]
        await _device(call).send(rgb_scenes.set_scene_properties(
            call.data["effect"], colors, call.data["speed"], call.data.get("brightness"),
            call.data.get("direction")))

    async def paint_segments(call):
        from .rgb.light import paint_colour
        try:
            paint = paint_colour(call.data["hue"], call.data["saturation"], call.data["value"],
                                 call.data["segments"], call.data["segment_count"])
        except ValueError as exc:
            raise vol.Invalid(str(exc)) from exc
        await _device(call).send({"switch_led": True, "work_mode": "colour", "paint_colour_data": paint})

    hass.services.async_register(DOMAIN, "set_scene", set_scene, schema=SET_SCENE_SCHEMA)
    hass.services.async_register(DOMAIN, "set_rgb_scene", set_rgb_scene, schema=SET_RGB_SCENE_SCHEMA)
    hass.services.async_register(DOMAIN, "paint_segments", paint_segments, schema=PAINT_SEGMENTS_SCHEMA)
    hass.services.async_register(DOMAIN, "set_properties", set_properties,
        schema=vol.Schema({vol.Required("address"): str, vol.Required("properties"): dict}))
    return True


def _property_values(data):
    """Flatten a report's data into {key: value}.

    Seen shapes: {"k": v}, {"k": {"value": v}} (valueless dicts are set-acks and
    are skipped), and [{"key"/"code": k, "value": v}, ...].
    """
    out = {}
    if isinstance(data, dict):
        items = data.items()
    elif isinstance(data, list):
        items = [((d.get("key") or d.get("code")), d) for d in data if isinstance(d, dict)]
    else:
        return None
    for key, value in items:
        if key is None:
            continue
        if isinstance(value, dict):
            if "value" not in value:
                continue
            value = value["value"]
        out[key] = value
    return out


KNOWN_PROPERTIES = {"switch_led", "work_mode", "bright_value", "paint_colour_data",
                    "dreamlight_scene_mode", "scene_select", "scene_combine", "device_music",
                    "sensitivity", "lightpixel_number_set", "light_pixel", "temp_value"}


def _find_properties(obj, depth=0):
    """Locate the light's properties anywhere in a report whose layout we don't know.

    Returns the first mapping (or key/value list) that holds a known property name.
    """
    if depth > 6:
        return None
    candidate = _property_values(obj) if isinstance(obj, (dict, list)) else None
    if candidate and KNOWN_PROPERTIES & set(candidate):
        return candidate
    children = obj.values() if isinstance(obj, dict) else obj if isinstance(obj, list) else ()
    for child in children:
        if isinstance(child, (dict, list)):
            found = _find_properties(child, depth + 1)
            if found:
                return found
    return None


_NO_DATA = object()
# State-request payloads to try, in order. #0 is what the app-derived code sent.
GET_VARIANTS = (
    [],
    sorted(KNOWN_PROPERTIES),
    {key: None for key in sorted(KNOWN_PROPERTIES)},
    _NO_DATA,
)


class _NotSeen(Exception):
    """The light is not currently heard by any connectable scanner."""


class BrizlabsDevice:
    def __init__(self, hass: HomeAssistant, address: str, poll_interval: float | None = None):
        self.hass = hass
        self.address = address
        self.values = {}
        self.available = False
        self.listeners = set()
        self.client = None
        self.write_char = None
        self.decoder = Decoder()
        self.lock = asyncio.Lock()
        self.task = None
        self.stop = asyncio.Event()
        self.disconnected = asyncio.Event()
        self._warned_missing = False
        self.poll_interval = poll_interval
        self.report_event = asyncio.Event()
        self.last_report = None
        self.get_variant = None  # index into GET_VARIANTS once one is known to work

    def subscribe(self, callback):
        self.listeners.add(callback)
        return lambda: self.listeners.discard(callback)

    def update(self):
        for callback in tuple(self.listeners):
            callback()

    def notification(self, _sender, data):
        message = self.decoder.feed(bytes(data))
        if message is None:
            return  # partial multi-packet message, or a frame the decoder rejected
        _LOGGER.debug("BrizLabs %s rx: %.1500r", self.address, message)
        if not isinstance(message, dict):
            return
        kind = str(message.get("type") or message.get("method") or "")
        if kind.endswith("property.set"):
            return  # our own command echoed back, or a set-ack
        values = _property_values(message.get("data")) if "data" in message else None
        if not values:
            values = _find_properties(message)
        if not values:
            return
        self.last_report = time.monotonic()
        self.report_event.set()
        changed = False
        for key, value in values.items():
            if self.values.get(key) != value:
                self.values[key] = value
                changed = True
        if changed:
            self.update()

    def _disconnected(self, _client):
        self.disconnected.set()

    async def run(self):
        """Keep a persistent connection through Home Assistant's Bluetooth stack.

        Going through ``homeassistant.components.bluetooth`` lets the connection
        use whichever connectable scanner currently hears the light best: a
        local adapter or an ESPHome / Shelly Bluetooth proxy.
        """
        while not self.stop.is_set():
            client = None
            try:
                ble_device = bluetooth.async_ble_device_from_address(
                    self.hass, self.address, connectable=True)
                if ble_device is None:
                    if not self._warned_missing:
                        _LOGGER.warning(
                            "BrizLabs %s is not being heard by any connectable Bluetooth "
                            "adapter or proxy; will keep retrying", self.address)
                        self._warned_missing = True
                    raise _NotSeen
                self._warned_missing = False
                self.disconnected.clear()
                client = await establish_connection(
                    BleakClientWithServiceCache, ble_device, self.address,
                    disconnected_callback=self._disconnected, max_attempts=3)
                self.client = client
                self.decoder = Decoder()
                self.write_char = client.services.get_characteristic(WRITE_UUID)
                notify_char = client.services.get_characteristic(NOTIFY_UUID)
                if not self.write_char or not notify_char:
                    await client.clear_cache()
                    raise RuntimeError("BrizLabs GATT characteristics are missing")
                await client.start_notify(notify_char, self.notification)
                self.available = True
                self.update()
                await self._initial_sync()
                stop_wait = asyncio.ensure_future(self.stop.wait())
                disc_wait = asyncio.ensure_future(self.disconnected.wait())
                try:
                    while True:
                        done, _ = await asyncio.wait({stop_wait, disc_wait}, timeout=self.poll_interval,
                                                     return_when=asyncio.FIRST_COMPLETED)
                        if done:
                            break
                        if self.get_variant is not None:
                            await self.get()  # periodic resync: picks up app / remote changes
                finally:
                    stop_wait.cancel()
                    disc_wait.cancel()
            except asyncio.CancelledError:
                raise
            except _NotSeen:
                pass
            except Exception as exc:
                _LOGGER.warning("BrizLabs %s connection: %s", self.address, exc,
                                exc_info=_LOGGER.isEnabledFor(logging.DEBUG))
            finally:
                self.available = False
                self.client = None
                self.write_char = None
                self.update()
                if client and client.is_connected:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
            if not self.stop.is_set():
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass

    async def _write(self, message: dict):
        if not self.client or not self.client.is_connected:
            raise ConnectionError(f"BrizLabs {self.address} is disconnected")
        async with self.lock:
            for packet in encode(message):
                await self.client.write_gatt_char(self.write_char, packet, response=True)
                await asyncio.sleep(0.03)

    async def send(self, properties=None):
        if properties is None:
            await self.get()
            return
        await self._write({"ts": int(time.time()), "data": properties,
                           "type": "thing.property.set", "msgId": uuid.uuid4().hex[:16]})
        # The device does not answer state requests reliably, so track what we set.
        changed = False
        for key, value in properties.items():
            if self.values.get(key) != value:
                self.values[key] = value
                changed = True
        if changed:
            self.update()

    async def get(self, variant: int | None = None):
        """Ask for the light's state using a request format (see GET_VARIANTS)."""
        index = self.get_variant if variant is None else variant
        message = {"ts": int(time.time()), "type": "thing.property.get",
                   "msgId": uuid.uuid4().hex[:16]}
        data = GET_VARIANTS[index or 0]
        if data is not _NO_DATA:
            message["data"] = data
        await self._write(message)

    async def _initial_sync(self, wait=3.0):
        """Find a state-request format the light answers.

        The RGB string acknowledges a bare get without sending its state, so
        try the known formats once each and remember the first that works.
        """
        order = [self.get_variant] if self.get_variant is not None else []
        order += [i for i in range(len(GET_VARIANTS)) if i not in order]
        for index in order:
            self.report_event.clear()
            await self.get(index)
            try:
                await asyncio.wait_for(self.report_event.wait(), timeout=wait)
            except asyncio.TimeoutError:
                _LOGGER.debug("BrizLabs %s: no state reply to get format #%d", self.address, index)
                continue
            if self.get_variant != index:
                _LOGGER.info("BrizLabs %s answers state requests in format #%d", self.address, index)
            self.get_variant = index
            return True
        self.get_variant = None
        _LOGGER.info("BrizLabs %s does not answer state requests; using the last known state "
                     "and the changes it reports", self.address)
        return False


async def async_setup_entry(hass, entry):
    from .const import MODEL_RGB, entry_model
    poll = RGB_POLL_SECONDS if entry_model(entry) == MODEL_RGB else None
    device = BrizlabsDevice(hass, entry.data["address"], poll_interval=poll)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = device
    device.task = hass.async_create_background_task(device.run(), f"brizlabs_{entry.entry_id}")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if hasattr(entry, "add_update_listener"):
        entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass, entry):
    """Model changed in the options flow: rebuild the entities for it."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    device = hass.data[DOMAIN].pop(entry.entry_id)
    device.stop.set()
    if device.task:
        await device.task
    return ok
