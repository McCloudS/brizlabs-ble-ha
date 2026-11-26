import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)

from .const import DOMAIN, SERVICE_UUID

DEFAULT_NAME = "BrizLabs Micro String Lights"
MANUAL = "manual"


def _is_brizlabs(info: BluetoothServiceInfoBleak) -> bool:
    return info.name == "RY" and SERVICE_UUID in info.service_uuids


class BrizlabsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._discovered: dict[str, str] = {}
        self._address: str | None = None

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak):
        """Handle a light found by a local adapter or Bluetooth proxy."""
        address = discovery_info.address.upper()
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        self._address = address
        self.context["title_placeholders"] = {"name": f"{DEFAULT_NAME} ({address})"}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title=user_input["name"], data={"address": self._address})
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({vol.Required("name", default=DEFAULT_NAME): str}),
            description_placeholders={"address": self._address},
        )

    async def async_step_user(self, user_input=None):
        """Pick a discovered light, or fall back to typing a MAC address."""
        if user_input is not None:
            if user_input["address"] == MANUAL:
                return await self.async_step_manual()
            address = user_input["address"]
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input["name"], data={"address": address})

        configured = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            address = info.address.upper()
            if address not in configured and _is_brizlabs(info):
                self._discovered[address] = f"{info.name} ({address})"
        if not self._discovered:
            return await self.async_step_manual()
        choices = {**self._discovered, MANUAL: "Enter address manually"}
        schema = vol.Schema({
            vol.Required("address"): vol.In(choices),
            vol.Required("name", default=DEFAULT_NAME): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_manual(self, user_input=None):
        errors = {}
        if user_input is not None:
            address = user_input["address"].strip().upper().replace("-", ":")
            if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
                errors["address"] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input["name"], data={"address": address})
        schema = vol.Schema({vol.Required("address"): str, vol.Required("name", default=DEFAULT_NAME): str})
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)
