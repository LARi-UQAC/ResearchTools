"""
wp_config.py - {value, provenance} config reader for wp-portfolio-sync.

Stage: imported by wp_common.py (client_from_config) and by discover.py
(rest.per_page). Holds the single parsing path for wp-sync-config.json,
so a missing or malformed key is named once, consistently (R3, R4).
"""
import json
from pathlib import Path

from wp_errors import WpRefusal

CONFIG_NAME = "wp-sync-config.json"


def load_config(path=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Load wp-sync-config.json.

    Inputs:
        path (Path or None): explicit config path, used by tests to inject a
            fixture; defaults to CONFIG_NAME beside this module.

    Outputs:
        config (dict): the parsed JSON document.

    Raises:
        WpRefusal: the file is missing or is not valid JSON, naming the path.
    --------------------------------------------------------------------------
    """
    target = Path(path) if path is not None else Path(__file__).resolve().parent / CONFIG_NAME
    if not target.is_file():
        raise WpRefusal("config file not found: %s" % target)
    try:
        with open(target, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise WpRefusal("config file is not valid JSON: %s (%s)" % (target, exc)) from exc


def config_value(config, dotted_key, source):
    """
    --------------------------------------------------------------------------
    Purpose:
        Walk a dotted key (e.g. "http.timeout_s") through a loaded config
        dict and return its provenance-carrying value (R3, R4).

    Inputs:
        config (dict): a document returned by load_config.
        dotted_key (str): a dot-separated path to a {"value", "provenance"} node.
        source (str): the file or caller name reported in a refusal, so a
            missing key is traceable to where it was asked for.

    Outputs:
        value: the node's "value" entry, whatever type it carries.

    Raises:
        WpRefusal: the dotted key is absent, or the node lacks "value" or a
            non-empty "provenance" string, naming dotted_key and source.
    --------------------------------------------------------------------------
    """
    node = config
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise WpRefusal("missing config key %r (from %s)" % (dotted_key, source))
        node = node[part]
    if not isinstance(node, dict) or "value" not in node:
        raise WpRefusal("config key %r (from %s) has no value" % (dotted_key, source))
    provenance = node.get("provenance")
    if not isinstance(provenance, str) or not provenance.strip():
        raise WpRefusal("config key %r (from %s) has no provenance" % (dotted_key, source))
    return node["value"]
