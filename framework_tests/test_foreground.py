import unittest
from unittest.mock import Mock
from studio.android import Android

class ForegroundTests(unittest.TestCase):
    def adapter(self, current):
        a=Android({'config':{'package':'test.app'}});a.driver=Mock();a.driver.current_package=current
        a.popups=Mock();a.popups.handle.return_value=False
        return a

    def test_starts_target_from_launcher(self):
        a=self.adapter('launcher')
        a.driver.activate_app.side_effect=lambda package:setattr(a.driver,'current_package',package)
        a.ensure_foreground()
        a.driver.activate_app.assert_called_once_with('test.app')

    def test_preserves_app_already_in_foreground(self):
        a=self.adapter('test.app');a.ensure_foreground()
        a.driver.activate_app.assert_not_called()
