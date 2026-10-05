import base64
import copy
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
from ports import PortManager, plan, revision
from server import Handler

CONFIG = {'inbounds': [
    {'tag': 'ss', 'type': 'shadowsocks', 'listen_port': 21001, 'password': 'secret'},
    {'tag': 'hy2', 'type': 'hysteria2', 'listen_port': 21002, 'users': [{'password': 'secret'}]}]}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = json.dumps(CONFIG).encode()
        (self.root / 'config.json').write_bytes(self.raw)
        self.ports = b'PORT_SS=21001\nPORT_HY2=21002\nPORT_ANYTLS_W=21003\n'
        (self.root / 'ports.env').write_bytes(self.ports)
        self.calls = []
        self.manager = PortManager(self.root, (18100, 40000), self.calls.append)
        self.probe = patch('ports.probe')
        self.probe.start()
        self.addCleanup(self.probe.stop)



class PortsTest(Fixture):
    def test_validation(self):
        for changes in ({'ss': True}, {'ss': '22001'}, {'ss': 65536}, {'ss': 1023},
                        {'ss': 21002}, {'ss': 40000}, {'unknown': 22001}, {}, []):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                plan(CONFIG, changes, (40000,))
        self.assertEqual(CONFIG['inbounds'][0]['listen_port'], 21001)

    def test_preview_does_not_write_or_restart(self):
        result = self.manager.change({'ss': 22001}, revision(self.raw))
        self.assertEqual(result['changes'][0]['after'], 22001)
        self.assertFalse(result['applied'])
        self.assertEqual((self.root / 'config.json').read_bytes(), self.raw)
        self.assertEqual((self.root / 'ports.env').read_bytes(), self.ports)
        self.assertEqual(self.calls, [])

    def test_apply_persists_ports_and_preserves_secrets(self):
        self.manager.change({'ss': 22001}, revision(self.raw), True)
        expected = copy.deepcopy(CONFIG)
        expected['inbounds'][0]['listen_port'] = 22001
        self.assertEqual(json.loads((self.root / 'config.json').read_bytes()), expected)
        self.assertIn(b'PORT_SS=22001', (self.root / 'ports.env').read_bytes())
        self.assertIn(b'PORT_ANYTLS_W=21003', (self.root / 'ports.env').read_bytes())
        self.assertEqual(self.calls[-1], ['singdock', 'restart'])
        self.assertEqual((self.root / 'config.json').stat().st_mode & 0o777, 0o600)

    def test_stale_preview_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.change({'ss': 22001}, 'stale', True)
        self.assertEqual(self.calls, [])

    def test_disabled_warp_port_stays_reserved(self):
        with self.assertRaises(ValueError):
            self.manager.change({'ss': 21003}, revision(self.raw), True)
        self.assertEqual(self.calls, [])

    def test_port_swap(self):
        self.manager.change({'ss': 21002, 'hy2': 21001}, revision(self.raw), True)
        self.assertIn(b'PORT_HY2=21001', (self.root / 'ports.env').read_bytes())

    def test_failed_check_never_writes(self):
        def fail(_):
            raise RuntimeError('invalid config')
        self.manager.run = fail
        with self.assertRaises(RuntimeError):
            self.manager.change({'ss': 22001}, revision(self.raw), True)
        self.assertEqual((self.root / 'config.json').read_bytes(), self.raw)
        self.assertEqual((self.root / 'ports.env').read_bytes(), self.ports)

    def test_failed_restart_rolls_back_both_files(self):
        def run(args):
            self.calls.append(args)
            if len(self.calls) == 2:
                raise RuntimeError('restart failed')
        self.manager.run = run
        with self.assertRaisesRegex(RuntimeError, '已恢复旧配置和服务'):
            self.manager.change({'ss': 22001}, revision(self.raw), True)
        self.assertEqual((self.root / 'config.json').read_bytes(), self.raw)
        self.assertEqual((self.root / 'ports.env').read_bytes(), self.ports)
        self.assertEqual(len(self.calls), 3)

    def test_snapshot_has_no_credentials(self):
        self.assertNotIn('secret', json.dumps(self.manager.snapshot()))

    def test_occupied_port_rejected(self):
        self.probe.stop()
        with socket.socket() as listener:
            listener.bind(('0.0.0.0', 0))
            port = listener.getsockname()[1]
            if port in (21001, 21002, 40000):
                self.skipTest('OS assigned a fixture port')
            with self.assertRaises(ValueError):
                self.manager.change({'ss': port}, revision(self.raw))


class HttpTest(Fixture):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.manager = self.manager
        self.server.password = 'test-password-123456'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.auth = 'Basic ' + base64.b64encode(b'admin:test-password-123456').decode()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, body=None, auth=True, csrf=True):
        headers = {'Authorization': self.auth} if auth else {}
        if body is not None:
            headers['Content-Type'] = 'application/json'
            if csrf:
                headers['X-SingDock-Request'] = '1'
        request = Request(self.url + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        return urlopen(request, timeout=5)

    def test_authentication_required_for_assets_and_api(self):
        for path in ('/', '/api/nodes', '/api/links', '/app.js'):
            with self.assertRaises(HTTPError) as result:
                self.request(path, auth=False)
            self.assertEqual(result.exception.code, 401)

    def test_cross_site_write_rejected(self):
        with self.assertRaises(HTTPError) as result:
            self.request('/api/apply', {'ports': {'ss': 22001}, 'revision': revision(self.raw)}, csrf=False)
        self.assertEqual(result.exception.code, 403)
        self.assertEqual(self.calls, [])

    def test_http_preview_then_apply(self):
        body = {'ports': {'ss': 22001}, 'revision': revision(self.raw)}
        with self.request('/api/preview', body) as response:
            self.assertFalse(json.load(response)['applied'])
        with self.request('/api/apply', body) as response:
            self.assertTrue(json.load(response)['applied'])
        with self.request('/api/nodes') as response:
            self.assertEqual(json.load(response)['nodes'][0]['port'], 22001)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_arbitrary_files_are_not_served(self):
        with self.assertRaises(HTTPError) as result:
            self.request('/../ports.env')
        self.assertEqual(result.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
