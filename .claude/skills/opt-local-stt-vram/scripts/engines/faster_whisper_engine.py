"""
faster_whisper_engine - the faster-whisper (CTranslate2) adapter.

Accepts any name faster-whisper resolves: a size ("small", "large-v3-turbo") or a Hugging
Face repo id holding a CTranslate2 conversion. The CUDA DLL search path is set by
rt-observe's stt_engine.add_cuda_dll_dirs, imported rather than copied (R18), so the
benchmark loads Whisper exactly as the voice panel does.
"""
import importlib.util
import sys
from pathlib import Path

_PANEL_SCRIPTS = Path(__file__).resolve().parents[3] / "rt-observe" / "scripts"


def available() -> tuple:
    """Purpose: say whether faster-whisper is importable, without importing it."""
    if importlib.util.find_spec("faster_whisper") is None:
        return False, "faster-whisper is not installed in this interpreter"
    return True, ""


def download(model: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Fetch a model's weights into the Hugging Face cache (no-op when cached).

    Inputs:
        model (str): a faster-whisper size or a CTranslate2 repo id

    Outputs:
        None. Side effect: files under the Hugging Face cache directory.
    --------------------------------------------------------------------------
    """
    from faster_whisper.utils import download_model
    download_model(model)


def load(model: str, compute_type: str, device: str):
    """
    --------------------------------------------------------------------------
    Purpose:
        Load a model on the device, with the CUDA DLLs findable on Windows.

    Inputs:
        model (str): a faster-whisper size or a CTranslate2 repo id
        compute_type (str): e.g. "float16", "int8_float16"
        device (str): "cuda" or "cpu"

    Outputs:
        model (faster_whisper.WhisperModel): the loaded model
    --------------------------------------------------------------------------
    """
    if str(_PANEL_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_PANEL_SCRIPTS))
    import stt_engine
    stt_engine.add_cuda_dll_dirs(device)
    from faster_whisper import WhisperModel
    return WhisperModel(model, device=device, compute_type=compute_type)


def transcribe(handle, audio_path: str, language: str, options: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Transcribe one recording with the voice panel's options.

    Inputs:
        handle (WhisperModel): from load()
        audio_path (str): the recording
        language (str): "auto", "en" or "fr"
        options (dict): vad_filter, vad_min_silence_ms, condition_on_previous_text

    Outputs:
        text (str): the transcript, segments joined by a space
    --------------------------------------------------------------------------
    """
    segments, _ = handle.transcribe(
        audio_path, language=None if language == "auto" else language,
        vad_filter=options["vad_filter"],
        vad_parameters={"min_silence_duration_ms": options["vad_min_silence_ms"]},
        condition_on_previous_text=options["condition_on_previous_text"])
    return " ".join(s.text.strip() for s in segments).strip()
