"""
engines - one adapter module per speech-to-text engine, looked up by name.

The registry is data (stt-bench-config.json "engines"), so a new engine is one module here
plus one entry there, with no change to the benchmark. Every adapter exposes:

  available() -> (bool, reason)             cheap, imports nothing heavy
  download(model) -> None                   fetch the weights (untimed by the caller)
  load(model, compute_type, device) -> h    the loaded model
  transcribe(h, audio_path, language, options) -> str
"""
import importlib

from bench_config import value


class EngineUnavailable(RuntimeError):
    """The named engine is unknown, not installed or not implemented; the message says which."""


def adapter_module(name: str, config: dict):
    """
    --------------------------------------------------------------------------
    Purpose:
        Import the adapter module declared for an engine name.

    Inputs:
        name (str): the engine name, e.g. "faster-whisper"
        config (dict): parsed stt-bench-config.json

    Outputs:
        module (module): the adapter

    Raises:
        EngineUnavailable: the name is not declared in the config.
    --------------------------------------------------------------------------
    """
    declared = config.get("engines", {})
    if name not in declared:
        raise EngineUnavailable(f"unknown engine '{name}'; declared: {', '.join(sorted(declared))}")
    return importlib.import_module(f"engines.{value(config, 'engines', name, 'module')}")


def get_engine(name: str, config: dict):
    """
    --------------------------------------------------------------------------
    Purpose:
        Return a usable adapter, or say exactly why there is none.

    Inputs:
        name (str): the engine name
        config (dict): parsed stt-bench-config.json

    Outputs:
        module (module): an adapter whose available() answered True

    Raises:
        EngineUnavailable: unknown, not installed, or not implemented; the
            message carries the declared install command.
    --------------------------------------------------------------------------
    """
    adapter = adapter_module(name, config)
    ok, reason = adapter.available()
    if not ok:
        raise EngineUnavailable(f"{name}: {reason}. Install: "
                                f"{value(config, 'engines', name, 'install')}")
    return adapter
