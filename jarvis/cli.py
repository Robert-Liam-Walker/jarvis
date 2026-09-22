"""`jarvis say "<utterance>"`: the typed intent bar, and the harness the voice loop feeds."""

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
    args = parser.parse_args(argv)

    if args.command == "say":
        with make_client() as client:
            result = Agent(client, act=not args.dry_run).say(args.utterance)
        print(f"[{result.outcome} in {result.seconds}s, {result.steps} steps]")
        sys.exit(0 if result.outcome in ("done", "dry run") else 1)


if __name__ == "__main__":
    main()
