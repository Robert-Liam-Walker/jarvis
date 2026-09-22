"""Spoken replies through Windows SAPI, off the calling thread, one utterance at a time."""

from __future__ import annotations

import queue
import threading


class Speaker:
    def __init__(self, rate: int = 185, echo: bool = True):
        self.echo = echo
        self._q: queue.Queue[str | None] = queue.Queue()
        self.speaking = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(rate,), name="jarvis-tts", daemon=True)
        self._thread.start()

    def say(self, text: str) -> None:
        if text:
            if self.echo:
                print(f"jarvis: {text}", flush=True)
            self._q.put(text)

    def close(self) -> None:
        self._q.put(None)

    def _loop(self, rate: int) -> None:
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", rate)
        while True:
            text = self._q.get()
            if text is None:
                return
            self.speaking.set()
            try:
                engine.say(text)
                engine.runAndWait()
            finally:
                self.speaking.clear()
