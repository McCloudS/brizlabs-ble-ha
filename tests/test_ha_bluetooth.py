"""Connection goes through Home Assistant's Bluetooth stack (adapters and proxies)."""

import asyncio
import json
from types import SimpleNamespace

import custom_components.brizlabs as integ
from custom_components.brizlabs.protocol import Decoder, encode
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

    reply = {"switch_led": True, "work_mode": "colour"}

    async def write_gatt_char(self, char, data, response=True):
        self.writes.append(bytes(data))
        msg = Decoder().feed(bytes(data))
        if msg and msg.get("type") == "thing.property.get" and self.reply is not None and self.notify:
            for packet in encode({"type": "thing.property.get.response", "data": self.reply}):
                self.notify(None, packet)

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


async def test_startup_reads_real_state_from_light(monkeypatch):
    calls = patch(monkeypatch, SimpleNamespace(address=ADDR, name="RY"))
    FakeClient.reply = {"switch_led": True, "work_mode": "colour"}
    device = integ.BrizlabsDevice(SimpleNamespace(), ADDR)
    task = asyncio.ensure_future(device.run())
    await wait_for(lambda: device.values.get("switch_led") is True)
    assert device.values["work_mode"] == "colour" and device.last_report is not None
    device.stop.set()
    await asyncio.wait_for(task, 2)


def test_property_value_shapes():
    pv = integ._property_values
    assert pv({"switch_led": True}) == {"switch_led": True}
    assert pv({"switch_led": {"value": False}, "ack": {}}) == {"switch_led": False}
    assert pv([{"key": "bright_value", "value": 40}, {"code": "work_mode", "value": "scene"}]) == \
        {"bright_value": 40, "work_mode": "scene"}
    assert pv("junk") is None


def test_report_types_accepted():
    device = integ.BrizlabsDevice(SimpleNamespace(), ADDR)
    for kind, ok in (("thing.property.report", True), ("thing.property.get.response", True),
                     ("thing.property.post", True), ("thing.property.set", False), ("other", True)):
        device.values = {}
        for packet in encode({"type": kind, "data": {"switch_led": True}}):
            device.notification(None, packet)
        assert (device.values == {"switch_led": True}) is ok, kind


async def test_initial_sync_tries_formats_and_remembers_the_one_answered():
    device = integ.BrizlabsDevice(SimpleNamespace(), ADDR)
    asked = []

    async def get(variant=None):
        asked.append(variant)
        if variant == 2:
            device.report_event.set()  # light answers only the third format

    device.get = get
    assert await device._initial_sync(wait=0.02) is True
    assert asked == [0, 1, 2] and device.get_variant == 2
    asked.clear()
    assert await device._initial_sync(wait=0.02) is True
    assert asked == [2]  # known-good format is tried first next time


async def test_initial_sync_gives_up_and_stops_polling():
    device = integ.BrizlabsDevice(SimpleNamespace(), ADDR, poll_interval=0.01)
    asked = []

    async def get(variant=None):
        asked.append(variant)

    device.get = get
    assert await device._initial_sync(wait=0.01) is False
    assert asked == list(range(len(integ.GET_VARIANTS))) and device.get_variant is None


async def test_get_variant_payloads():
    device = integ.BrizlabsDevice(SimpleNamespace(), ADDR)
    sent = []

    async def write(message):
        sent.append(message)

    device._write = write
    for i in range(len(integ.GET_VARIANTS)):
        await device.get(i)
    assert [m.get("data", "absent") for m in sent][0] == []
    assert "switch_led" in sent[1]["data"] and sent[2]["data"]["switch_led"] is None
    assert "data" not in sent[3] and all(m["type"] == "thing.property.get" for m in sent)


async def test_periodic_resync_polls_while_connected(monkeypatch):
    calls = patch(monkeypatch, SimpleNamespace(address=ADDR, name="RY"))
    device = integ.BrizlabsDevice(SimpleNamespace(), ADDR, poll_interval=0.05)
    task = asyncio.ensure_future(device.run())
    await wait_for(lambda: device.available)
    client = calls["clients"][0]
    start = len(client.writes)
    await asyncio.sleep(0.2)
    assert len(client.writes) >= start + 2  # re-asked for state at least twice
    device.stop.set()
    await asyncio.wait_for(task, 2)


async def test_only_rgb_entries_poll(monkeypatch):
    from custom_components.brizlabs.const import CONF_MODEL, MODEL_CURTAIN, MODEL_RGB
    made = []

    class Rec:
        def __init__(self, hass, address, poll_interval=None):
            made.append(poll_interval)
            self.stop = asyncio.Event()
            self.task = None

        async def run(self):
            await self.stop.wait()

    monkeypatch.setattr(integ, "BrizlabsDevice", Rec)

    async def fwd(e, platforms):
        pass

    hass = SimpleNamespace(data={}, config_entries=SimpleNamespace(async_forward_entry_setups=fwd),
                           async_create_background_task=lambda coro, name: asyncio.ensure_future(coro))
    for i, model in enumerate((MODEL_RGB, MODEL_CURTAIN)):
        entry = SimpleNamespace(entry_id=f"e{i}", data={"address": ADDR, CONF_MODEL: model}, options={})
        await integ.async_setup_entry(hass, entry)
    assert made == [integ.RGB_POLL_SECONDS, None]
    for d in hass.data["brizlabs"].values():
        d.stop.set()


def test_unknown_report_layouts_are_found():
    device = integ.BrizlabsDevice(SimpleNamespace(), ADDR)
    layouts = [
        {"switch_led": True, "work_mode": "scene", "ts": 1},                      # flat, no type/data
        {"method": "report", "params": {"switch_led": True, "work_mode": "scene"}},
        {"msg": {"props": [{"code": "switch_led", "value": True}, {"code": "work_mode", "value": "scene"}]}},
    ]
    for layout in layouts:
        device.values = {}
        device.report_event.clear()
        for packet in encode(layout):
            device.notification(None, packet)
        assert device.values.get("switch_led") is True and device.values.get("work_mode") == "scene", layout
        assert device.report_event.is_set()
    device.values = {}
    for packet in encode({"ts": 1, "code": 0}):       # nothing recognisable: ignored
        device.notification(None, packet)
    assert device.values == {}
