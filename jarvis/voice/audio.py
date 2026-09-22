"""16 kHz mono microphone frames, 80 ms at a time, which is what the wake-word model expects."""

from __future__ import annotations

import contextlib
import queue
from collections.abc import Iterator

import numpy as np
import sounddevice as sd

RATE = 16_000
FRAME = 1_280  # samples per chunk: 80 ms at 16 kHz


def pick_input_device(preferred: str | None = None) -> int | None:
    """An input device index: the named one, else the first whose name says microphone, else the default."""
    devices = sd.query_devices()
    inputs = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    if preferred:
        for i, d in inputs:
            if preferred.lower() in d["name"].lower():
                return i
    for i, d in inputs:
        if "microphone" in d["name"].lower() or "mic" in d["name"].lower():
            return i
    default = sd.default.device[0]
    return None if default is None or default < 0 else default


def frames(device: int | None = None, stop=None) -> Iterator[np.ndarray]:
    """Yield int16 frames of FRAME samples until `stop()` is true. Blocks between frames."""
    q: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)

    def callback(indata, frame_count, time_info, status):
        with contextlib.suppress(queue.Full):
            q.put_nowait(indata[:, 0].copy())

    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME, device=device, callback=callback):
        while not (stop and stop()):
            try:
                yield q.get(timeout=0.5)
            except queue.Empty:
                continue


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) if frame.size else 0.0
