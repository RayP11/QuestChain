"""Entry point for `python -m genie`."""

import argparse

from genie.config import MODEL_PRESETS, OLLAMA_MODEL


def parse_args():
    parser = argparse.ArgumentParser(
        prog="genie",
        description="Genie - A terminal-based AI agent powered by local Ollama models",
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
        "--telegram",
        action="store_true",
        help="Run as a Telegram bot instead of the terminal REPL",
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

    if args.telegram:
        import asyncio

        from genie.telegram import run_telegram_bot

        asyncio.run(run_telegram_bot(model_name=args.model))
        return

    from genie.cli import main as cli_main

    cli_main(
        model_name=args.model,
        thread_id=args.thread,
        use_memory=not args.no_memory,
    )


if __name__ == "__main__":
    main()
