"""Entry point for `python -m questchain`."""

import argparse

from questchain.config import DEFAULT_BUSY_WORK_MINUTES, MODEL_PRESETS, OLLAMA_MODEL


def parse_args():
    parser = argparse.ArgumentParser(
        prog="questchain",
        description="QuestChain - A terminal-based AI agent powered by local Ollama models",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["start"],
        default="start",
        help="Command to run (default: start)",
    )
    parser.add_argument(
        "-m", "--model",
        default=OLLAMA_MODEL,
        help=f"Ollama model to use (default: {OLLAMA_MODEL})",
    )
    parser.add_argument(
        "-t", "--thread",
        default=None,
        help="Resume a specific conversation thread by ID",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Disable persistent memory for this session",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available model presets and exit",
    )
    parser.add_argument(
        "--busy-work",
        type=int,
        default=DEFAULT_BUSY_WORK_MINUTES,
        metavar="MINUTES",
        help=f"Busy work interval in minutes (default: {DEFAULT_BUSY_WORK_MINUTES})",
    )
    parser.add_argument(
        "--no-busy-work",
        action="store_true",
        help="Disable the periodic busy work check",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.list_models:
        print("Model presets:")
        for name, preset in MODEL_PRESETS.items():
            marker = " <-- default" if name == OLLAMA_MODEL else ""
            print(f"  {name:20s} {preset['description']}{marker}")
        return

    busy_work_minutes = None if args.no_busy_work else args.busy_work

    from questchain.cli import main as cli_main

    cli_main(
        model_name=args.model,
        thread_id=args.thread,
        use_memory=not args.no_memory,
        busy_work_minutes=busy_work_minutes,
    )


if __name__ == "__main__":
    main()
