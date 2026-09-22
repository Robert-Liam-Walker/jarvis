"""The resident process: one mic loop, one Jev client, one worker that drives the machine, spoken replies."""

from __future__ import annotations

import queue
import threading
import time

from . import stopkey
from .gates import Confirmer
from .voice.listener import Listener
from .voice.tts import Speaker


def _worker(inbox: queue.Queue, handle, speaking: threading.Event) -> None:
    """Run utterances one at a time on a thread that owns COM for UI Automation."""
    import uiautomation as auto

    with auto.UIAutomationInitializerInThread():
        while True:
            text = inbox.get()
            if text is None:
                return
            try:
                handle(text)
            except Exception as e:  # keep the daemon alive; the failure is spoken and logged
                print(f"jarvis: error: {e}", flush=True)


def listen(
    handle=None,
    device: int | None = None,
    hear_only: bool = False,
    wake_threshold: float = 0.6,
    confirmer: Confirmer | None = None,
) -> None:
    """Block on the microphone. `handle(text)` runs on the worker thread for every utterance.

    With `hear_only`, transcripts are printed and spoken back, and nothing is driven: a microphone and
    model check that needs no Jev key. While a confirmation question is pending, the next utterance
    answers it instead of starting a new request. Ctrl+Shift+Backspace stops the current run.
    """
    speaker = Speaker()
    inbox: queue.Queue = queue.Queue()
    stopkey.clear_stop()
    stopkey.start(on_stop=lambda: speaker.say("Stopping."))

    def on_utterance(text: str) -> None:
        print(f"heard: {text}", flush=True)
        if confirmer is not None and confirmer.answer(text):
            return
        if hear_only:
            speaker.say(f"I heard: {text}")
        else:
            inbox.put(text)

    def on_state(state: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {state}", flush=True)

    if not hear_only:
        threading.Thread(target=_worker, args=(inbox, handle, speaker.speaking), name="jarvis-worker", daemon=True).start()
    listener = Listener(on_utterance, on_state, device=device, wake_threshold=wake_threshold, speaking=speaker.speaking)
    speaker.say("Jarvis is listening.")
    try:
        listener.run()
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        inbox.put(None)
        speaker.close()
