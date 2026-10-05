"""Validate and atomically persist port changes without altering node identities."""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile

TAGS = ['vless-reality', 'vless-grpcr', 'trojan-reality', 'hy2', 'vmess-ws',
        'hy2-obfs', 'ss2022', 'ss', 'tuic-v5', 'anytls']
KEYS = ['VLESSR', 'VLESS_GRPCR', 'TROJANR', 'HY2', 'VMESS_WS',
        'HY2_OBFS', 'SS2022', 'SS', 'TUIC', 'ANYTLS']
PORT_KEYS = dict(zip(TAGS, ['PORT_' + key for key in KEYS]))
PORT_KEYS.update({tag + '-warp': key + '_W' for tag, key in list(PORT_KEYS.items())})


def revision(raw):
    return hashlib.sha256(raw).hexdigest()


def networks(node):
    if node['type'] in ('hysteria2', 'tuic'):
        return ['UDP']
    return ['TCP', 'UDP'] if node['type'] == 'shadowsocks' else ['TCP']


def plan(config, changes, reserved=()):
    if not isinstance(changes, dict) or not changes:
        raise ValueError('请选择需要修改的节点')
    candidate = copy.deepcopy(config)
    nodes = {n['tag']: n for n in candidate['inbounds']}
    for tag, port in changes.items():
        if tag not in nodes or tag not in PORT_KEYS:
            raise ValueError('未知节点')
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('端口必须是 1024–65535 的整数')
        nodes[tag]['listen_port'] = port
    used = set(reserved)
    for node in candidate['inbounds']:
        port = node['listen_port']
        if port in used:
            raise ValueError(f'端口 {port} 重复或被管理界面/WARP 保留')
        used.add(port)
    return candidate


def probe(config, candidate):
    old = {n['tag']: n['listen_port'] for n in config['inbounds']}
    current = {n['listen_port'] for n in config['inbounds']}
    for node in candidate['inbounds']:
        port = node['listen_port']
        if port == old[node['tag']] or port in current:
            continue  # Current sing-box listeners will be released on restart.
        for network in networks(node):
            for family, address in ((socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')):
                with socket.socket(family, socket.SOCK_STREAM if network == 'TCP' else socket.SOCK_DGRAM) as sock:
                    if family == socket.AF_INET6:
                        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    try:
                        sock.bind((address, port))
                    except OSError as error:
                        if error.errno in (97, 99):  # IPv6 disabled on the host.
                            continue
                        raise ValueError(f'端口 {port}/{network} 已被占用') from error


def atomic(path, raw):
    fd, name = tempfile.mkstemp(prefix='.ports-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class PortManager:
    def __init__(self, root, reserved=(), run=None):
        self.root = Path(root)
        self.reserved = reserved
        self.run = run or self.command

    @staticmethod
    def command(args):
        result = subprocess.run(args, capture_output=True, timeout=45)
        if result.returncode:
            raise RuntimeError('配置检查或服务重启失败')

    def snapshot(self):
        with (self.root / '.manage.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            raw = (self.root / 'config.json').read_bytes()
            config = json.loads(raw)
            return {'revision': revision(raw), 'nodes': [
                {'tag': n['tag'], 'type': n['type'], 'port': n['listen_port'],
                 'network': '+'.join(networks(n)), 'warp': n['tag'].endswith('-warp')}
                for n in config['inbounds']]}

    def change(self, changes, expected, apply=False):
        with (self.root / '.manage.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            config_path, ports_path = self.root / 'config.json', self.root / 'ports.env'
            raw, ports_raw = config_path.read_bytes(), ports_path.read_bytes()
            if expected != revision(raw):
                raise ValueError('配置已变化，请刷新后重新预览')
            config = json.loads(raw)
            active_keys = {PORT_KEYS[n['tag']] for n in config['inbounds'] if n['tag'] in PORT_KEYS}
            dormant = [int(value) for key, value in
                       (line.split('=', 1) for line in ports_raw.decode().splitlines() if '=' in line)
                       if key in PORT_KEYS.values() and key not in active_keys]
            candidate = plan(config, changes, (*self.reserved, *dormant))
            probe(config, candidate)
            rows = [{'tag': n['tag'], 'before': n['listen_port'], 'after': changes[n['tag']]}
                    for n in config['inbounds'] if n['tag'] in changes and n['listen_port'] != changes[n['tag']]]
            if not apply or not rows:
                return {'changes': rows, 'applied': False}
            fd, name = tempfile.mkstemp(prefix='.candidate-', suffix='.json', dir=self.root)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(candidate, stream)
                self.run(['/usr/local/bin/sing-box', 'check', '-c', name])
                values = dict(line.split('=', 1) for line in ports_raw.decode().splitlines() if '=' in line)
                for tag, port in changes.items():
                    values[PORT_KEYS[tag]] = str(port)
                ports_new = ''.join(f'{key}={value}\n' for key, value in values.items()).encode()
                # Backups are private, fixed files; never sent through the HTTP API.
                atomic(self.root / 'config.json.bak', raw)
                atomic(self.root / 'ports.env.bak', ports_raw)
                try:
                    atomic(ports_path, ports_new)
                    atomic(config_path, Path(name).read_bytes())
                    self.run(['singdock', 'restart'])
                except Exception as error:
                    atomic(ports_path, ports_raw)
                    atomic(config_path, raw)
                    try:
                        self.run(['singdock', 'restart'])
                    except Exception:
                        raise RuntimeError('已恢复旧配置，但服务恢复失败，请检查容器日志') from error
                    raise RuntimeError('应用失败，已恢复旧配置和服务') from error
            finally:
                Path(name).unlink(missing_ok=True)
            return {'changes': rows, 'applied': True}
