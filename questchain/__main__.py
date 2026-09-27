"""Entry point for `python -m questchain`."""

import argparse
import platform
import shutil
import subprocess
import sys

from questchain.config import MODEL_PRESETS, OLLAMA_MODEL


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
        help="Command to run: 'start' (default) launches the CLI",
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
    """Update the installed tool directly, falling back to the installer without uv."""
    source = "git+https://github.com/RayP11/QuestChain@master"
    _WIN  = "https://raw.githubusercontent.com/RayP11/QuestChain/master/install.ps1"
    _UNIX = "https://raw.githubusercontent.com/RayP11/QuestChain/master/install.sh"

    print("Updating QuestChain...")

    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "tool", "install", source, "--reinstall"]
    elif platform.system() == "Windows":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        cmd = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-c", f"irm {_WIN} | iex"] if shell else None
    else:
        shell = shutil.which("bash")
        cmd = [shell, "-c", f"curl -fsSL {_UNIX} | bash"] if shell else None

    try:
        if cmd is None:
            raise FileNotFoundError("Neither uv nor a supported installer shell was found on PATH")
        if platform.system() == "Windows":
            from questchain.updater import handoff_windows_update
            handoff_windows_update(cmd)
            print("QuestChain will exit so the updater can replace its files.", flush=True)
            sys.exit(0)
        result = subprocess.run(cmd)
    except OSError as exc:
        print(f"Could not start the updater: {exc}", file=sys.stderr)
        print(f"Run this command in your terminal (install uv first if needed):\n"
              f"  uv tool install {source} --reinstall", file=sys.stderr)
        sys.exit(1)
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

    from questchain.cli import main as cli_main

    cli_main(
        model_name=args.model,
        thread_id=args.thread,
        use_memory=not args.no_memory,
        enable_web=args.web,
        web_host=args.web_host,
        web_port=args.web_port,
    )


if __name__ == "__main__":
    main()
