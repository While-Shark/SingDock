"""Auto-password persistence, authentication, private state and local discovery."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
from gui_password import GROUPS, resolve_password, valid_generated
from settings import Settings
from server import create_app, main as server_main
from gui_info import main as info_main


class AutoPasswordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {'GUI_PATH': '/', 'ENABLE_GUI': 'true'}

    def settings(self, **values):
        return Settings.from_env({**self.env, **values}, self.root)

    def test_missing_and_empty_password_generate_and_reuse_complex_value(self):
        settings = self.settings()
        self.assertEqual(len(settings.password), 32)
        for group in GROUPS:
            self.assertTrue(any(c in group for c in settings.password))
        self.assertEqual(self.settings(GUI_PASSWORD='').password, settings.password)
        self.assertEqual((self.root / 'gui-password').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / '.gui-password.lock').stat().st_mode & 0o777, 0o600)
        other = self.root / 'other'
        other.mkdir()
        self.assertNotEqual(Settings.from_env(self.env, other).password, settings.password)

    def test_concurrent_creation_keeps_one_value(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            passwords = list(pool.map(lambda _: resolve_password(self.root), range(20)))
        self.assertEqual(len(set(passwords)), 1)
        self.assertTrue(valid_generated(passwords[0]))

    def test_explicit_override_and_return_to_auto_preserve_saved_password(self):
        manual = 'custom:password-123456'
        self.assertEqual(self.settings(GUI_PASSWORD=manual).password, manual)
        self.assertFalse((self.root / 'gui-password').exists())
        saved = self.settings().password
        self.assertEqual(self.settings(GUI_PASSWORD=manual).password, manual)
        self.assertEqual(self.settings().password, saved)
        with self.assertRaises(ValueError):
            self.settings(GUI_PASSWORD='short')
        self.assertEqual(self.settings().password, saved)

    def test_unsafe_state_is_rejected_without_exposing_or_replacing_content(self):
        file = self.root / 'gui-password'
        for raw in (b'short', b'A' * 32, b'x' * 129, b'\xff', b'aA1!' * 8 + b'\n\n'):
            file.write_bytes(raw)
            with self.assertRaises(ValueError) as error:
                self.settings()
            self.assertNotIn(repr(raw), str(error.exception))
            self.assertEqual(file.read_bytes(), raw)

    def test_links_and_fifos_are_rejected_without_changing_target(self):
        target = self.root / 'target'
        target.write_text('aA1!' * 8 + '\n')
        target.chmod(0o644)
        for name in ('gui-password', '.gui-password.lock'):
            file = self.root / name
            file.unlink(missing_ok=True)
            for kind in ('symlink', 'hardlink', 'fifo'):
                if kind == 'symlink':
                    file.symlink_to(target)
                elif kind == 'hardlink':
                    os.link(target, file)
                else:
                    os.mkfifo(file)
                with self.assertRaises(ValueError):
                    self.settings()
                file.unlink()
                self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_readonly_discovery_never_creates_missing_state(self):
        with self.assertRaises(ValueError):
            Settings.from_env(self.env, self.root, create_state=False)
        self.assertEqual(list(self.root.iterdir()), [])
        saved = self.settings()
        self.assertEqual(Settings.from_env(self.env, self.root, create_state=False), saved)
        (self.root / 'gui-password').unlink()
        with self.assertRaises(ValueError):
            Settings.from_env(self.env, self.root, create_state=False)
        self.assertFalse((self.root / 'gui-password').exists())

    def test_generated_password_authenticates_without_api_or_log_leak(self):
        settings = self.settings()
        manager = Mock()
        manager.snapshot.return_value = {'nodes': [], 'revision': 'test'}
        client = create_app(settings, manager).test_client()
        auth = 'Basic ' + base64.b64encode((settings.username + ':' + settings.password).encode()).decode()
        self.assertEqual(client.get('/api/nodes').status_code, 401)
        response = client.get('/api/nodes', headers={'Authorization': auth})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(settings.password.encode(), response.data)
        output = io.StringIO()
        with patch('server.Settings.from_env', return_value=settings), patch('server.make_server'), redirect_stdout(output):
            server_main()
        self.assertNotIn(settings.password, output.getvalue())
        self.assertIn('singdock gui-info', output.getvalue())

    def test_explicit_local_command_shows_details_and_disabled_gui_rejects(self):
        settings = self.settings()
        output = io.StringIO()
        source = Mock()
        source.from_env.return_value = settings
        with patch.dict(os.environ, {'ENABLE_GUI': 'true'}), patch('gui_info.Settings', source), redirect_stdout(output):
            info_main()
        self.assertIn('用户名: admin', output.getvalue())
        self.assertIn('密码: ' + settings.password, output.getvalue())
        source.from_env.assert_called_once_with(create_state=False)
        output = io.StringIO()
        with patch.dict(os.environ, {'ENABLE_GUI': 'false'}), redirect_stdout(output), self.assertRaises(SystemExit):
            info_main()
        self.assertEqual(output.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
