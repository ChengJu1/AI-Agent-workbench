import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.errors import ServiceError
from app.platform.browser_runtime import browser_choice

class BrowserRuntimeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.path=Path(temp.name)
    @patch('app.platform.browser_runtime.installed_channel',return_value=True)
    def test_auto_prefers_installed_regular_chrome(self, installed):
        choice=browser_choice(self.path,'auto')
        self.assertEqual(choice['channel'],'chrome');self.assertTrue(choice['available'])
        self.assertEqual(choice['browser_name'],'Google Chrome')
    @patch('app.platform.browser_runtime.installed_channel',return_value=False)
    def test_auto_falls_back_to_bundled_without_installing_anything(self, installed):
        (self.path/'chromium-1').mkdir()
        choice=browser_choice(self.path,'auto')
        self.assertEqual(choice['channel'],'chromium');self.assertTrue(choice['available'])
    @patch('app.platform.browser_runtime.installed_channel',return_value=False)
    def test_explicit_missing_browser_is_not_silently_replaced(self, installed):
        (self.path/'chromium-1').mkdir()
        choice=browser_choice(self.path,'chrome')
        self.assertEqual(choice['channel'],'chrome');self.assertFalse(choice['available'])
    def test_invalid_channel_cannot_be_an_arbitrary_executable(self):
        with self.assertRaises(ServiceError):browser_choice(self.path,'/tmp/unknown-app')
