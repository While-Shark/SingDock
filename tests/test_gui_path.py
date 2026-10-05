"""Auto-path lifecycle, untrusted file handling and startup log regressions."""
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
from settings import Settings
from gui_path import resolve_path
from server import create_app, main


class AutoPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {'GUI_PASSWORD': 'private-test-password-123456'}

    def settings(self, **values):
        return Settings.from_env({**self.env, **values}, self.root)

    def test_missing_empty_and_auto_reuse_persisted_random_path(self):
        path = self.settings().path
        self.assertRegex(path, r'^/panel-[0-9a-f]{32}$')
        self.assertEqual(path, self.settings(GUI_PATH='').path)
        self.assertEqual(path, self.settings(GUI_PATH='auto').path)
        self.assertEqual((self.root / 'gui-path').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / '.gui-path.lock').stat().st_mode & 0o777, 0o600)
        other = self.root / 'other'
        other.mkdir()
        self.assertNotEqual(path, Settings.from_env(self.env, other).path)

    def test_concurrent_creation_has_one_stable_result(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            paths = list(pool.map(lambda _: resolve_path(self.root), range(20)))
        self.assertEqual(len(set(paths)), 1)
        self.assertEqual((self.root / 'gui-path').read_text().strip(), paths[0])

    def test_custom_path_and_root_override_without_overwriting_saved_path(self):
        self.assertEqual(self.settings(GUI_PATH='/private/control/').path, '/private/control')
        self.assertFalse((self.root / 'gui-path').exists())
        auto = self.settings().path
        self.assertEqual(self.settings(GUI_PATH='/').path, '')
        self.assertEqual(self.settings().path, auto)

    def test_malformed_oversized_and_non_ascii_state_fail_closed(self):
        file = self.root / 'gui-path'
        for raw in (b'/known\n', b'$(touch /tmp/marker)', b'x' * 129, b'\xff'):
            with self.subTest(raw=raw):
                file.write_bytes(raw)
                with self.assertRaisesRegex(ValueError, 'Cannot safely'):
                    self.settings()
                self.assertEqual(file.read_bytes(), raw)

    def test_symlinks_hardlinks_and_fifos_are_rejected_without_changing_target(self):
        target = self.root / 'target'
        target.write_text('/panel-' + 'a' * 32 + '\n')
        target.chmod(0o644)
        for name in ('gui-path', '.gui-path.lock'):
            file = self.root / name
            # Prior cases may have created the ordinary lock.
            file.unlink(missing_ok=True)
            for kind in ('symlink', 'hardlink', 'fifo'):
                with self.subTest(name=name, kind=kind):
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

    def test_invalid_credentials_or_bind_do_not_create_path_or_leak_input(self):
        for values in ({'GUI_PASSWORD': 'short'}, {'GUI_BIND': '127.0.0.1\npassword'},
                       {'GUI_BIND': 'localhost'}, {'GUI_BIND': 'fe80::1%eth0'}):
            with self.subTest(values=values), self.assertRaises(ValueError) as error:
                self.settings(**values)
            self.assertNotIn(next(iter(values.values())), str(error.exception))
            self.assertFalse((self.root / 'gui-path').exists())

    def test_unknown_root_does_not_challenge_or_reveal_generated_path(self):
        settings = self.settings()
        client = create_app(settings).test_client()
        response = client.get('/')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(settings.path.encode(), response.data)
        self.assertNotIn('WWW-Authenticate', response.headers)
        self.assertEqual(client.get(settings.path + '/').status_code, 401)

    def test_logs_print_url_after_binding_and_never_password(self):
        settings = self.settings(GUI_BIND='::1')
        output = io.StringIO()
        server = Mock()
        with patch('server.Settings.from_env', return_value=settings), patch('server.make_server', return_value=server), redirect_stdout(output):
            main()
        self.assertIn(f'http://[::1]:18100{settings.path}/', output.getvalue())
        self.assertNotIn(settings.password, output.getvalue())
        server.run.assert_called_once()
        output = io.StringIO()
        with patch('server.Settings.from_env', return_value=settings), patch('server.make_server', side_effect=OSError('busy')), redirect_stdout(output), self.assertRaises(OSError):
            main()
        self.assertEqual(output.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
