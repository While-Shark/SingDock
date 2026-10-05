"""Create one private random GUI path per deployment, never per image."""
import fcntl
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

AUTO_PATTERN = re.compile(r'/panel-[0-9a-f]{32}')


def private_file(path, create=False):
    flags = os.O_RDWR if create else os.O_RDONLY
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 128:
            raise ValueError('Invalid persisted GUI path file')
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, 'r+' if create else 'r', encoding='ascii')
    except Exception:
        os.close(fd)
        raise


def resolve_path(state_dir):
    """Serialize creation; fail closed on unsafe or malformed existing state."""
    root = Path(state_dir)
    try:
        with private_file(root / '.gui-path.lock', create=True) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                with private_file(root / 'gui-path') as stream:
                    path = stream.read(129).rstrip('\n')
                if not AUTO_PATTERN.fullmatch(path):
                    raise ValueError('Invalid persisted GUI path file')
                return path
            except FileNotFoundError:
                pass
            path = '/panel-' + secrets.token_hex(16)
            fd, name = tempfile.mkstemp(prefix='.gui-path-', dir=root)
            try:
                with os.fdopen(fd, 'w', encoding='ascii') as stream:
                    stream.write(path + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, root / 'gui-path')
                # Persist the rename as well as the file contents.
                directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                Path(name).unlink(missing_ok=True)
            return path
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError('Cannot safely load or save GUI path; check the data directory and gui-path file') from error
