"""Explicit local-model routing evaluation; never runs specialist tools.

Run: python scripts/evaluate_routing.py --model qwen3:8b --output workspace/qa/routing.json
"""
import argparse
import asyncio
import json
import statistics
import tempfile
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from questchain.agents import PRESET_AGENTS, CLASS_GUIDANCE
from questchain.engine.agent import Agent
from questchain.engine import context
from questchain.engine.model import OllamaModel
from questchain.engine.tools import ToolRegistry
from questchain.runtime.routing import add_routing_tool


async def evaluate(model_name, output, cases_path):
    cases = json.loads(cases_path.read_text())
    router = next(a for a in PRESET_AGENTS if a["class_name"] == "Router")
    catalog = [{"id": a["class_name"], "name": a["name"], "class_name": a["class_name"],
                "when_to_call": CLASS_GUIDANCE[a["class_name"]], "when_not_to_call": "",
                "routing_examples": [], "tools": a["tools"]} for a in PRESET_AGENTS if a["class_name"] != "Router"]
    model = OllamaModel(model_name)
    model._options["temperature"] = 0
    results = []
    with tempfile.TemporaryDirectory(prefix="questchain-routing-eval-") as temp:
        original_data_dir = context.QUESTCHAIN_DATA_DIR
        context.QUESTCHAIN_DATA_DIR = Path(temp)
        try:
            for i, case in enumerate(cases, 1):
                history = []
                if case.get("previous"):
                    history = [{"role": "user", "content": case["previous"]},
                               {"role": "assistant", "content": "Handed this request to " + case["agent_id"] + "."}]
                decision = dict(action="reply", agent_id="", message="")
                async def route(agent_id, context=""):
                    if agent_id not in {a["id"] for a in catalog}:
                        raise ValueError("Unknown destination")
                    decision.update(action="dispatch", agent_id=agent_id, context=context)
                    return "Handed off."
                agent = Agent(model, ToolRegistry(), router["system_prompt"].replace("{agent_name}", router["name"]))
                add_routing_tool(agent, catalog, route)
                started = time.perf_counter()
                try:
                    decision["message"] = "".join([token async for token in agent.run(
                        case["request"], f"evaluation-{i}", initial_messages=history)])
                    expected = "reply" if case["action"] == "clarify" else case["action"]
                    correct = decision["action"] == expected and decision["agent_id"] == case.get("agent_id", "")
                    entry = dict(case=case, decision=decision, correct=correct, seconds=time.perf_counter() - started)
                except Exception as exc:
                    entry = dict(case=case, error=str(exc), correct=False, seconds=time.perf_counter() - started)
                results.append(entry)
                print(f"{i}/{len(cases)} {case['category']}: {'PASS' if entry['correct'] else 'FAIL'} ({entry['seconds']:.1f}s)", flush=True)
                output.parent.mkdir(parents=True, exist_ok=True)
                summary = {category: {"correct": sum(r["correct"] for r in results if r["case"]["category"] == category),
                                      "total": sum(r["case"]["category"] == category for r in results)}
                           for category in {r["case"]["category"] for r in results}}
                output.write_text(json.dumps(dict(model=model_name, summary=summary,
                                  median_seconds=statistics.median(r["seconds"] for r in results), results=results), indent=2))
        finally:
            context.QUESTCHAIN_DATA_DIR = original_data_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--output", type=Path, default=Path("workspace/qa/routing.json"))
    parser.add_argument("--cases", type=Path, default=Path("tests/fixtures/routing_evaluation.json"))
    args = parser.parse_args()
    asyncio.run(evaluate(args.model, args.output, args.cases))
