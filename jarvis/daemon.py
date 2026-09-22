"""The resident process: store, event bus, world model, observers, evaluator, then the voice loop on top.

`Supervisor` is the persistent part and runs without a microphone (`jarvis watch`). `listen` keeps its
signature: the voice loop is started last, unchanged, as one more source of events.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from . import rules as rules_mod
from . import stopkey
from .capabilities import Registry, default_registry
from .evaluate import Evaluator
from .events import Bus, Event
from .gates import Confirmer
from .notify import Notifier
from .observers import Observer
from .store import Store
from .world import World


class Supervisor:
    def __init__(
        self,
        home: Path | None = None,
        client=None,
        speak=None,
        observers: list[Observer] | None = None,
        rules: rules_mod.Rules | None = None,
        registry: Registry | None = None,
        lister=None,
        threaded: bool = True,
    ):
        self.store = Store(home / "jarvis.db" if home else None)
        self.rules = rules or rules_mod.load(home / "config.json" if home else None)
        self.bus = Bus(self.store, threaded=threaded)
        self.world = World(self.store)
        self.registry = registry or default_registry(speak)
        self.notifier = Notifier(speak, toasts=self.rules.toasts)
        self.evaluator = Evaluator(self.registry, self.world, self.notifier, self.rules, client=client, store=self.store)
        self.observers = observers if observers is not None else self._default_observers()
        self.lister = lister
        self.bus.subscribe("*", self.world.apply)
        self.bus.subscribe("*", self.evaluator.handle)
        self.started_at: float | None = None

    def _default_observers(self) -> list[Observer]:
        from .observers.foreground import ForegroundObserver
        from .observers.presence import PresenceObserver
        from .observers.processes import ProcessObserver
        from .observers.timer import TimerObserver

        return [ProcessObserver(), PresenceObserver(idle_after=self.rules.idle_after), TimerObserver(), ForegroundObserver()]

    def start(self) -> None:
        self.started_at = time.time()
        self.store.prune_events()
        demoted = self.store.demote_interrupted_tasks()
        if demoted:
            print(f"jarvis: {demoted} interrupted task(s) back to pending", flush=True)
        self.bus.start()
        lister = self.lister
        if lister is None:
            from .observers.processes import list_processes

            lister = list_processes
        started, stopped = self.world.reconcile(self.bus, lister())
        self.bus.drain()
        print(f"jarvis: reconciled {started} started, {stopped} stopped since last run", flush=True)
        for observer in self.observers:
            observer.start(self.bus)

    def stop(self) -> None:
        for observer in self.observers:
            try:
                observer.stop()
            except Exception as e:
                print(f"jarvis: stopping {observer.name}: {e}", flush=True)
        self.bus.drain()
        self.bus.stop()
        self.store.close()

    def publish(self, kind: str, key: str, source: str, payload: dict | None = None) -> None:
        self.bus.publish(Event(kind, key, source, payload or {}))

    def status(self) -> dict:
        return {
            "uptime_seconds": round(time.time() - self.started_at, 1) if self.started_at else None,
            "world": self.world.snapshot(),
            "events_delivered": self.bus.delivered,
            "duplicates": self.bus.duplicates,
            "decisions": len(self.evaluator.verdicts),
            "jev_skipped": self.evaluator.skipped,
        }


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
    supervisor: Supervisor | None = None,
) -> None:
    """Block on the microphone. `handle(text)` runs on the worker thread for every utterance.

    With `hear_only`, transcripts are printed and spoken back, and nothing is driven: a microphone and
    model check that needs no Jev key. While a confirmation question is pending, the next utterance
    answers it instead of starting a new request. Ctrl+Shift+Backspace stops the current run. With a
    `supervisor`, the observers run alongside and every utterance is also recorded as an event.
    """
    from .voice.listener import Listener
    from .voice.tts import Speaker

    speaker = Speaker()
    inbox: queue.Queue = queue.Queue()
    stopkey.clear_stop()
    stopkey.start(on_stop=lambda: speaker.say("Stopping."))

    def on_utterance(text: str) -> None:
        print(f"heard: {text}", flush=True)
        if supervisor is not None:
            supervisor.publish("user.utterance", "local", "voice", {"text": text})
        if confirmer is not None and confirmer.answer(text):
            return
        if hear_only:
            speaker.say(f"I heard: {text}")
        else:
            inbox.put(text)

    def on_state(state: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {state}", flush=True)

    if supervisor is not None:
        if supervisor.notifier._speak is None:
            supervisor.notifier._speak = speaker.say
        supervisor.start()
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
        if supervisor is not None:
            supervisor.stop()
        speaker.close()


def watch(supervisor: Supervisor) -> None:
    """Run the persistent part alone, no microphone, until Ctrl-C. Prints a status line every minute."""
    supervisor.start()
    print(f"jarvis: watching; state in {supervisor.store.path}", flush=True)
    try:
        while True:
            time.sleep(60)
            s = supervisor.status()
            print(
                f"[{time.strftime('%H:%M:%S')}] {s['events_delivered']} events, {s['decisions']} decisions, user {s['world']['user'].get('presence')}",
                flush=True,
            )
    except KeyboardInterrupt:
        pass
    finally:
        supervisor.stop()
