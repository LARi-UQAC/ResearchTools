#!/usr/bin/env python3
"""
stt_engine.py - local speech-to-text, faster-whisper on the GPU.

An OPTIONAL dependency, following the same pattern rt_store.py and
rt_openobserve.py already use for their own optional layers: the import
happens lazily, inside _default_loader only, so importing this module (and
therefore importing rt_server.py, and therefore starting rt-dashboard at
all) never requires faster-whisper to be installed. A machine without it
sees the voice route answer "unavailable" naming requirements-voice.txt,
never a broken dashboard.

Model size/compute_type/device and the anti-hallucination options are
config-driven (observe-config.json voice.stt.*) and copy the Devoir2
reference implementation's measured configuration: small / float16 / cuda,
VAD filter on, no conditioning on the previous text. Language is
per-request (the voice panel's own dropdown, auto/en/fr).

On Windows with no system CUDA Toolkit, ctranslate2 finds cuBLAS/cuDNN only
once the pip-installed nvidia-* package directories are on the DLL search
path (add_cuda_dll_dirs, ported from Devoir2's voice.py).
"""
import importlib.util
import io
import os
import sys
import threading
from pathlib import Path

_MODEL = None
_MODEL_LOCK = threading.Lock()
_LANGUAGE_HINT = {"auto": None, "en": "en", "fr": "fr"}
_CUDA_PACKAGES = ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc")
_INSTALL_HINT = ("pip install -r .claude/skills/rt-observe/scripts/"
                 "requirements-voice.txt (and requirements-voice-cuda.txt "
                 "for the GPU runtime)")


class SttUnavailable(RuntimeError):
    """faster-whisper (or the configured engine) could not be loaded."""


def reset_loaded_model() -> None:
    """Test-only: clear the module-level singleton between cases."""
    global _MODEL
    _MODEL = None


def _stt_value(config: dict, key: str):
    """Read voice.stt.<key>.value, naming the key when it is absent (R3)."""
    stt = config["voice"]["stt"]
    if key not in stt:
        raise KeyError(f"observe-config.json declares no voice.stt.{key}")
    return stt[key]["value"]


def add_cuda_dll_dirs(device: str, platform: str = None, find_spec=None,
                      add_dll_directory=None, environ=None) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Make the pip-installed cuBLAS/cuDNN/NVRTC DLLs findable by Windows
        before faster-whisper runs on CUDA. Ported from Devoir2's
        _ajouter_repertoires_dll_cuda, which measured on this machine that
        ctranslate2 otherwise raises `cublas64_12.dll is not found` on the
        first real calculation. os.add_dll_directory alone was measured not
        to be enough (ctranslate2 loads lazily with LoadLibrary, not
        LoadLibraryEx), so PATH is extended as well.

    Inputs:
        device (str): ctranslate2 device, e.g. "cpu" or "cuda"
        platform, find_spec, add_dll_directory, environ: injected for the
            suite; default to sys.platform, importlib.util.find_spec,
            os.add_dll_directory and os.environ

    Outputs:
        None. Never raises: a package that is absent is skipped, and the
        first transcription then names the missing DLL itself (R8).
    --------------------------------------------------------------------------
    """
    platform = platform or sys.platform
    if not str(device).startswith("cuda") or platform != "win32":
        return
    find_spec = find_spec or importlib.util.find_spec
    add_dll_directory = add_dll_directory or getattr(os, "add_dll_directory",
                                                     None)
    environ = os.environ if environ is None else environ
    for package in _CUDA_PACKAGES:
        try:
            spec = find_spec(package)
        except ModuleNotFoundError:
            # find_spec on a dotted name imports the parent first and raises
            # when 'nvidia' itself is absent (Devoir2's measured defect).
            continue
        if spec is None or not spec.submodule_search_locations:
            continue
        bin_dir = Path(next(iter(spec.submodule_search_locations))) / "bin"
        if not bin_dir.is_dir():
            continue
        if add_dll_directory is not None:
            add_dll_directory(str(bin_dir))
        current = environ.get("PATH", "")
        if str(bin_dir) not in current.split(os.pathsep):
            environ["PATH"] = str(bin_dir) + os.pathsep + current


def _default_loader(config: dict):
    device = _stt_value(config, "device")
    add_cuda_dll_dirs(device)
    from faster_whisper import WhisperModel  # noqa: PLC0415 - optional dep
    return WhisperModel(_stt_value(config, "model_size"), device=device,
                        compute_type=_stt_value(config, "compute_type"))


def _loaded_model(config: dict, loader):
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    # The HTTP server is threaded: a live-preview request and the final one
    # can both arrive before the model exists, and loading it twice costs a
    # second copy of the weights in VRAM the card does not have.
    with _MODEL_LOCK:
        if _MODEL is None:
            try:
                _MODEL = (loader or (lambda: _default_loader(config)))()
            except Exception as exc:                       # noqa: BLE001
                raise SttUnavailable(
                    f"the configured STT engine could not be loaded: "
                    f"{type(exc).__name__}: {exc}. Install it with "
                    f"{_INSTALL_HINT}") from exc
    return _MODEL


def transcribe(audio_bytes: bytes, config: dict, loader=None,
               language: str = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Transcribe one push-to-talk recording (or a live-preview snapshot of
        it). The model loads once, under a lock, and is reused.

    Inputs:
        audio_bytes (bytes): the recorded audio as uploaded by the browser
        config (dict): parsed observe-config.json
        loader (callable): () -> model, injected for the suite; defaults to
            _default_loader, which imports faster_whisper lazily
        language (str | None): "auto", "en" or "fr" from the voice panel's
            dropdown; None falls back to voice.stt.language

    Outputs:
        text (str): the transcription, possibly empty when the recording
        carried no speech

    Raises:
        SttUnavailable: the configured engine could not be loaded.
        ValueError: `language` is not auto/en/fr - never silently treated as
            auto-detect (R8).
        KeyError: a voice.stt option key is absent from the config (R3).
    --------------------------------------------------------------------------
    """
    dropdown_value = language or _stt_value(config, "language") or "auto"
    if dropdown_value not in _LANGUAGE_HINT:
        raise ValueError(
            f"unsupported language {dropdown_value!r}; the voice panel's "
            "dropdown offers auto, en, fr only")
    options = {
        "language": _LANGUAGE_HINT[dropdown_value],
        "vad_filter": bool(_stt_value(config, "vad_filter")),
        "vad_parameters": {"min_silence_duration_ms":
                           int(_stt_value(config, "vad_min_silence_ms"))},
        "condition_on_previous_text":
            bool(_stt_value(config, "condition_on_previous_text")),
    }
    model = _loaded_model(config, loader)
    # faster-whisper's transcribe() accepts a path, a file-like object, or
    # an ndarray - never plain bytes, which it hands to PyAV's av.open()
    # and fails on. The browser's MediaRecorder upload arrives as bytes.
    segments, _info = model.transcribe(io.BytesIO(audio_bytes), **options)
    return " ".join(segment.text.strip() for segment in segments).strip()


def _silence_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    import struct  # noqa: PLC0415
    import wave  # noqa: PLC0415
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = int(seconds * rate)
        out.writeframes(struct.pack(f"<{frames}h", *([0] * frames)))
    return buf.getvalue()


def warm(config: dict, loader=None) -> "str | None":
    """
    --------------------------------------------------------------------------
    Purpose:
        Load the model and run one tiny transcription before anyone speaks,
        as Devoir2's _prechauffer_modele_whisper does. Measured 2026-09-26:
        with lazy loading, the first request took 14.3 s, so no live preview
        could appear during the first push-to-talk at all.

    Inputs:
        config (dict): parsed observe-config.json
        loader (callable): injected for the suite

    Outputs:
        reason (str | None): None when warm, otherwise why it could not be
        warmed. Never raises: the dashboard must start regardless.
    --------------------------------------------------------------------------
    """
    try:
        transcribe(_silence_wav(), config, loader=loader)
    except Exception as exc:                               # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    return None
