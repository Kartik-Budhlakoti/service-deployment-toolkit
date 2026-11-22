"""Run inside the demo API container. Only emit a fixed outcome label."""
import signal
import socket
import sys


def probe(kind, db_ip, timeout):
    if kind == "dns":
        try:
            addresses = {row[4][0] for row in socket.getaddrinfo(
                "db", 5432, socket.AF_INET, socket.SOCK_STREAM)}
        except socket.gaierror:
            return "resolution-failed"
        if not db_ip:
            return "resolved-address-unconfirmed"
        return "ok" if addresses == {db_ip} else "unexpected-address"

    if kind != "tcp" or not db_ip:
        return "unavailable"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect((db_ip, 5432))
        return "ok"
    except ConnectionRefusedError:
        return "connection-refused"
    except TimeoutError:
        return "timeout"
    except OSError:
        return "connection-error"


if __name__ == "__main__":
    # A killed Docker CLI does not necessarily stop an already submitted exec.
    seconds = float(sys.argv[3])
    signal.setitimer(signal.ITIMER_REAL, seconds)
    print(probe(sys.argv[1], sys.argv[2], seconds))
