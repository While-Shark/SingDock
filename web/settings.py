"""GUI settings shared by startup validation and the HTTP server."""
from dataclasses import dataclass
import os
import re


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    path: str
    port: int
    bind: str

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        username = env.get('GUI_USERNAME', 'admin')
        password = env.get('GUI_PASSWORD', '')
        if not 1 <= len(username) <= 64 or username != username.strip() or ':' in username or any(ord(c) < 32 or ord(c) == 127 for c in username):
            raise ValueError('GUI_USERNAME must be 1–64 characters, without colon, control characters or surrounding spaces')
        if not 16 <= len(password) <= 256 or any(ord(c) < 32 or ord(c) == 127 for c in password):
            raise ValueError('GUI_PASSWORD must be 16–256 characters without control characters')
        path = env.get('GUI_PATH', '/')
        if path != '/' and not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+/?', path):
            raise ValueError('GUI_PATH must be / or an absolute path using letters, digits, underscores and hyphens')
        path = path.rstrip('/')  # Root becomes empty; all routed URLs start with /.
        port_text = env.get('GUI_PORT', '18100')
        if not re.fullmatch(r'[1-9][0-9]{3,4}', port_text) or not 1024 <= int(port_text) <= 65535 or int(port_text) == 40000:
            raise ValueError('GUI_PORT must be 1024–65535 and must not be 40000')
        return cls(username, password, path, int(port_text), env.get('GUI_BIND', '127.0.0.1'))


if __name__ == '__main__':
    try:
        Settings.from_env()
    except ValueError as error:
        raise SystemExit(str(error))
