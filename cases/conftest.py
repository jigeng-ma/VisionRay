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
def android(context, request):
    if reason := context.get('skip_case_nodes', {}).get(request.node.nodeid):
        pytest.skip(reason)
    adapter = Android(context)
    try:
        adapter.connect()
        from studio.preconditions import needs_business_preparation, prepare_business
        if needs_business_preparation(request.node.nodeid):
            prepare_business(adapter)
        yield adapter
    finally:
        try:
            multi_device_tests = {
                'test_reconnect_after_switch_and_restart',
                'test_g5_device_list', 'test_g5_switch_bound_device',
                'test_g5_pair_from_device_management',
                'test_g5_unbind_one_of_multiple_devices',
            }
            if (context['config'].get('model') == 'G5'
                    and request.node.originalname in multi_device_tests
                    and getattr(adapter, 'driver', None) is not None):
                from cases.g5.test_device_management import DeviceManagement
                DeviceManagement(adapter).keep_only_target()
        finally:
            adapter.close()
