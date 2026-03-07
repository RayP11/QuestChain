"""Entry point for `python -m questchain`."""

import argparse
import logging
import os
import platform
import subprocess
import sys
import warnings

# Suppress noisy output from the deepagents SummarizationMiddleware — it
# tries to write conversation history to the filesystem backend which can
# fail in normal use.  These are recoverable non-fatal events.
logging.getLogger("deepagents.middleware.summarization").setLevel(logging.ERROR)
logging.getLogger("deepagents").setLevel(logging.ERROR)
warnings.filterwarnings(
    "ignore",
    message=".*summarization.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=".*Offloading conversation history.*",
    category=UserWarning,
)

from questchain.config import DEFAULT_QUEST_MINUTES, MODEL_PRESETS, OLLAMA_MODEL


def parse_args():
    parser = argparse.ArgumentParser(
        prog="questchain",
        description="QuestChain - A terminal-based AI agent powered by local Ollama models",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["start", "web"],
        default="start",
        help="Command to run: 'start' (default) launches the CLI, 'web' starts only the web UI",
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
        "--quests",
        type=int,
        default=DEFAULT_QUEST_MINUTES,
        metavar="MINUTES",
        help=f"Quest runner interval in minutes (default: {DEFAULT_QUEST_MINUTES})",
    )
    parser.add_argument(
        "--no-quests",
        action="store_true",
        help="Disable the periodic quest runner",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start the web UI alongside the CLI",
    )
    parser.add_argument(
        "--web-host",
        default="127.0.0.1",
        metavar="HOST",
        help="Web UI host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8765,
        metavar="PORT",
        help="Web UI port (default: 8765)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update QuestChain to the latest version and exit",
    )
    return parser.parse_args()


def do_update() -> None:
    """Re-run the appropriate installer to update QuestChain."""
    _WIN  = "https://raw.githubusercontent.com/RayP11/QuestChain/main/install.ps1"
    _UNIX = "https://raw.githubusercontent.com/RayP11/QuestChain/main/install.sh"

    print("Updating QuestChain...")

    if platform.system() == "Windows":
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-c",
               f"irm {_WIN} | iex"]
    else:
        cmd = ["bash", "-c", f"curl -fsSL {_UNIX} | bash"]

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def main():
    args = parse_args()

    if args.update:
        do_update()
        return

    if args.list_models:
        print("Model presets:")
        for name, preset in MODEL_PRESETS.items():
            marker = " <-- default" if name == OLLAMA_MODEL else ""
            print(f"  {name:20s} {preset['description']}{marker}")
        return

    if args.command == "web":
        import asyncio
        from questchain.cli import web_only
        asyncio.run(web_only(host=args.web_host, port=args.web_port))
        return

    quest_minutes = None if args.no_quests else args.quests

    from questchain.cli import main as cli_main

    cli_main(
        model_name=args.model,
        thread_id=args.thread,
        use_memory=not args.no_memory,
        quest_minutes=quest_minutes,
        enable_web=args.web,
        web_host=args.web_host,
        web_port=args.web_port,
    )


if __name__ == "__main__":
    main()
