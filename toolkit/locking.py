from contextlib import contextmanager
import fcntl
import os
import stat


class LockBusy(RuntimeError):
    pass


@contextmanager
def mutation_lock(path):
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags, 0o600), "rb") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise OSError("Lock must be a regular file")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LockBusy("Another toolkit operation holds the mutation lock") from None
        yield
