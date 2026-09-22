"""'Hey Jarvis' detection on 80 ms frames with openWakeWord's bundled model."""

from __future__ import annotations

import pathlib
import time

import numpy as np


class WakeDetector:
    def __init__(self, model: str = "hey_jarvis", threshold: float = 0.6, cooldown: float = 1.5):
        import openwakeword
        from openwakeword.model import Model

        bundled = pathlib.Path(openwakeword.__file__).parent / "resources" / "models"
        candidates = sorted(bundled.glob(f"{model}*.onnx"))
        if not candidates:
            raise FileNotFoundError(f"no bundled wake-word model for {model!r} under {bundled}")
        self.model = Model(wakeword_model_paths=[str(candidates[-1])])
        self.name = model
        self.threshold = threshold
        self.cooldown = cooldown
        self._last = 0.0

    def feed(self, frame: np.ndarray) -> float:
        """Score this frame; returns the wake probability (0 to 1)."""
        scores = self.model.predict(frame)
        key = next(k for k in scores if self.name in k)
        return float(scores[key])

    def triggered(self, frame: np.ndarray) -> bool:
        score = self.feed(frame)
        now = time.monotonic()
        if score >= self.threshold and now - self._last >= self.cooldown:
            self._last = now
            self.model.reset()
            return True
        return False
