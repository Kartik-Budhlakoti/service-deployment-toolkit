"""Bounded fields shared by verification, the journal and report export."""
import re


ROUTES = ("live", "direct_version", "proxy_version", "direct_items", "proxy_items")
HTTP_LABELS = {"ok", "oversize-body", "unexpected-body", "connection-refused",
               "connection-error", "timeout", "invalid-body", "probe-error", "probe-unavailable"}
INSTANCE_FIELDS = {
    "api_id": r"[0-9a-f]{64}",
    "image_id": r"sha256:[0-9a-f]{64}",
    "started_at": r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z",
}


def http_label(value):
    if isinstance(value, str) and (value in HTTP_LABELS or re.fullmatch(r"http-[1-5][0-9]{2}", value)):
        return value
    return "probe-unavailable"


def observed_instance(api):
    values = (api["Id"], api["Image"], api["State"].get("StartedAt"))
    return {
        key: value if isinstance(value, str) and re.fullmatch(pattern, value) else None
        for (key, pattern), value in zip(INSTANCE_FIELDS.items(), values, strict=True)
    }


def validate_trace(trace):
    if type(trace) is not dict or set(trace) != {"first_failed", "last"}:
        raise ValueError("Invalid verification observations")
    for attempt in trace.values():
        if attempt is None:
            continue
        if type(attempt) is not dict or set(attempt) != {"number", "instance", "inspection", "deadline", "routes"}:
            raise ValueError("Invalid attempt")
        if type(attempt["number"]) is not int or not 1 <= attempt["number"] <= 1000:
            raise ValueError("Invalid attempt number")
        if type(attempt["deadline"]) is not bool or attempt["inspection"] not in (
                "unconfirmed", "running", "exited", "changed"):
            raise ValueError("Invalid observation")
        instance = attempt["instance"]
        if instance is not None:
            if type(instance) is not dict or set(instance) != set(INSTANCE_FIELDS):
                raise ValueError("Invalid API identity")
            for key, pattern in INSTANCE_FIELDS.items():
                value = instance[key]
                if value is not None and (type(value) is not str or not re.fullmatch(pattern, value)):
                    raise ValueError("Invalid API identity")
        routes = attempt["routes"]
        if type(routes) is not dict or set(routes) != set(ROUTES):
            raise ValueError("Invalid HTTP observations")
        for value in routes.values():
            if value not in ("not-run", "deadline") and http_label(value) != value:
                raise ValueError("Unsupported HTTP observation")
    first, last = trace["first_failed"], trace["last"]
    if last is None or (first is not None and first["number"] > last["number"]):
        raise ValueError("Invalid attempt order")
