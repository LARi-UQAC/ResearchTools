#!/usr/bin/env python3
"""
stt_engine.py - local speech-to-text, faster-whisper by default.

An OPTIONAL dependency, following the same pattern rt_store.py and
rt_openobserve.py already use for their own optional layers: the import
happens lazily, inside _default_loader only, so importing this module (and
therefore importing rt_server.py, and therefore starting rt-dashboard at
all) never requires faster-whisper to be installed. A machine without it
sees the voice route answer "unavailable" naming
requirements-voice.txt, never a broken dashboard.

Model size/compute_type/device are config-driven (observe-config.json
voice.stt.*), matching the Devoir2 reference implementation's own proven
defaults (small/int8/cpu). Language is per-request (the voice panel's own
dropdown, auto/en/fr), overriding config's default for that one call, since
the same server may answer a French question and an English one back to
back.
"""
_MODEL = None
_LANGUAGE_HINT = {"auto": None, "en": "en", "fr": "fr"}


class SttUnavailable(RuntimeError):
    """faster-whisper (or the configured engine) could not be loaded."""


def reset_loaded_model() -> None:
    """Test-only: clear the module-level singleton between cases."""
    global _MODEL
    _MODEL = None


def _default_loader(config: dict):
    from faster_whisper import WhisperModel  # noqa: PLC0415 - optional dep
    stt = config["voice"]["stt"]
    return WhisperModel(stt["model_size"]["value"],
                       device=stt["device"]["value"],
                       compute_type=stt["compute_type"]["value"])


def transcribe(audio_bytes: bytes, config: dict, loader=None,
               language: str = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Transcribe one push-to-talk recording. The model loads once (a
        module-level singleton) and is reused across calls, matching the
        Devoir2 reference's warmup-then-reuse pattern.

    Inputs:
        audio_bytes (bytes): the recorded audio, in whatever format the
        configured engine accepts (faster-whisper reads a NumPy array or a
        file-like object; the route task decodes the browser's upload into
        that shape before calling this)
        config (dict): parsed observe-config.json
        loader (callable): () -> model, injected for the suite; defaults to
        _default_loader, which imports faster_whisper lazily
        language (str | None): "auto", "en" or "fr" from the voice panel's
        dropdown, overriding config's voice.stt.language default for this
        one call; None means fall back to the configured default

    Outputs:
        text (str): the transcription, possibly empty when the recording
        carried no speech

    Raises:
        SttUnavailable: the configured engine could not be loaded (missing
        dependency, or the loader raised for any other reason).
    --------------------------------------------------------------------------
    """
    global _MODEL
    if _MODEL is None:
        try:
            _MODEL = (loader or (lambda: _default_loader(config)))()
        except Exception as exc:                           # noqa: BLE001
            raise SttUnavailable(
                f"the configured STT engine could not be loaded: "
                f"{type(exc).__name__}: {exc}. Install it with "
                "pip install -r .claude/skills/rt-observe/scripts/"
                "requirements-voice.txt") from exc
    dropdown_value = language or config["voice"]["stt"]["language"]["value"] or "auto"
    hint = _LANGUAGE_HINT.get(dropdown_value)
    segments, _info = _MODEL.transcribe(audio_bytes, language=hint)
    return "".join(segment.text for segment in segments).strip()
