#!/usr/bin/env python
"""Genie model benchmarking script.

Measures inference speed and response quality across multiple Ollama models.
Outputs a comparison table with TTFT (time to first token), total time, and
estimated tokens/second.

Usage::

    # Benchmark all presets available on your Ollama server
    python scripts/benchmark.py

    # Benchmark specific models
    python scripts/benchmark.py -m qwen3:8b qwen2.5:7b-instruct mistral:7b

    # Use a custom prompt set
    python scripts/benchmark.py --prompts "What is 2+2?" "Name the planets"

    # Save results to JSON
    python scripts/benchmark.py --output results.json
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Ensure the project root is on the path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table

from genie.config import MODEL_PRESETS, OLLAMA_BASE_URL
from genie.models import check_ollama_connection, get_model, list_available_models

console = Console()

# Default prompts cover a range of task types: factual recall, reasoning, and
# instruction-following — chosen to be short so benchmarks complete quickly.
DEFAULT_PROMPTS = [
    "What is the capital of France?",
    "Write a Python function to reverse a string.",
    "Explain the difference between a list and a tuple in one sentence.",
    "What is 17 multiplied by 23?",
    "Summarize the water cycle in two sentences.",
]


@dataclass
class PromptResult:
    prompt: str
    ttft_seconds: float  # time to first token
    total_seconds: float
    response: str
    estimated_tokens: int  # rough estimate based on character count
    error: str | None = None

    @property
    def tokens_per_second(self) -> float:
        if self.total_seconds <= 0:
            return 0.0
        return self.estimated_tokens / self.total_seconds


@dataclass
class ModelResult:
    model_name: str
    prompt_results: list[PromptResult] = field(default_factory=list)

    @property
    def avg_ttft(self) -> float:
        valid = [r.ttft_seconds for r in self.prompt_results if r.error is None]
        return sum(valid) / len(valid) if valid else 0.0

    @property
    def avg_total(self) -> float:
        valid = [r.total_seconds for r in self.prompt_results if r.error is None]
        return sum(valid) / len(valid) if valid else 0.0

    @property
    def avg_tps(self) -> float:
        valid = [r.tokens_per_second for r in self.prompt_results if r.error is None]
        return sum(valid) / len(valid) if valid else 0.0

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.prompt_results if r.error is not None)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token on average."""
    return max(1, len(text) // 4)


async def benchmark_model(model_name: str, prompts: list[str]) -> ModelResult:
    """Run all prompts against a single model and collect timing metrics."""
    result = ModelResult(model_name=model_name)

    try:
        model = get_model(model_name)
    except Exception as e:
        for prompt in prompts:
            result.prompt_results.append(
                PromptResult(
                    prompt=prompt,
                    ttft_seconds=0.0,
                    total_seconds=0.0,
                    response="",
                    estimated_tokens=0,
                    error=f"Model init failed: {e}",
                )
            )
        return result

    for prompt in prompts:
        t_start = time.perf_counter()
        t_first_token: float | None = None
        chunks: list[str] = []
        error: str | None = None

        try:
            async for chunk in model.astream(prompt):
                content = chunk.content if hasattr(chunk, "content") else str(chunk)
                if content and t_first_token is None:
                    t_first_token = time.perf_counter()
                chunks.append(content if isinstance(content, str) else "")
        except Exception as e:
            error = str(e)

        t_end = time.perf_counter()
        response = "".join(chunks)

        result.prompt_results.append(
            PromptResult(
                prompt=prompt,
                ttft_seconds=(t_first_token - t_start) if t_first_token else (t_end - t_start),
                total_seconds=t_end - t_start,
                response=response,
                estimated_tokens=_estimate_tokens(response),
                error=error,
            )
        )

    return result


def render_summary_table(results: list[ModelResult]) -> None:
    """Render a Rich comparison table of all model results."""
    table = Table(
        title="Model Benchmark Results",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Model", style="bold", min_width=24)
    table.add_column("Avg TTFT (s)", justify="right")
    table.add_column("Avg Total (s)", justify="right")
    table.add_column("Avg Tok/s", justify="right")
    table.add_column("Errors", justify="right")

    # Sort by avg total time (fastest first)
    sorted_results = sorted(results, key=lambda r: r.avg_total)

    for r in sorted_results:
        errors_cell = f"[red]{r.error_count}[/red]" if r.error_count else "[green]0[/green]"
        table.add_row(
            r.model_name,
            f"{r.avg_ttft:.2f}",
            f"{r.avg_total:.2f}",
            f"{r.avg_tps:.1f}",
            errors_cell,
        )

    console.print(table)


def render_detail_table(results: list[ModelResult], prompts: list[str]) -> None:
    """Render a per-prompt breakdown table."""
    table = Table(
        title="Per-Prompt Breakdown",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Prompt", max_width=40)
    for r in results:
        table.add_column(r.model_name, justify="right", min_width=12)

    for i, prompt in enumerate(prompts):
        short = prompt[:37] + "..." if len(prompt) > 40 else prompt
        row = [short]
        for r in results:
            pr = r.prompt_results[i]
            if pr.error:
                row.append("[red]ERR[/red]")
            else:
                row.append(f"{pr.total_seconds:.2f}s / {pr.tokens_per_second:.0f}t/s")
        table.add_row(*row)

    console.print(table)


def save_results(results: list[ModelResult], prompts: list[str], output_path: Path) -> None:
    """Save benchmark results to a JSON file."""
    data = {
        "prompts": prompts,
        "models": [
            {
                "model": r.model_name,
                "avg_ttft_seconds": r.avg_ttft,
                "avg_total_seconds": r.avg_total,
                "avg_tokens_per_second": r.avg_tps,
                "error_count": r.error_count,
                "prompts": [
                    {
                        "prompt": pr.prompt,
                        "ttft_seconds": pr.ttft_seconds,
                        "total_seconds": pr.total_seconds,
                        "estimated_tokens": pr.estimated_tokens,
                        "tokens_per_second": pr.tokens_per_second,
                        "response": pr.response,
                        "error": pr.error,
                    }
                    for pr in r.prompt_results
                ],
            }
            for r in results
        ],
    }
    output_path.write_text(json.dumps(data, indent=2))
    console.print(f"[green]Results saved to {output_path}[/green]")


async def run_benchmark(models: list[str], prompts: list[str]) -> list[ModelResult]:
    results: list[ModelResult] = []

    for model_name in models:
        console.print(f"\n[cyan]Benchmarking:[/cyan] [bold]{model_name}[/bold] ({len(prompts)} prompts)")
        result = await benchmark_model(model_name, prompts)
        results.append(result)

        # Show quick summary for this model as we go
        if result.error_count == len(prompts):
            console.print(f"  [red]All prompts failed.[/red]")
        else:
            console.print(
                f"  Avg TTFT: {result.avg_ttft:.2f}s  "
                f"Total: {result.avg_total:.2f}s  "
                f"Tok/s: {result.avg_tps:.1f}"
            )

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark Ollama models on speed and response quality.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-m", "--models",
        nargs="+",
        metavar="MODEL",
        help="Models to benchmark. Defaults to all presets available on your Ollama server.",
    )
    parser.add_argument(
        "--prompts",
        nargs="+",
        metavar="PROMPT",
        help="Custom prompts to use. Defaults to the built-in prompt set.",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Save results to a JSON file.",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Show per-prompt breakdown table in addition to the summary.",
    )
    parser.add_argument(
        "--base-url",
        default=OLLAMA_BASE_URL,
        help=f"Ollama server URL (default: {OLLAMA_BASE_URL})",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()

    if not check_ollama_connection(args.base_url):
        console.print(
            "[bold red]Cannot connect to Ollama![/bold red]\n"
            f"Make sure Ollama is running at {args.base_url}"
        )
        sys.exit(1)

    # Resolve model list
    if args.models:
        models_to_bench = args.models
    else:
        available = set(list_available_models(args.base_url))
        models_to_bench = [m for m in MODEL_PRESETS if m in available]
        if not models_to_bench:
            console.print(
                "[yellow]No preset models found on your Ollama server.[/yellow]\n"
                "Pull a model first (e.g. [cyan]ollama pull qwen3:8b[/cyan]) "
                "or specify models with [cyan]-m MODEL_NAME[/cyan]."
            )
            sys.exit(1)

    prompts = args.prompts or DEFAULT_PROMPTS

    console.print(f"[bold]Benchmarking {len(models_to_bench)} model(s) × {len(prompts)} prompt(s)[/bold]")

    results = await run_benchmark(models_to_bench, prompts)

    console.print()
    render_summary_table(results)

    if args.detail:
        console.print()
        render_detail_table(results, prompts)

    if args.output:
        save_results(results, prompts, Path(args.output))


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
