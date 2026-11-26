"""BrizLabs sensitivity and pixel count controls."""

from homeassistant.components.number import NumberEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo

from . import scenes
from ..const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    device = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BrizlabsNumber(device, entry, "sensitivity", 0, 100),
                        BrizlabsNumber(device, entry, "lightpixel_number_set", 1, 200),
                        BrizlabsSceneSpeed(device, entry)])


class BrizlabsNumber(NumberEntity):
    _attr_has_entity_name = True
    _attr_native_step = 1

    def __init__(self, device, entry, key, minimum, maximum):
        self.device = device
        self.key = key
        self._attr_name = "Music sensitivity" if key == "sensitivity" else "Pixel count"
        self._attr_unique_id = f"{device.address}_{key}"
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device.address)})

    async def async_added_to_hass(self):
        self.async_on_remove(self.device.subscribe(self._changed))

    @callback
    def _changed(self):
        self.async_write_ha_state()

    @property
    def available(self):
        return self.device.available and self.key in self.device.values

    @property
    def native_value(self):
        return self.device.values.get(self.key)

    async def async_set_native_value(self, value):
        await self.device.send({self.key: int(value)})


class BrizlabsSceneSpeed(NumberEntity):
    """Speed byte (header byte 3) of the active scene payload."""

    _attr_has_entity_name = True
    _attr_name = "Scene speed"
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_native_max_value = scenes.MAX_SPEED

    def __init__(self, device, entry):
        self.device = device
        self._attr_unique_id = f"{device.address}_scene_speed"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device.address)})

    async def async_added_to_hass(self):
        self.async_on_remove(self.device.subscribe(self._changed))

    @callback
    def _changed(self):
        self.async_write_ha_state()

    def _payload(self):
        if self.device.values.get("work_mode") != "scene":
            return None
        payload = self.device.values.get("dreamlight_scene_mode")
        try:
            scenes.decode_scene(payload)
        except (ValueError, TypeError):
            return None
        return payload

    @property
    def available(self):
        return self.device.available and self._payload() is not None

    @property
    def native_value(self):
        payload = self._payload()
        return None if payload is None else scenes.decode_scene(payload).speed

    async def async_set_native_value(self, value):
        payload = self._payload()
        if payload is None:
            raise HomeAssistantError("Speed can only be changed while a scene is active")
        await self.device.send({"switch_led": True, "work_mode": "scene",
                                "dreamlight_scene_mode": scenes.with_speed(payload, int(value))})
