"""Create one private random GUI path per deployment, never per image."""
import re
import secrets
from private_state import load_or_create

AUTO_PATTERN = re.compile(r'/panel-[0-9a-f]{32}')


def resolve_path(state_dir, create=True):
    return load_or_create(state_dir, 'gui-path', AUTO_PATTERN.fullmatch,
                          lambda: '/panel-' + secrets.token_hex(16), create)
