import os
import selectors
import signal
import subprocess
import time


class CommandError(RuntimeError):
    pass


def run_command(arguments, root, environment, timeout):
    try:
        process = subprocess.Popen(
            arguments, cwd=root, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        raise CommandError("Could not launch local command") from None
    deadline = time.monotonic() + timeout
    output = bytearray()
    total = 0
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CommandError("Local command timed out")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > 1024 * 1024:
                        raise CommandError("Local command output exceeded the 1 MiB limit")
                    if key.fileobj is process.stdout:
                        output.extend(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CommandError("Local command timed out")
            # Keep the group leader unreaped until group cleanup to avoid PID reuse.
            while True:
                exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is not None:
                    code = exited.si_status if exited.si_code == os.CLD_EXITED else -exited.si_status
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CommandError("Local command timed out")
                time.sleep(min(remaining, 0.01))
        if code:
            raise CommandError("Local command failed; raw output withheld to avoid exposing configuration")
        try:
            return output.decode("utf-8")
        except UnicodeDecodeError:
            raise CommandError("Local command returned invalid text") from None
    except OSError:
        raise CommandError("Local command I/O failed") from None
    finally:
        try:
            # Include ordinary child processes such as the Compose plugin.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            raise CommandError("Local command cleanup could not be confirmed") from None
        finally:
            process.stdout.close()
            process.stderr.close()
