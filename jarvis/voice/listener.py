"""Wake word, then record until the person stops talking, then transcribe, then hand over the words."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable

import numpy as np

from . import audio
from .stt import Transcriber
from .wake import WakeDetector

SILENCE_AFTER_SPEECH = 0.7  # seconds of quiet that ends an utterance
MAX_UTTERANCE = 8.0  # seconds
MIN_UTTERANCE = 0.4  # seconds of speech before quiet counts as an end
NOISE_FLOOR_FRAMES = 25  # 2 s of ambient audio to calibrate the energy gate


_WAKE_PREFIX = re.compile(r"^\W*(?:hey|hi|ok|okay|yo)?\W*jarvis\W*", re.IGNORECASE)


def strip_wake_phrase(text: str) -> str:
    """'Hey Jarvis! Open notepad.' -> 'Open notepad.' The wake phrase is often inside the recording."""
    return _WAKE_PREFIX.sub("", text, count=1).strip()


class Listener:
    def __init__(
        self,
        on_utterance: Callable[[str], None],
        on_state: Callable[[str], None] = lambda s: None,
        device: int | None = None,
        wake_threshold: float = 0.6,
        speaking: threading.Event | None = None,
    ):
        self.on_utterance = on_utterance
        self.on_state = on_state
        self.device = device
        self.speaking = speaking or threading.Event()
        self.paused = threading.Event()
        self._stop = threading.Event()
        self.wake = WakeDetector(threshold=wake_threshold)
        self.stt = Transcriber()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        floor = 0.0
        seen = 0
        recording: list[np.ndarray] = []
        speech_started: float | None = None
        last_voice = 0.0
        self.on_state("listening")
        for frame in audio.frames(self.device, self._stop.is_set):
            if self.paused.is_set() or self.speaking.is_set():
                continue
            level = audio.rms(frame)
            if seen < NOISE_FLOOR_FRAMES:
                floor = max(floor, level)
                seen += 1
                continue
            gate = max(floor * 2.5, 300.0)
            if not recording:
                if self.wake.triggered(frame):
                    self.on_state("heard wake word")
                    recording = [frame]
                    speech_started = None
                    last_voice = time.monotonic()
                continue
            recording.append(frame)
            now = time.monotonic()
            if level > gate:
                last_voice = now
                speech_started = speech_started or now
            total = len(recording) * audio.FRAME / audio.RATE
            spoke_enough = speech_started is not None and now - speech_started >= MIN_UTTERANCE
            quiet = now - last_voice >= SILENCE_AFTER_SPEECH
            if (spoke_enough and quiet) or total >= MAX_UTTERANCE or (speech_started is None and total >= 3.0):
                clip = np.concatenate(recording)
                recording = []
                if speech_started is None:
                    self.on_state("listening")
                    continue
                self.on_state("transcribing")
                result = self.stt.transcribe(clip)
                self.on_state("listening")
                text = strip_wake_phrase(result.text)
                if text:
                    self.on_utterance(text)
