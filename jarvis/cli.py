"""`jarvis say "<utterance>"` is the typed intent bar; `jarvis listen` is the voice loop."""

from __future__ import annotations

import argparse
import sys

from .agent import Agent, make_client


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

    args = parser.parse_args(argv)

    if args.command == "say":
        with make_client() as client:
            result = Agent(client, act=not args.dry_run).say(args.utterance)
        print(f"[{result.outcome} in {result.seconds}s, {result.steps} steps]")
        sys.exit(0 if result.outcome in ("done", "dry run") else 1)

    if args.command == "listen":
        from .daemon import listen as run_listen
        from .voice.audio import pick_input_device

        device = pick_input_device(None if args.device is None or args.device.isdigit() else args.device)
        if args.device is not None and args.device.isdigit():
            device = int(args.device)
        if args.hear_only:
            run_listen(None, device=device, hear_only=True, wake_threshold=args.wake_threshold)
            return
        with make_client() as client:
            agent = Agent(client, act=not args.dry_run)
            run_listen(agent.say, device=device, wake_threshold=args.wake_threshold)


if __name__ == "__main__":
    main()
