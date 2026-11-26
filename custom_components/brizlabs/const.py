DOMAIN = "brizlabs"
WRITE_UUID = "00002b11-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "00002b10-0000-1000-8000-00805f9b34fb"
SERVICE_UUID = "0000a101-0000-1000-8000-00805f9b34fb"
CONF_MODEL = "model"
MODEL_RGB = "rgb"
MODEL_CURTAIN = "curtain"
MODELS = {MODEL_RGB: "Micro String Lights RGB (colour wheel, schemes)",
          MODEL_CURTAIN: "Curtain / C1-C2 scene lights (scene_select)"}


def entry_model(entry) -> str:
    """Model of a config entry; entries created before 0.6 are curtain lights."""
    options = getattr(entry, "options", None) or {}
    data = getattr(entry, "data", None) or {}
    return options.get(CONF_MODEL) or data.get(CONF_MODEL) or MODEL_CURTAIN
FLOW_SCENE = "00010232000003e803e800000000"
