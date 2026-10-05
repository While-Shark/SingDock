"""Synthetic nodes for browser verification; never starts real proxies."""
import json
import os
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'web'))
from ports import PortManager, PORT_KEYS, TAGS
from server import Handler


class FixtureHandler(Handler):
    def do_GET(self):
        if self.route() == '/api/links' and self.authorized():
            port = next(node['port'] for node in self.server.manager.snapshot()['nodes'] if node['tag'] == 'ss')
            return self.send(200, {'links': f'ss://synthetic-test-credential@example.invalid:{port}#ss'})
        super().do_GET()


def main():
    with tempfile.TemporaryDirectory(prefix='singdock-ui-') as directory:
        root = Path(directory)
        types = ['vless', 'vless', 'trojan', 'hysteria2', 'vmess',
                 'hysteria2', 'shadowsocks', 'shadowsocks', 'tuic', 'anytls']
        config = {'inbounds': [{'tag': tag, 'type': kind, 'listen_port': 30000 + i}
                               for i, (tag, kind) in enumerate(zip(TAGS, types))]}
        (root / 'config.json').write_text(json.dumps(config))
        (root / 'ports.env').write_text(''.join(f'{key}={30000 + i}\n' for i, key in enumerate(PORT_KEYS.values())))
        server = ThreadingHTTPServer(('127.0.0.1', 18101), FixtureHandler)
        server.username = os.environ.get('GUI_USERNAME', 'admin')
        server.gui_path = os.environ.get('GUI_PATH', '/').rstrip('/')
        server.password = 'synthetic-browser-password'
        # Probe/core/restart already have real container coverage in smoke.sh.
        # Here only the browser and production HTTP/transaction code are exercised.
        server.manager = PortManager(root, (18101, 40000), run=lambda _: None)
        with patch('ports.probe'):
            print('Synthetic browser fixture ready on 127.0.0.1:18101', flush=True)
            server.serve_forever()


if __name__ == '__main__':
    main()
