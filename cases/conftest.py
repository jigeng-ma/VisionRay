import json
import os
from pathlib import Path
import pytest
from studio.devices import Adb
from studio.android import Android


@pytest.fixture
def context():
    return json.loads(Path(os.environ['GLASSES_RUN_CONTEXT']).read_text(encoding='utf-8'))


@pytest.fixture
def adb():
    return Adb()


@pytest.fixture
def android(context):
    adapter = Android(context)
    try:
        yield adapter.connect()
    finally:
        adapter.close()
