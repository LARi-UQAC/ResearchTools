"""
augure_models - list the AugureAI models an account may use, and render the LiteLLM config.

Purpose (Issue #112, plan 2): the models are listed live from Augure's MCP server, kept only when
the local window file gives them the required context window, and the owner picks one of them at
switch time. Nothing is guessed: a model with no measured window is refused with its reason (R8).
Every number, URL, path and variable name comes from the three data files beside this module, each
as {value, provenance} (R0, R3, R4). Only variable NAMES are stored there, never a key value.

Separating the dev and chat keys later is one line of augure-profiles.json, no code change.

CLI:
    augure_models.py list --profile P [--json]
    augure_models.py render-config --out PATH [--dry-run] [--json]

Exit codes (R12): 0 done, 2 refusal by design (missing key, no selectable model, unknown profile,
a path outside ~/.claude), 1 failure (MCP error, unreachable server, unreadable file).
"""
import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = "augure-settings.json"
MODELS_FILE = "augure-models.json"
PROFILES_FILE = "augure-profiles.json"

SETTINGS_KEYS = (
    "mcp_url", "mcp_protocol_version", "mcp_list_tool", "api_base", "proxy_host", "proxy_port",
    "liveness_path", "http_timeout_s", "proxy_start_timeout_s", "master_key_env", "config_path",
    "log_path", "log_max_bytes", "model_prefix", "litellm_provider",
)
SESSION_HEADER = "Mcp-Session-Id"


class ConfigError(Exception):
    """A data file is missing, unreadable or malformed, or a refusal names a missing variable."""


class McpError(Exception):
    """The MCP server answered an error, an isError result, or an answer that is not JSON-RPC."""


def _read_json(path):
    """
    Purpose:
        Read a data file as a JSON object.

    Inputs:
        path (Path): the file to read.

    Outputs:
        dict: the parsed top-level object.

    Raises:
        ConfigError: the file cannot be read, is not JSON, or its top level is not an object.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {Path(path).name}: {exc.strerror or exc}") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise ConfigError(f"{Path(path).name} is not valid JSON") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{Path(path).name} must hold a JSON object at its top level")
    return data


def _entry(doc, key, file_name):
    """
    Purpose:
        Return the value of a {value, provenance} entry, refusing a missing or unsourced one (R3, R4).

    Inputs:
        doc (dict): the loaded data file or a sub-object of it.
        key (str): the key to read.
        file_name (str): the data file name, quoted in every refusal.

    Outputs:
        Any: the entry's "value".

    Raises:
        ConfigError: the key is absent, not a {value, provenance} object, or has no provenance.
    """
    if key not in doc:
        raise ConfigError(f"'{key}' is missing from {file_name}")
    entry = doc[key]
    if not isinstance(entry, dict) or "value" not in entry:
        raise ConfigError(f"'{key}' in {file_name} must be an object with a 'value'")
    provenance = entry.get("provenance")
    if not isinstance(provenance, str) or not provenance.strip():
        raise ConfigError(f"'{key}' in {file_name} has no provenance (R4)")
    return entry["value"]


def _plain(doc, key, file_name):
    """
    Purpose:
        Return a plain (unwrapped) object of a data file, such as the models or profiles table.

    Inputs:
        doc (dict): the loaded data file.
        key (str): the key of the table.
        file_name (str): the data file name, quoted in every refusal.

    Outputs:
        Any: the value stored under key.

    Raises:
        ConfigError: the key is absent.
    """
    if key not in doc:
        raise ConfigError(f"'{key}' is missing from {file_name}")
    return doc[key]


def _is_positive_int(value):
    """
    Purpose:
        Tell a positive integer apart from a bool, a string, zero or a float.

    Inputs:
        value (Any): the candidate.

    Outputs:
        bool: True only for an int above zero that is not a bool.

    Raises:
        None.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def load_settings(path):
    """
    Purpose:
        Load and validate augure-settings.json (URLs, ports, timeouts, variable names).

    Inputs:
        path (Path): the settings file.

    Outputs:
        dict: the raw document, every entry still {value, provenance}.

    Raises:
        ConfigError: a file problem, a missing key (named), a key without provenance, or a
        timeout or port that is not a positive number.
    """
    doc = _read_json(path)
    for key in SETTINGS_KEYS:
        _entry(doc, key, Path(path).name)
    timeout = _entry(doc, "http_timeout_s", Path(path).name)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ConfigError(f"'http_timeout_s' in {Path(path).name} must be a positive number")
    port = _entry(doc, "proxy_port", Path(path).name)
    if not _is_positive_int(port):
        raise ConfigError(f"'proxy_port' in {Path(path).name} must be a positive integer")
    return doc


def load_models(path):
    """
    Purpose:
        Load and validate augure-models.json: the required window and each model's measured window.

    Inputs:
        path (Path): the models file.

    Outputs:
        dict: the raw document, every entry still {value, provenance}.

    Raises:
        ConfigError: a file problem, a missing key (named), or any window that is not a positive
        integer (string, zero, negative, bool or float).
    """
    doc = _read_json(path)
    name = Path(path).name
    required = _entry(doc, "required_window", name)
    if not _is_positive_int(required):
        raise ConfigError(f"'required_window' in {name} must be a positive integer")
    models = _plain(doc, "models", name)
    if not isinstance(models, dict):
        raise ConfigError(f"'models' in {name} must be an object")
    for model_id, body in models.items():
        if not isinstance(body, dict):
            raise ConfigError(f"model '{model_id}' in {name} must be an object")
        window = _entry(body, "context_window", name)
        if not _is_positive_int(window):
            raise ConfigError(f"context_window of '{model_id}' in {name} must be a positive integer")
    return doc


def load_profiles(path):
    """
    Purpose:
        Load and validate augure-profiles.json: the environment variable NAMES of each account profile.

    Inputs:
        path (Path): the profiles file.

    Outputs:
        dict: the raw document, with a "profiles" object of {api_key_env, mcp_key_env} entries.

    Raises:
        ConfigError: a file problem, a missing profile key (named), or a variable name that is not
        a non-empty string.

    Separating the dev and chat keys later is one line of augure-profiles.json, no code change.
    """
    doc = _read_json(path)
    name = Path(path).name
    profiles = _plain(doc, "profiles", name)
    if not isinstance(profiles, dict) or not profiles:
        raise ConfigError(f"'profiles' in {name} must be a non-empty object")
    for profile_name, body in profiles.items():
        if not isinstance(body, dict):
            raise ConfigError(f"profile '{profile_name}' in {name} must be an object")
        for field in ("api_key_env", "mcp_key_env"):
            value = _entry(body, field, name)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"'{field}' of profile '{profile_name}' in {name} must name a variable")
    return doc


def parse_mcp_body(text):
    """
    Purpose:
        Extract the JSON-RPC object from an MCP answer, plain JSON or Server-Sent Events.

    Details:
        The real server answers `event: message` then `data: {json}` (measured 2026-11-27). The
        last event holding a `result` or an `error` wins.

    Inputs:
        text (str): the raw HTTP body.

    Outputs:
        dict: the JSON-RPC object, with a "result" or an "error" key.

    Raises:
        McpError: the body is empty, or holds no JSON-RPC object. The body is never quoted.
    """
    stripped = (text or "").strip()
    if not stripped:
        raise McpError("empty answer from the MCP server")
    candidates = []
    if stripped.startswith("{"):
        candidates.append(stripped)
    else:
        current = []
        for line in stripped.splitlines():
            if not line.strip():
                if current:
                    candidates.append("\n".join(current))
                    current = []
                continue
            if line.startswith("data:"):
                current.append(line[5:].lstrip())
        if current:
            candidates.append("\n".join(current))
    chosen = None
    for raw in candidates:
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict) and ("result" in obj or "error" in obj):
            chosen = obj
    if chosen is None:
        raise McpError("no JSON-RPC answer in the MCP server's reply")
    return chosen


def _redact(text, key):
    """
    Purpose:
        Remove the key value from any text that may leave the process (R8, no key in output).

    Inputs:
        text (str): the message to clean.
        key (str): the key value to hide.

    Outputs:
        str: the text with every occurrence of the key replaced.

    Raises:
        None.
    """
    return text.replace(key, "<redacted>") if key else text


def _post(opener, url, payload, key, timeout, session=None):
    """
    Purpose:
        POST one JSON-RPC message to the MCP server with the bearer key and the session header.

    Inputs:
        opener (Callable): urllib-style opener, called as opener(request, timeout=...).
        url (str): the MCP endpoint.
        payload (dict): the JSON-RPC message.
        key (str): the bearer key (from the environment only).
        timeout (float): seconds for this one request (R10).
        session (str | None): the Mcp-Session-Id to echo, when the server gave one.

    Outputs:
        tuple[str, Mapping]: the decoded body and the response headers.

    Raises:
        McpError: an HTTP error, or the server is unreachable. The response body is not quoted.
    """
    headers = {
        "Authorization": "Bearer " + key,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if session:
        headers[SESSION_HEADER] = session
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with opener(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            resp_headers = resp.headers
    except urllib.error.HTTPError as exc:
        raise McpError(f"HTTP {exc.code} from the MCP server") from None
    except (urllib.error.URLError, OSError) as exc:
        raise McpError(f"MCP server unreachable ({type(exc).__name__})") from None
    return text, resp_headers


def _raise_on_rpc_error(obj):
    """
    Purpose:
        Turn a JSON-RPC error or an isError tool result into an McpError.

    Inputs:
        obj (dict): a parsed JSON-RPC object.

    Outputs:
        None.

    Raises:
        McpError: the object carries an "error", or a result with isError set to true.
    """
    if "error" in obj:
        err = obj["error"]
        message = err.get("message", "unspecified") if isinstance(err, dict) else str(err)
        raise McpError(f"MCP error: {message}")
    result = obj.get("result")
    if isinstance(result, dict) and result.get("isError"):
        texts = [c.get("text", "") for c in result.get("content", []) if isinstance(c, dict)]
        raise McpError("MCP tool reported an error: " + " ".join(t for t in texts if t))


def _fetch_model_ids(settings, key, opener):
    """
    Purpose:
        Run the MCP handshake (initialize, notification, tools/call) and return the model ids.

    Inputs:
        settings (dict): the loaded settings document.
        key (str): the bearer key.
        opener (Callable): urllib-style opener.

    Outputs:
        list[str]: the model ids from structuredContent.models, in server order.

    Raises:
        McpError: any protocol or server failure, or an answer without structuredContent.models.
    """
    url = _entry(settings, "mcp_url", SETTINGS_FILE)
    timeout = _entry(settings, "http_timeout_s", SETTINGS_FILE)
    protocol = _entry(settings, "mcp_protocol_version", SETTINGS_FILE)
    tool = _entry(settings, "mcp_list_tool", SETTINGS_FILE)

    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": protocol, "capabilities": {},
                       "clientInfo": {"name": "augure-models", "version": "1"}}}
    text, hdrs = _post(opener, url, init, key, timeout)
    _raise_on_rpc_error(parse_mcp_body(text))
    session = hdrs.get(SESSION_HEADER)

    _post(opener, url, {"jsonrpc": "2.0", "method": "notifications/initialized"},
          key, timeout, session)

    call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": tool, "arguments": {}}}
    text, _ = _post(opener, url, call, key, timeout, session)
    obj = parse_mcp_body(text)
    _raise_on_rpc_error(obj)

    result = obj.get("result")
    structured = result.get("structuredContent") if isinstance(result, dict) else None
    if not isinstance(structured, dict) or not isinstance(structured.get("models"), list):
        raise McpError("the list_models answer has no structuredContent.models")
    ids = []
    for model in structured["models"]:
        if not isinstance(model, dict) or not isinstance(model.get("id"), str) or not model["id"]:
            raise McpError("a model in the list_models answer has no id")
        ids.append(model["id"])
    return ids


def list_models(profile, environ, opener=None, data_dir=None):
    """
    Purpose:
        List the models of one account profile that reach the required context window.

    Details:
        The key is read only from `environ`, under the variable the profile names (mcp_key_env).
        A model the server lists but augure-models.json does not describe is refused with a reason
        that names the file; a window below required_window is refused with both numbers.

    Inputs:
        profile (str): the profile name, a key of augure-profiles.json.
        environ (Mapping[str, str]): the environment holding the MCP key (os.environ in production).
        opener (Callable | None): urllib-style opener for tests; urllib.request.urlopen when None.
        data_dir (Path | None): folder of the three data files; this module's folder when None.

    Outputs:
        dict: {"profile": str, "selectable": [{"id", "context_window"}], "refused": [{"id", "reason"}]}.

    Raises:
        ConfigError: unknown profile, a data file problem, or the key variable is unset or empty.
        McpError: the MCP exchange failed. The key value is redacted from the message.
    """
    base = Path(data_dir) if data_dir is not None else DATA_DIR
    settings = load_settings(base / SETTINGS_FILE)
    models = load_models(base / MODELS_FILE)
    profiles = _plain(load_profiles(base / PROFILES_FILE), "profiles", PROFILES_FILE)
    if profile not in profiles:
        raise ConfigError(f"unknown profile '{profile}' (known: {', '.join(profiles)})")
    key_var = _entry(profiles[profile], "mcp_key_env", PROFILES_FILE)
    key = (environ or {}).get(key_var, "") or ""
    if not key.strip():
        raise ConfigError(f"{key_var} is not set or empty at the User scope; the model listing needs it")
    key = key.strip()
    if opener is None:
        opener = urllib.request.urlopen

    try:
        ids = _fetch_model_ids(settings, key, opener)
    except McpError as exc:
        raise McpError(_redact(str(exc), key)) from None
    logger.info("[AUGURE] %d model(s) listed for profile %s", len(ids), profile)

    window_required = _entry(models, "required_window", MODELS_FILE)
    table = _plain(models, "models", MODELS_FILE)
    selectable, refused = [], []
    for model_id in ids:
        if model_id not in table:
            refused.append({"id": model_id, "reason": "no context window in augure-models.json"})
            continue
        window = _entry(table[model_id], "context_window", MODELS_FILE)
        if window < window_required:
            refused.append({"id": model_id, "reason": (
                f"context window {window} is below the required {window_required} "
                f"(augure-models.json)")})
            continue
        selectable.append({"id": model_id, "context_window": window})
    return {"profile": profile, "selectable": selectable, "refused": refused}


def render_config(profiles, settings):
    """
    Purpose:
        Build the LiteLLM proxy config: one wildcard model per profile, master key by reference.
        The provider prefix of each wildcard is litellm_provider from the settings, not a literal:
        the 'openai' provider routes /v1/messages through the Responses API and fails on Augure
        (measured 2026-11-27), so the shipped value is 'hosted_vllm' (chat/completions).

    Inputs:
        profiles (dict): the loaded augure-profiles.json document (top key "profiles").
        settings (dict): the loaded augure-settings.json document.

    Outputs:
        dict: {"model_list": [...], "general_settings": {"master_key": "os.environ/<var>"}}, with no
        key value in it (only variable names). Each litellm_params.model is "<provider>/*".

    Raises:
        ConfigError: a required settings or profile entry is missing (named).
    """
    prefix = _entry(settings, "model_prefix", SETTINGS_FILE)
    api_base = _entry(settings, "api_base", SETTINGS_FILE)
    master_var = _entry(settings, "master_key_env", SETTINGS_FILE)
    provider = _entry(settings, "litellm_provider", SETTINGS_FILE)
    model_list = []
    for name, body in _plain(profiles, "profiles", PROFILES_FILE).items():
        api_key_var = _entry(body, "api_key_env", PROFILES_FILE)
        model_list.append({
            "model_name": f"{prefix}{name}/*",
            "litellm_params": {
                "model": f"{provider}/*",
                "api_base": api_base,
                "api_key": f"os.environ/{api_key_var}",
            },
        })
    return {"model_list": model_list,
            "general_settings": {"master_key": f"os.environ/{master_var}"}}


def _expand_home(text):
    """
    Purpose:
        Expand a leading ~ to the user's home folder, taken from Path.home().

    Inputs:
        text (str): a path, possibly starting with ~.

    Outputs:
        Path: the expanded path, not yet resolved.

    Raises:
        None.
    """
    if text == "~":
        return Path.home()
    if text.startswith("~/") or text.startswith("~\\"):
        return Path.home() / text[2:]
    return Path(text)


def _write_atomic(path, payload):
    """
    Purpose:
        Write JSON text to path through a sibling .tmp file and os.replace (no partial file left).

    Inputs:
        path (Path): the destination.
        payload (dict): the object to serialise.

    Outputs:
        None. Side effect: creates the parent folder and the file.

    Raises:
        OSError: the write or the replace failed; the .tmp file is removed first.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        if tmp.exists():
            tmp.unlink()
        raise


def _render_command(args, data_dir):
    """
    Purpose:
        Run the render-config subcommand: refuse a path outside ~/.claude, then write or dry-run.

    Inputs:
        args (Namespace): parsed arguments (out, dry_run, json).
        data_dir (Path | None): folder of the data files; this module's folder when None.

    Outputs:
        int: 0 when done (or dry run), as the exit code.

    Raises:
        ConfigError: the output path is not strictly inside ~/.claude (R24).
    """
    base = Path(data_dir) if data_dir is not None else DATA_DIR
    settings = load_settings(base / SETTINGS_FILE)
    profiles = load_profiles(base / PROFILES_FILE)
    out = _expand_home(args.out).resolve()
    claude_dir = (Path.home() / ".claude").resolve()
    if out == claude_dir or not out.is_relative_to(claude_dir):
        raise ConfigError(f"refusing to write {out}: the config must lie inside {claude_dir}")
    config = render_config(profiles, settings)
    if not args.dry_run:
        _write_atomic(out, config)
    report = {"out": str(out), "written": not args.dry_run,
              "model_names": [m["model_name"] for m in config["model_list"]]}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        verb = "would write" if args.dry_run else "wrote"
        print(f"[AUGURE] {verb} {out}")
    return 0


def _list_command(args, environ, opener, data_dir):
    """
    Purpose:
        Run the list subcommand and print the report; exit 2 when no model is selectable.

    Inputs:
        args (Namespace): parsed arguments (profile, json).
        environ (Mapping[str, str]): the environment holding the key.
        opener (Callable | None): urllib-style opener, or None for the real one.
        data_dir (Path | None): folder of the data files, or None.

    Outputs:
        int: 0 with at least one selectable model, 2 otherwise.

    Raises:
        ConfigError, McpError: propagated to main, which maps them to exit codes.
    """
    report = list_models(args.profile, environ, opener=opener, data_dir=data_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"profile {report['profile']}")
        for item in report["selectable"]:
            print(f"  selectable  {item['id']}  {item['context_window']}")
        for item in report["refused"]:
            print(f"  refused     {item['id']}  {item['reason']}")
    if not report["selectable"]:
        print("[AUGURE] no model is selectable for this profile; see the refused reasons",
              file=sys.stderr)
        return 2
    return 0


def build_parser():
    """
    Purpose:
        Build the command-line parser of augure_models.

    Inputs:
        None.

    Outputs:
        argparse.ArgumentParser: the parser with the list and render-config subcommands.

    Raises:
        None.
    """
    parser = argparse.ArgumentParser(prog="augure_models", description=__doc__.split("\n")[1])
    sub = parser.add_subparsers(dest="command", required=True)
    lst = sub.add_parser("list", help="list the models the profile may use")
    lst.add_argument("--profile", required=True)
    lst.add_argument("--json", action="store_true")
    render = sub.add_parser("render-config", help="write the LiteLLM proxy config")
    render.add_argument("--out", required=True)
    render.add_argument("--dry-run", action="store_true")
    render.add_argument("--json", action="store_true")
    return parser


def main(argv=None, *, environ=None, opener=None, data_dir=None):
    """
    Purpose:
        Entry point of the CLI, returning the exit code (R12).

    Inputs:
        argv (list[str] | None): the arguments; sys.argv[1:] when None.
        environ (Mapping[str, str] | None): the environment; os.environ when None.
        opener (Callable | None): urllib-style opener, for tests only.
        data_dir (Path | None): folder of the data files, for tests only.

    Outputs:
        int: 0 done, 2 refusal, 1 failure.

    Raises:
        None. Every expected failure is mapped to an exit code and a [AUGURE] line on stderr.
    """
    args = build_parser().parse_args(argv)
    env = os.environ if environ is None else environ
    try:
        if args.command == "list":
            return _list_command(args, env, opener, data_dir)
        return _render_command(args, data_dir)
    except ConfigError as exc:
        print(f"[AUGURE] refused: {exc}", file=sys.stderr)
        return 2
    except McpError as exc:
        print(f"[AUGURE] MCP failure: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"[AUGURE] failure: {exc.strerror or exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
