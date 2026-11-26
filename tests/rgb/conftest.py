import json
from pathlib import Path
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "scene-capture.json"


@pytest.fixture(scope="session")
def capture():
    return json.loads(FIXTURE.read_text())


ORDERED = Path(__file__).parent / "fixtures" / "ordered-presets-capture.json"


@pytest.fixture(scope="session")
def ordered():
    return json.loads(ORDERED.read_text())
