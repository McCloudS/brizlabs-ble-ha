from types import SimpleNamespace
from custom_components.brizlabs.rgb import scenes as S


class FakeDevice:
    def __init__(self, address="00:11:22:33:44:55", values=None, available=True):
        self.address = address
        self.values = dict(values or {})
        self.available = available
        self.sent = []
        self.listeners = set()
        self.stop = SimpleNamespace(set=lambda: None)
        self.task = None

    def subscribe(self, cb):
        self.listeners.add(cb)
        return lambda: self.listeners.discard(cb)

    def update(self):
        for cb in tuple(self.listeners):
            cb()

    async def send(self, properties=None):
        self.sent.append(properties)

    def report(self, **values):
        """Simulate a hardware report."""
        self.values.update(values)
        self.update()


def entry(title="Test Light", entry_id="e1", address="00:11:22:33:44:55"):
    return SimpleNamespace(title=title, entry_id=entry_id, data={"address": address, "model": "rgb"})


def scene_values(scene_id, index=0, **extra):
    return {"switch_led": True, "work_mode": "scene", "bright_value": 80,
            "dreamlight_scene_mode": S.CAPTURED_PALETTES[scene_id][index], **extra}
