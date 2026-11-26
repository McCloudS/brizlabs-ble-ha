"""Scene palette and music mode selectors."""

from homeassistant.components.select import SelectEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo

from . import scenes
from ..const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    device = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BrizlabsScenePaletteSelect(device, entry), BrizlabsMusicSelect(device, entry),
                        BrizlabsSceneDirectionSelect(device, entry)])


class _BrizlabsSelect(SelectEntity):
    _attr_has_entity_name = True

    def __init__(self, device, entry, key, name):
        self.device = device
        self._attr_name = name
        self._attr_unique_id = f"{device.address}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device.address)})

    async def async_added_to_hass(self):
        self.async_on_remove(self.device.subscribe(self._changed))

    @callback
    def _changed(self):
        self.async_write_ha_state()


class BrizlabsScenePaletteSelect(_BrizlabsSelect):
    """Colour palette of the active scene (captured app palettes + Custom)."""

    def __init__(self, device, entry):
        super().__init__(device, entry, "scene_palette", "Scene palette")

    def _payload(self):
        values = self.device.values
        if values.get("work_mode") != "scene":
            return None
        payload = values.get("dreamlight_scene_mode")
        try:
            scenes.decode_scene(payload)
        except (ValueError, TypeError):
            return None
        return payload

    @property
    def available(self):
        return self.device.available and self._payload() is not None

    @property
    def options(self):
        payload = self._payload()
        if payload is None:
            # Never empty: HomeKit and some cards fail on a select with no options.
            return [label for label, _ in scenes.PRESET_PALETTES]
        options = scenes.palette_options(scenes.decode_scene(payload).scene_id)
        current = scenes.palette_label(payload)
        return options + [current] if current not in options else options

    @property
    def current_option(self):
        payload = self._payload()
        return None if payload is None else scenes.palette_label(payload)

    async def async_select_option(self, option):
        payload = self._payload()
        if payload is None:
            raise HomeAssistantError("Palette can only be changed while a scene is active")
        if option == scenes.palette_label(payload):
            return  # already active (includes the read-only "Custom: ..." entry)
        try:
            new = scenes.apply_palette(payload, option)
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self.device.send({"switch_led": True, "work_mode": "scene", "dreamlight_scene_mode": new})


class BrizlabsSceneDirectionSelect(_BrizlabsSelect):
    """Direction (header byte 0: Left=1, Right=0) of the active scene."""

    _attr_options = scenes.DIRECTION_OPTIONS

    def __init__(self, device, entry):
        super().__init__(device, entry, "scene_direction", "Scene direction")

    _payload = BrizlabsScenePaletteSelect._payload

    @property
    def available(self):
        return self.device.available and self._payload() is not None

    @property
    def current_option(self):
        payload = self._payload()
        return None if payload is None else scenes.direction_label(payload)

    async def async_select_option(self, option):
        payload = self._payload()
        if payload is None:
            raise HomeAssistantError("Direction can only be changed while a scene is active")
        try:
            new = scenes.with_direction(payload, option)
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self.device.send({"switch_led": True, "work_mode": "scene", "dreamlight_scene_mode": new})


class BrizlabsMusicSelect(_BrizlabsSelect):
    _attr_options = scenes.MUSIC_OPTIONS

    def __init__(self, device, entry):
        super().__init__(device, entry, "music_mode", "Music mode")

    @property
    def available(self):
        return self.device.available

    @property
    def current_option(self):
        if self.device.values.get("work_mode") != "music":
            return None
        return scenes.effect_for_values(self.device.values)

    async def async_select_option(self, option):
        try:
            music = scenes.music_id_for_name(option)
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self.device.send({"switch_led": True, "work_mode": "music", "device_music": music})
