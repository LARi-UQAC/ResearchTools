"""
nemo_engine - the declared seam for NVIDIA NeMo models (Canary-Qwen 2.5B, parakeet).

Not implemented. Declared on 2026-09-26 at the operator's request for a machine whose GPU
can hold such models beside the resident LLM: on the 6 GB RTX A1000 this skill was built on,
Whisper large-v3 (1.5B parameters) already pushed 24% of the LLM out of VRAM. It reports
itself unavailable with that reason rather than pretending to run (R8), and its three
action functions refuse. Implementing it means adding nemo_toolkit and PyTorch to a pinned,
pip-audited requirement file and filling these three functions in.
"""


def available() -> tuple:
    """Purpose: always refuse, with the reason, until the adapter is implemented."""
    return False, ("the NeMo adapter is not implemented yet (it needs nemo_toolkit, PyTorch, "
                   "and a GPU with room for a 2.5B-parameter model beside the resident LLM)")


def download(model: str) -> None:
    """Purpose: refuse. Raises: NotImplementedError always."""
    raise NotImplementedError("nemo_engine.download is not implemented")


def load(model: str, compute_type: str, device: str):
    """Purpose: refuse. Raises: NotImplementedError always."""
    raise NotImplementedError("nemo_engine.load is not implemented")


def transcribe(handle, audio_path: str, language: str, options: dict) -> str:
    """Purpose: refuse. Raises: NotImplementedError always."""
    raise NotImplementedError("nemo_engine.transcribe is not implemented")
