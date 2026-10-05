"""Regression tests for executable configuration, throttling and request limits."""
import importlib.util
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
from http_security import LoginLimiter
import test_gui

reader_path = Path(__file__).resolve().parents[1] / 'docker/read_env.py'
spec = importlib.util.spec_from_file_location('read_env', reader_path)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class PersistedSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_command_substitution_and_backticks_are_literal(self):
        marker = self.root / 'executed'
        file = self.root / 'env.conf'
        value = f'$(touch {marker});`touch {marker}`'
        file.write_text(f'GRPC_SERVICE={value}\n')
        self.assertEqual(reader.read(file)['GRPC_SERVICE'], value)
        result = subprocess.run([sys.executable, str(reader_path), str(file)], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn(value.encode(), result.stdout)
        self.assertFalse(marker.exists())

    def test_bash_adapter_loads_payload_as_literal_data(self):
        file = self.root / 'env.conf'
        marker = self.root / 'executed'
        value = f'$(touch {marker});`touch {marker}`'
        file.write_text(f'GRPC_SERVICE={value}\n')
        source = (reader_path.parent / 'manage.sh').read_text()
        definition = 'safe_source_env() {' + source.split('safe_source_env() {', 1)[1].split('\n}', 1)[0] + '\n}'
        definition = definition.replace('/opt/singdock/docker/read_env.py', str(reader_path)).replace('/run/singdock', str(self.root))
        script = 'set -euo pipefail\ndie() { exit 1; }\n' + definition + '\nsafe_source_env "$1"\n[[ "$GRPC_SERVICE" == "$2" ]]'
        result = subprocess.run(['bash', '-c', script, 'test', str(file), value], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(marker.exists())

    def test_unknown_keys_core_override_and_duplicate_keys_rejected(self):
        file = self.root / 'env.conf'
        for content in ('PATH=/tmp/evil\n', 'BASH_ENV=/tmp/evil\n', 'BIN_PATH=/tmp/evil\n',
                        'GRPC_SERVICE=a\nGRPC_SERVICE=b\n', 'touch /tmp/evil\n'):
            with self.subTest(content=content):
                file.write_text(content)
                with self.assertRaises(ValueError):
                    reader.read(file)

    def test_supported_quotes_base64_and_empty_values(self):
        file = self.root / 'creds.env'
        file.write_text('HY2_PWD="a+b/c=="\nANYTLS_PWD=\n')
        self.assertEqual(reader.read(file), {'HY2_PWD': 'a+b/c==', 'ANYTLS_PWD': ''})

    def test_symlink_and_oversized_settings_rejected(self):
        target = self.root / 'target'
        target.write_text('PORT_SS=20000\n')
        file = self.root / 'ports.env'
        file.symlink_to(target)
        with self.assertRaises(ValueError):
            reader.read(file)
        file.unlink()
        file.write_bytes(b'x' * 65537)
        with self.assertRaises(ValueError):
            reader.read(file)

    def test_port_arithmetic_payload_rejected(self):
        file = self.root / 'ports.env'
        file.write_text('PORT_SS=x[$(touch /tmp/should-not-run)]\n')
        with self.assertRaises(ValueError):
            reader.read(file)

    def test_adapter_does_not_use_data_volume_executables_or_source_settings(self):
        adapter = (reader_path.parent / 'manage.sh').read_text()
        self.assertIn('export SBP_BIN_DIR=/opt/singdock/bootstrap-bin', adapter)
        override = adapter.split('safe_source_env() {', 1)[1].split('\n}', 1)[0]
        self.assertNotIn('source ', override)
        self.assertIn('read_env.py', override)
        self.assertIn('printf -v "$key"', override)


class LimiterTest(unittest.TestCase):
    def test_failure_threshold_and_expiry(self):
        now = [0]
        limiter = LoginLimiter(clock=lambda: now[0])
        for _ in range(10):
            self.assertEqual(limiter.authenticate('peer', False), 401)
        self.assertEqual(limiter.authenticate('peer', True), 429)
        self.assertEqual(limiter.authenticate('other', True), 200)
        now[0] = 61
        self.assertEqual(limiter.authenticate('peer', True), 200)

    def test_success_does_not_reset_global_failure_budget(self):
        limiter = LoginLimiter(clock=lambda: 0)
        for i in range(100):
            self.assertEqual(limiter.authenticate(str(i), False), 401)
            if i < 99:
                self.assertEqual(limiter.authenticate('valid', True), 200)
        self.assertEqual(limiter.authenticate('next', False), 429)
        self.assertLessEqual(len(limiter.failures), 100)



class HttpSecurityTest(test_gui.HttpTest):
    def test_failed_auth_is_limited_and_has_retry_header(self):
        from urllib.error import HTTPError
        for _ in range(10):
            with self.assertRaises(HTTPError) as error:
                self.request('/api/nodes', auth=False)
            self.assertEqual(error.exception.code, 401)
        with self.assertRaises(HTTPError) as error:
            self.request('/api/nodes', auth=False)
        self.assertEqual(error.exception.code, 429)
        self.assertEqual(error.exception.headers['Retry-After'], '60')

    def raw_request(self, headers, body):
        with socket.create_connection(('127.0.0.1', self.server.effective_port), timeout=5) as conn:
            data = (f'POST /api/apply HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nAuthorization: {self.auth}\r\n'
                    f'Content-Type: application/json\r\nX-SingDock-Request: 1\r\n{headers}\r\n\r\n').encode() + body
            conn.sendall(data)
            return conn.recv(4096)

    def test_conflicting_lengths_and_unsupported_transfer_encoding_rejected(self):
        for headers, status in [('Content-Length: 2\r\nContent-Length: 3', b' 400 '),
                                ('Content-Length: 2\r\nTransfer-Encoding: gzip', b' 501 ')]:
            with self.subTest(headers=headers):
                self.assertIn(status, self.raw_request(headers, b'{}').split(b'\r\n')[0])
        self.assertEqual(self.calls, [])

    def test_chunked_body_is_normalized_even_with_mismatched_length(self):
        import json
        from ports import revision
        body = json.dumps({'ports': {'ss': 22001}, 'revision': revision(self.raw)}).encode()
        chunked = f'{len(body):x}\r\n'.encode() + body + b'\r\n0\r\n\r\n'
        response = self.raw_request('Content-Length: 999\r\nTransfer-Encoding: chunked', chunked)
        self.assertIn(b' 200 ', response.split(b'\r\n')[0])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.manager.snapshot()['nodes'][0]['port'], 22001)

    def test_oversized_body_rejected_before_mutation(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as error:
            self.request('/api/apply', {'padding': 'x' * 16384})
        self.assertEqual(error.exception.code, 413)
        self.assertEqual(self.calls, [])

    def test_invalid_json_and_internal_errors_do_not_expose_details(self):
        from server import create_app
        client = create_app(self.settings, self.manager).test_client()
        headers = {'Authorization': self.auth, 'X-SingDock-Request': '1', 'Content-Type': 'application/json'}
        for body in (b'\xff', b'{', b'[]'):
            self.assertEqual(client.post('/api/apply', data=body, headers=headers).status_code, 400)
        from unittest.mock import patch
        with patch.object(self.manager, 'snapshot', side_effect=Exception('secret-internal-path')):
            response = client.get('/api/nodes', headers=headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'secret-internal-path', response.data)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')


if __name__ == '__main__':
    unittest.main()
