"""Connection goes through Home Assistant's Bluetooth stack (adapters and proxies)."""

import asyncio
import json
from types import SimpleNamespace

import custom_components.brizlabs as integ
from custom_components.brizlabs.const import NOTIFY_UUID, SERVICE_UUID, WRITE_UUID

ADDR = "44:4A:D6:0C:62:DD"


class FakeClient:
    def __init__(self, disconnected_callback):
        self.is_connected = True
        self.writes = []
        self.notify = None
        self._cb = disconnected_callback
        chars = {WRITE_UUID: object(), NOTIFY_UUID: object()}
        self.services = SimpleNamespace(get_characteristic=chars.get)

    async def start_notify(self, char, callback):
        self.notify = callback

    async def write_gatt_char(self, char, data, response=True):
        self.writes.append(bytes(data))

    async def disconnect(self):
        self.is_connected = False

    async def clear_cache(self):
        pass

    def drop(self):
        self.is_connected = False
        self._cb(self)


def patch(monkeypatch, ble_device):
    calls = {"connect": [], "clients": []}

    def lookup(hass, address, connectable=True):
        calls.setdefault("lookup", []).append((address, connectable))
        return ble_device

    async def establish(cls, device, name, disconnected_callback=None, max_attempts=None):
        calls["connect"].append((cls, device, name))
        client = FakeClient(disconnected_callback)
        calls["clients"].append(client)
        return client

    monkeypatch.setattr(integ.bluetooth, "async_ble_device_from_address", lookup)
    monkeypatch.setattr(integ, "establish_connection", establish)
    return calls


async def wait_for(predicate, timeout=2):
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met")


async def test_connects_via_ha_bluetooth_and_sends_get(monkeypatch):
    ble = SimpleNamespace(address=ADDR, name="RY")
    calls = patch(monkeypatch, ble)
    device = integ.BrizlabsDevice(SimpleNamespace(), ADDR)
    task = asyncio.ensure_future(device.run())
    await wait_for(lambda: device.available)
    assert calls["lookup"][0] == (ADDR, True)
    cls, dev, name = calls["connect"][0]
    assert cls is integ.BleakClientWithServiceCache and dev is ble and name == ADDR
    client = calls["clients"][0]
    assert client.notify == device.notification
    await wait_for(lambda: client.writes)
    device.stop.set()
    await asyncio.wait_for(task, 2)
    assert not device.available and not client.is_connected


async def test_disconnect_callback_marks_unavailable(monkeypatch):
    calls = patch(monkeypatch, SimpleNamespace(address=ADDR, name="RY"))
    device = integ.BrizlabsDevice(SimpleNamespace(), ADDR)
    task = asyncio.ensure_future(device.run())
    await wait_for(lambda: device.available)
    calls["clients"][0].drop()
    await wait_for(lambda: not device.available)
    device.stop.set()
    await asyncio.wait_for(task, 2)


async def test_not_heard_by_any_scanner_stays_unavailable(monkeypatch):
    calls = patch(monkeypatch, None)
    device = integ.BrizlabsDevice(SimpleNamespace(), ADDR)
    task = asyncio.ensure_future(device.run())
    await wait_for(lambda: calls.get("lookup"))
    assert not device.available and calls["connect"] == []
    device.stop.set()
    await asyncio.wait_for(task, 2)


def test_manifest_declares_bluetooth_matcher():
    manifest = json.load(open("custom_components/brizlabs/manifest.json"))
    assert "bluetooth_adapters" in manifest["dependencies"]
    assert manifest["bluetooth"] == [{"local_name": "RY", "service_uuid": SERVICE_UUID, "connectable": True}]


def test_discovery_filter():
    from custom_components.brizlabs.config_flow import _is_brizlabs
    assert _is_brizlabs(SimpleNamespace(name="RY", service_uuids=[SERVICE_UUID]))
    assert not _is_brizlabs(SimpleNamespace(name="RY", service_uuids=[]))
    assert not _is_brizlabs(SimpleNamespace(name="wyze_hub", service_uuids=[SERVICE_UUID]))
