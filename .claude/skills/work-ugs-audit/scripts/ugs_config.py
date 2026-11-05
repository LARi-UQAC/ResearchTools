"""ugs_config - reads the work-ugs-audit configuration (Issue 104, plan 3)."""

import json
import re
from pathlib import Path

_PROFILE_RE = re.compile(r"^active_profile:[ \t]*([A-Za-z0-9_-]+)[ \t]*$", re.MULTILINE)


class ConfigError(ValueError):
    """Raised when a configuration value is missing or malformed."""


REQUIRED_KEYS = (
    "annotation.colors",
    "references.url_timeout_s",
    "references.max_retries",
    "batch.outlier_z",
    "driver.audit_retries",
    "driver.request_timeout_s",
)


def default_path() -> Path:
    """Returns the default path to the configuration file."""
    return Path(__file__).resolve().parent.parent / "assets" / "ugs_config.json"


def load(path: Path) -> dict:
    """Reads and validates the UGS configuration file.

    Purpose: Load and validate the UGS configuration from a JSON file.
    Inputs: path (Path): The path to the configuration JSON file.
    Outputs: dict: A dictionary mapping each dotted key to its "value".
    Raises: ConfigError: If the file is missing, contains invalid JSON,
        is not a dict, or any entry lacks required structure or keys.
    """
    if not path.exists():
        raise ConfigError(f"missing file: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ConfigError(f"invalid JSON: {path}")

    if not isinstance(raw, dict):
        raise ConfigError(f"top level must be a dict: {path}")

    result = {}
    for dotted_key, entry in raw.items():
        if not isinstance(entry, dict):
            raise ConfigError(f"entry for {dotted_key} must be a dict: {path}")
        if "value" not in entry:
            raise ConfigError(f"missing 'value' for {dotted_key}: {path}")
        if "provenance" not in entry or not isinstance(entry["provenance"], str) or not entry["provenance"]:
            raise ConfigError(f"missing or empty 'provenance' for {dotted_key}: {path}")
        result[dotted_key] = entry["value"]

    for key in REQUIRED_KEYS:
        if key not in result:
            raise ConfigError(f"missing required key '{key}': {path}")

    return result

def annotation_author(repo_root: Path) -> str:
    """
    Purpose: Return the author name from the active profile in CLAUDE.md.
    Inputs: repo_root (Path): root directory of the repository.
    Outputs: str: the stripped author name.
    Raises: ConfigError: if any required file, key, or value is missing or invalid.
    """
    import yaml

    claude_path = repo_root / ".claude" / "CLAUDE.md"
    if not claude_path.is_file():
        raise ConfigError(f"Missing file: {claude_path}")

    content = claude_path.read_text(encoding="utf-8")
    match = _PROFILE_RE.search(content)
    if not match:
        raise ConfigError("active_profile line is missing from CLAUDE.md")

    profile_name = match.group(1)
    profile_path = repo_root / "profiles" / f"{profile_name}.yaml"
    if not profile_path.is_file():
        raise ConfigError(f"Missing profile file: {profile_path}")

    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "author" not in data:
        raise ConfigError(f"Missing 'author' block in {profile_path}")

    author = data["author"]
    if not isinstance(author, dict) or "name" not in author:
        raise ConfigError(f"Missing 'name' key in author block of {profile_path}")

    name = author["name"]
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"Invalid 'name' value in {profile_path}")

    return name.strip()