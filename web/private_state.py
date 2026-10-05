"""Locked private state shared by automatic GUI paths and passwords."""
import fcntl
import os
from pathlib import Path
import stat
import tempfile


def private_file(path, create=False):
    flags = os.O_RDWR if create else os.O_RDONLY
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 128:
            raise ValueError('Invalid persisted GUI state file')
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, 'r+' if create else 'r', encoding='ascii')
    except Exception:
        os.close(fd)
        raise


def load_or_create(state_dir, name, validate, generate, create=True):
    """Serialize creation; fail closed on unsafe or malformed existing state."""
    if name not in ('gui-path', 'gui-password'):
        raise ValueError('Unsupported GUI state file')
    root = Path(state_dir)
    try:
        with private_file(root / ('.' + name + '.lock'), create=create) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX if create else fcntl.LOCK_SH)
            try:
                with private_file(root / name) as stream:
                    value = stream.read(129).removesuffix('\n')
                if not validate(value):
                    raise ValueError('Invalid persisted GUI state file')
                return value
            except FileNotFoundError:
                if not create:
                    raise
            value = generate()
            if not validate(value):
                raise ValueError('Invalid generated GUI state')
            fd, temporary = tempfile.mkstemp(prefix='.' + name + '-', dir=root)
            try:
                with os.fdopen(fd, 'w', encoding='ascii') as stream:
                    stream.write(value + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, root / name)
                # Persist the rename as well as the file contents.
                directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return value
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError('Cannot safely load or save GUI state; check the data directory and GUI state files') from error
