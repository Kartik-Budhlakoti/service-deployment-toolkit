"""One bounded-body HTTP probe; the parent enforces a wall-clock deadline."""
import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


ITEMS = [{"id": 1, "name": "Notebook"}, {"id": 2, "name": "Pencil"},
         {"id": 3, "name": "Folder"}]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def observe_http(url, kind, release, timeout):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username:
        return "unsupported-url"
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(url, timeout=timeout) as response:
            if response.status != 200:
                return f"http-{response.status}"
            raw = response.read(65537)
        if len(raw) > 65536:
            return "oversize-body"
        body = json.loads(raw)
        if kind == "live":
            matches = body == {"status": "alive"}
        elif kind == "release":
            matches = body == {"release": release}
        else:
            matches = (kind == "items" and body == ITEMS and isinstance(body, list)
                       and all(type(row.get("id")) is int for row in body))
        return "ok" if matches else "unexpected-body"
    except HTTPError as error:
        error.close()
        return f"http-{error.code}"
    except URLError as error:
        if isinstance(error.reason, ConnectionRefusedError):
            return "connection-refused"
        return "timeout" if isinstance(error.reason, TimeoutError) else "connection-error"
    except TimeoutError:
        return "timeout"
    except (ValueError, RecursionError):
        return "invalid-body"
    except Exception:
        return "probe-error"


def probe(url, kind, release, timeout):
    return observe_http(url, kind, release, timeout) == "ok"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("kind", choices=("live", "release", "items"))
    parser.add_argument("release")
    parser.add_argument("timeout", type=float)
    parser.add_argument("--observation", action="store_true")
    args = parser.parse_args()
    if args.observation:
        print(observe_http(args.url, args.kind, args.release, args.timeout))
        return 0
    if probe(args.url, args.kind, args.release, args.timeout):
        print("PASS")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
