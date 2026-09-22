"""Speech to text with faster-whisper: CUDA float16 when the GPU is there, CPU int8 otherwise."""

from __future__ import annotations

import pathlib
import time
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Transcript:
    text: str
    seconds: float
    device: str


def _register_cuda_dlls() -> None:
    """Make the pip-installed cuBLAS and cuDNN DLLs loadable; they are not on PATH by default."""
    import os
    import site
    import sys

    roots = [pathlib.Path(p) for p in [*site.getsitepackages(), site.getusersitepackages()]]
    roots.append(pathlib.Path(sys.prefix) / "Lib" / "site-packages")
    for root in roots:
        for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin"):
            folder = root / sub
            if folder.is_dir() and hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(folder))
                os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")


class Transcriber:
    def __init__(self, size: str = "small.en"):
        _register_cuda_dlls()
        import ctranslate2
        from faster_whisper import WhisperModel

        if ctranslate2.get_cuda_device_count() > 0:
            self.device, compute = "cuda", "float16"
        else:
            self.device, compute = "cpu", "int8"
        self.model = WhisperModel(size, device=self.device, compute_type=compute)

    def transcribe(self, audio_int16: np.ndarray) -> Transcript:
        started = time.perf_counter()
        audio = audio_int16.astype(np.float32) / 32768.0
        segments, _info = self.model.transcribe(
            audio, language="en", beam_size=1, vad_filter=False, condition_on_previous_text=False
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return Transcript(text, round(time.perf_counter() - started, 2), self.device)
