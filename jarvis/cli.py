"""`jarvis say "<utterance>"` is the typed intent bar; `jarvis listen` is the voice loop; `jarvis watch` and
`jarvis status` are the persistent agent without and after a microphone."""

from __future__ import annotations

import argparse
import sys
import time

from .gates import Confirmer


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="Voice-first Jev computer use for Windows.")
    sub = parser.add_subparsers(dest="command", required=True)

    say = sub.add_parser("say", help="handle one utterance as if it had been spoken")
    say.add_argument("utterance")
    say.add_argument("--dry-run", action="store_true", help="decide but never click or type")

    listen = sub.add_parser("listen", help="wake word, then speech, then act; Ctrl-C to stop")
    listen.add_argument("--dry-run", action="store_true", help="decide but never click or type")
    listen.add_argument("--hear-only", action="store_true", help="only transcribe and echo; needs no Jev key")
    listen.add_argument("--device", help="input device index or name substring")
    listen.add_argument("--wake-threshold", type=float, default=0.6)
    listen.add_argument("--no-watch", action="store_true", help="voice only; do not run the observers")

    watch = sub.add_parser("watch", help="run the observers and the evaluator without a microphone; Ctrl-C to stop")
    watch.add_argument("--no-jev", action="store_true", help="standing rules only; needs no Jev key")

    status = sub.add_parser("status", help="print the world model and recent events from the store")
    status.add_argument("--events", type=int, default=15, help="how many recent events to show")

    args = parser.parse_args(argv)

    if args.command == "say":
        from .agent import Agent, make_client

        confirmer = Confirmer(ask=lambda q: None)
        confirmer.ask = lambda q: confirmer.answer(input(f"jarvis: {q} [yes/no] ").strip())  # typed answer, synchronous
        with make_client() as client:
            result = Agent(client, act=not args.dry_run, confirmer=confirmer).say(args.utterance)
        print(f"[{result.outcome} in {result.seconds}s, {result.steps} steps]")
        sys.exit(0 if result.outcome in ("done", "dry run") else 1)

    if args.command == "listen":
        from .agent import Agent, make_client
        from .daemon import Supervisor
        from .daemon import listen as run_listen
        from .voice.audio import pick_input_device

        device = pick_input_device(None if args.device is None or args.device.isdigit() else args.device)
        if args.device is not None and args.device.isdigit():
            device = int(args.device)
        if args.hear_only:
            supervisor = None if args.no_watch else Supervisor()
            run_listen(None, device=device, hear_only=True, wake_threshold=args.wake_threshold, supervisor=supervisor)
            return
        with make_client() as client:
            speaker_confirmer = Confirmer(ask=lambda q: None)
            agent = Agent(client, act=not args.dry_run, confirmer=speaker_confirmer)
            speaker_confirmer.ask = agent.narrate  # spoken question; the next utterance answers it
            supervisor = None if args.no_watch else Supervisor(client=client)
            run_listen(
                agent.say, device=device, wake_threshold=args.wake_threshold, confirmer=speaker_confirmer, supervisor=supervisor
            )
        return

    if args.command == "watch":
        from .daemon import Supervisor
        from .daemon import watch as run_watch

        if args.no_jev:
            run_watch(Supervisor())
            return
        from .agent import make_client

        with make_client() as client:
            run_watch(Supervisor(client=client))
        return

    if args.command == "status":
        print_status(args.events)


def print_status(events: int = 15) -> None:
    from .store import Store
    from .world import World

    with Store() as store:
        world = World(store)
        snap = world.snapshot()
        print(f"store: {store.path}")
        print(f"user: {snap['user'].get('presence')}")
        fg = snap["foreground"]
        print(f"foreground: {fg['title']!r} ({fg.get('exe')})" if fg else "foreground: unknown")
        print(f"processes: {snap['processes']['count']} known")
        if snap["jupyter"]:
            print(f"jupyter kernels: {', '.join(f'{k} {v.get("status")}' for k, v in snap['jupyter'].items())}")
        tasks = store.tasks(("pending", "active", "waiting_event", "waiting_approval", "waiting_host"))
        print(f"open tasks: {len(tasks)}")
        for t in tasks[:10]:
            print(f"  #{t['id']} {t['status']} {t['goal']!r} (attempts {t['attempts']})")
        print(f"recent events (last {events}):")
        for e in reversed(store.recent_events(events)):
            stamp = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
            about = e["payload"].get("name") or e["payload"].get("title") or e["payload"].get("text") or e["key"]
            print(f"  {stamp} {e['kind']:<18} {about} [{e['source']}]")
        decisions = store.recent_decisions(5)
        if decisions:
            print("recent decisions:")
            for d in reversed(decisions):
                stamp = time.strftime("%H:%M:%S", time.localtime(d["ts"]))
                a = d["answer"]
                print(
                    f"  {stamp} event #{d['event_id']} relevant={a.get('relevant')} action={a.get('action')} ({a.get('source')})"
                )


if __name__ == "__main__":
    main()
