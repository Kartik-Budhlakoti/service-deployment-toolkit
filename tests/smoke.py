import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

EXPECTED = [
    {"id": 1, "name": "Notebook"},
    {"id": 2, "name": "Pencil"},
    {"id": 3, "name": "Folder"},
]
# These checks target local services, not a configured HTTP proxy.
OPENER = build_opener(ProxyHandler({}))


class CheckFailure(Exception):
    pass


def read(url):
    try:
        response = OPENER.open(url, timeout=12)
    except HTTPError as error:
        response = error
    with response:
        status = response.code
        body = response.read(65537)
    if len(body) > 65536:
        raise ValueError("Response exceeded the checker limit")
    return status, json.loads(body)


def verify(base, database_down=False):
    unavailable = {"detail": "Catalogue unavailable"}
    checks = [
        ("/health/live", 200, {"status": "alive"}),
        ("/version", 200, {"release": "demo-v1"}),
        ("/health/ready", 503 if database_down else 200,
         unavailable if database_down else {"status": "ready"}),
        ("/items", 503 if database_down else 200,
         unavailable if database_down else EXPECTED),
    ]
    for path, expected_status, expected_body in checks:
        status, body = read(base.rstrip("/") + path)
        if status != expected_status:
            raise CheckFailure(f"{path}: expected HTTP {expected_status}, got {status}")
        if body != expected_body:
            raise CheckFailure(f"{path}: response did not match expected content")
    mode = "database-outage behavior" if database_down else "healthy-stack behavior"
    print(f"PASS: {mode} at {base}")


def main():
    parser = argparse.ArgumentParser(description="Verify the local demo stack.")
    parser.add_argument("--database-down", action="store_true")
    args = parser.parse_args()
    failures = 0
    for base in ("http://127.0.0.1:8089", "http://127.0.0.1:8088"):
        try:
            verify(base, args.database_down)
        except CheckFailure as error:
            print(f"FAIL: {base}: {error}", file=sys.stderr)
            failures += 1
        except (OSError, URLError, ValueError) as error:
            # Do not print response bodies or connection details.
            print(f"FAIL: {base}: {type(error).__name__}; "
                  "request failed or response did not match expectations", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
