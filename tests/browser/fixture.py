"""Synthetic nodes for browser verification; never starts real proxies."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'web'))
from ports import PortManager, PORT_KEYS, TAGS
from server import create_app, make_server
from settings import Settings


def main():
    with tempfile.TemporaryDirectory(prefix='singdock-ui-') as directory:
        root = Path(directory)
        types = ['vless', 'vless', 'trojan', 'hysteria2', 'vmess',
                 'hysteria2', 'shadowsocks', 'shadowsocks', 'tuic', 'anytls']
        config = {'inbounds': [{'tag': tag, 'type': kind, 'listen_port': 30000 + i}
                               for i, (tag, kind) in enumerate(zip(TAGS, types))]}
        (root / 'config.json').write_text(json.dumps(config))
        (root / 'ports.env').write_text(''.join(f'{key}={30000 + i}\n' for i, key in enumerate(PORT_KEYS.values())))
        settings = Settings.from_env({**os.environ, 'GUI_PASSWORD': 'synthetic-browser-password', 'GUI_PORT': '18101'})
        manager = PortManager(root, (18101, 40000), run=lambda _: None)
        def links():
            port = next(node['port'] for node in manager.snapshot()['nodes'] if node['tag'] == 'ss')
            return f'ss://synthetic-test-credential@example.invalid:{port}#ss'
        server = make_server(create_app(settings, manager, links), '127.0.0.1', 18101)
        with patch('ports.probe'):
            print('Synthetic browser fixture ready on 127.0.0.1:18101', flush=True)
            server.run()


if __name__ == '__main__':
    main()
