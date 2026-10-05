"""Read persisted node settings as data, never as executable shell code."""
import os
from pathlib import Path
import re
import shlex
import stat
import sys

BASE = ['VLESSR', 'VLESS_GRPCR', 'TROJANR', 'HY2', 'VMESS_WS', 'HY2_OBFS', 'SS2022', 'SS', 'TUIC', 'ANYTLS']
ALLOWED = {
    'ports.env': {f'PORT_{name}{suffix}' for name in BASE for suffix in ('', '_W')},
    'env.conf': set('BIN_PATH ENABLE_VLESS_REALITY ENABLE_VLESS_GRPCR ENABLE_TROJAN_REALITY ENABLE_HYSTERIA2 ENABLE_VMESS_WS ENABLE_HY2_OBFS ENABLE_SS2022 ENABLE_SS ENABLE_TUIC ENABLE_ANYTLS ENABLE_WARP REALITY_SERVER REALITY_SERVER_PORT GRPC_SERVICE VMESS_WS_PATH'.split()),
    'creds.env': set('UUID HY2_PWD REALITY_PRIV REALITY_PUB REALITY_SID HY2_PWD2 HY2_OBFS_PWD SS2022_KEY SS_PWD TUIC_UUID TUIC_PWD ANYTLS_PWD RS_VR RS_GR RS_TR RS_VRW RS_GRW RS_TRW'.split()),
    'warp.env': set('WARP_PRIVATE_KEY WARP_PEER_PUBLIC_KEY WARP_ENDPOINT_HOST WARP_ENDPOINT_PORT WARP_ADDRESS_V4 WARP_ADDRESS_V6 WARP_RESERVED_1 WARP_RESERVED_2 WARP_RESERVED_3'.split()),
}


def read(path):
    path = Path(path)
    if path.name not in ALLOWED:
        raise ValueError('Unsupported settings file')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                raise ValueError('Unsupported settings file')
            raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError('Oversized settings file')
    except OSError as error:
        raise ValueError('Cannot safely open settings file') from error
    pairs = {}
    for line in raw.decode('utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'([A-Z][A-Z0-9_]*)=(.*)', line)
        if not match or match[1] not in ALLOWED[path.name] or match[1] in pairs:
            raise ValueError('Invalid or duplicate settings key')
        value = match[2]
        # Support existing quoted assignments without shell interpolation.
        if value.startswith(('"', "'")):
            parts = shlex.split(value, comments=False, posix=True)
            if len(parts) != 1:
                raise ValueError('Invalid quoted setting')
            value = parts[0]
        if '\x00' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Invalid setting value')
        if path.name == 'ports.env' and not re.fullmatch(r'[1-9][0-9]{3,4}', value):
            raise ValueError('Invalid node port')
        if path.name == 'env.conf' and match[1] == 'BIN_PATH':
            if value != '/usr/local/bin/sing-box':
                raise ValueError('Core executable cannot be overridden')
        pairs[match[1]] = value
    return pairs


if __name__ == '__main__':
    try:
        pairs = read(sys.argv[1])
        for key, value in pairs.items():
            os.write(1, key.encode() + b'\0' + value.encode() + b'\0')
    except (ValueError, OSError, IndexError):
        raise SystemExit('Invalid persisted node settings; refusing to load')
