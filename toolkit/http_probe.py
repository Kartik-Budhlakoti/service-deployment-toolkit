"""One bounded-body HTTP probe; the parent enforces a wall-clock deadline."""
import argparse
import json
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


ITEMS = [{"id": 1, "name": "Notebook"}, {"id": 2, "name": "Pencil"},
         {"id": 3, "name": "Folder"}]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def probe(url, kind, release, timeout):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username:
        return False
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(url, timeout=timeout) as response:
            if response.status != 200:
                return False
            raw = response.read(65537)
        if len(raw) > 65536:
            return False
        body = json.loads(raw)
        if kind == "live":
            return body == {"status": "alive"}
        if kind == "release":
            return body == {"release": release}
        if kind == "items":
            return (body == ITEMS and isinstance(body, list)
                    and all(type(row.get("id")) is int for row in body))
        return False
    except HTTPError as error:
        error.close()
        return False
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("kind", choices=("live", "release", "items"))
    parser.add_argument("release")
    parser.add_argument("timeout", type=float)
    args = parser.parse_args()
    if probe(args.url, args.kind, args.release, args.timeout):
        print("PASS")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
