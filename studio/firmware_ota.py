"""G1/G3/G6 firmware OTA test preparation and result checks."""

from .errors import TestBlocked
from .ota import OtaClient


TEST_TASKS = (164, 165, 171, 155)


def prepare_target(task_id, config_path=None):
    """Ensure only the target test firmware is online before checking OTA UI."""
    client = OtaClient(config_path=config_path) if config_path else OtaClient()
    return client.activate_only(task_id, TEST_TASKS, apply=True)


def firmware_version(android):
    """Read the connected glasses firmware version on System Settings page."""
    from .home_device import HomeDevicePage
    page = HomeDevicePage(android)
    page.setting('System Settings')
    labels = [e for e in android.driver.find_elements('xpath',
              f"//*[@resource-id='{page.package}:id/tv_title' and @text='Firmware Version']") if e.is_displayed()]
    if len(labels) != 1:
        raise TestBlocked('系统设置页未唯一找到 Firmware Version。')
    values = [e.text.strip() for e in labels[0].find_element('xpath', '..').find_elements('xpath', './/*[@text]') if e.text.strip()]
    version = next((value for value in values if value != 'Firmware Version'), '')
    if not version:
        raise TestBlocked('无法读取当前眼镜固件版本。')
    return version
