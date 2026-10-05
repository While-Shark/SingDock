"""Generate and retain a strong password when GUI_PASSWORD is unset or empty."""
import secrets
import string
from private_state import load_or_create

GROUPS = (string.ascii_lowercase, string.ascii_uppercase, string.digits, '!@#%_-')
ALPHABET = ''.join(GROUPS)


def valid_generated(value):
    return (len(value) == 32 and all(c in ALPHABET for c in value)
            and all(any(c in group for c in value) for group in GROUPS))


def generate():
    # Rejection sampling keeps every accepted password equally likely while
    # guaranteeing lowercase, uppercase, digits and symbols.
    while True:
        value = ''.join(secrets.choice(ALPHABET) for _ in range(32))
        if valid_generated(value):
            return value


def resolve_password(state_dir, create=True):
    return load_or_create(state_dir, 'gui-password', valid_generated, generate, create)
