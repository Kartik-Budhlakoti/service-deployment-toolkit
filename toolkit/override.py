from pathlib import Path
import re

from .docker import InspectionError
from .state import _check_directory, _read_json, _write_json, state_directory


IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")


def override_path(root):
    return state_directory(root) / "compose-image.json"


def read_override(root):
    path = override_path(root)
    try:
        _check_directory(path.parent)
        try:
            value = _read_json(path)
        except FileNotFoundError:
            return None
        image = value["services"]["api"]["image"]
        if (not isinstance(image, str) or not IMAGE_ID.fullmatch(image)
                or value != {"services": {"api": {"image": image}}}):
            raise ValueError
        return image
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise InspectionError("Toolkit image override is unreadable or unsupported") from None


def write_override(root, image):
    if not isinstance(image, str) or not IMAGE_ID.fullmatch(image):
        raise ValueError("Override requires a full image ID")
    read_override(root)  # Do not silently overwrite an unsupported file.
    _write_json(override_path(root), {"services": {"api": {"image": image}}})


def config_label_allowed(root, service, value):
    base = str(Path(root) / "compose.yaml")
    if value == base:
        return True
    expected = base + "," + str(override_path(root))
    return service == "api" and value == expected and read_override(root) is not None
