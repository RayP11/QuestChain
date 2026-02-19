"""Tests for scripts/benchmark.py — data classes, metrics, I/O, and async runner."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make sure scripts/ is importable without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.benchmark import (
    DEFAULT_PROMPTS,
    ModelResult,
    PromptResult,
    _estimate_tokens,
    benchmark_model,
    save_results,
)


# ──────────────────────────────────────────────────────────────────────────────
# _estimate_tokens()
# ──────────────────────────────────────────────────────────────────────────────

class TestEstimateTokens:
    """Rough token estimator: ~4 chars per token, minimum 1."""

    def test_empty_string_returns_one(self):
        assert _estimate_tokens("") == 1

    def test_four_chars_is_one_token(self):
        assert _estimate_tokens("abcd") == 1

    def test_eight_chars_is_two_tokens(self):
        assert _estimate_tokens("abcdefgh") == 2

    def test_long_text(self):
        text = "a" * 400
        assert _estimate_tokens(text) == 100

    def test_single_char_returns_one(self):
        assert _estimate_tokens("x") == 1

    def test_unicode_uses_char_count(self):
        # 8 unicode chars → 2 tokens
        assert _estimate_tokens("αβγδεζηθ") == 2


# ──────────────────────────────────────────────────────────────────────────────
# PromptResult
# ──────────────────────────────────────────────────────────────────────────────

class TestPromptResult:
    """PromptResult.tokens_per_second computed correctly."""

    def test_tokens_per_second_basic(self):
        pr = PromptResult(
            prompt="hello",
            ttft_seconds=0.1,
            total_seconds=2.0,
            response="x" * 200,  # 50 tokens
            estimated_tokens=50,
        )
        assert pr.tokens_per_second == pytest.approx(25.0)

    def test_tokens_per_second_zero_total_returns_zero(self):
        pr = PromptResult(
            prompt="hello",
            ttft_seconds=0.0,
            total_seconds=0.0,
            response="x" * 100,
            estimated_tokens=25,
        )
        assert pr.tokens_per_second == 0.0

    def test_error_field_defaults_to_none(self):
        pr = PromptResult(
            prompt="p", ttft_seconds=0.1, total_seconds=1.0,
            response="r", estimated_tokens=1,
        )
        assert pr.error is None

    def test_error_field_stored(self):
        pr = PromptResult(
            prompt="p", ttft_seconds=0.0, total_seconds=0.0,
            response="", estimated_tokens=0, error="Connection refused",
        )
        assert pr.error == "Connection refused"


# ──────────────────────────────────────────────────────────────────────────────
# ModelResult — aggregate metrics
# ──────────────────────────────────────────────────────────────────────────────

class TestModelResult:
    """ModelResult aggregate properties use only successful (non-error) results."""

    def _make_result(self, ttft, total, tokens, error=None):
        return PromptResult(
            prompt="q",
            ttft_seconds=ttft,
            total_seconds=total,
            response="x" * (tokens * 4),
            estimated_tokens=tokens,
            error=error,
        )

    def test_avg_ttft(self):
        mr = ModelResult(model_name="test")
        mr.prompt_results = [
            self._make_result(0.1, 1.0, 10),
            self._make_result(0.3, 2.0, 20),
        ]
        assert mr.avg_ttft == pytest.approx(0.2)

    def test_avg_total(self):
        mr = ModelResult(model_name="test")
        mr.prompt_results = [
            self._make_result(0.1, 1.0, 10),
            self._make_result(0.1, 3.0, 30),
        ]
        assert mr.avg_total == pytest.approx(2.0)

    def test_avg_tps(self):
        mr = ModelResult(model_name="test")
        mr.prompt_results = [
            self._make_result(0.1, 2.0, 20),   # 10 tps
            self._make_result(0.1, 4.0, 40),   # 10 tps
        ]
        assert mr.avg_tps == pytest.approx(10.0)

    def test_error_count(self):
        mr = ModelResult(model_name="test")
        mr.prompt_results = [
            self._make_result(0.1, 1.0, 10),
            self._make_result(0.0, 0.0, 0, error="fail"),
            self._make_result(0.0, 0.0, 0, error="fail"),
        ]
        assert mr.error_count == 2

    def test_errors_excluded_from_averages(self):
        mr = ModelResult(model_name="test")
        mr.prompt_results = [
            self._make_result(1.0, 5.0, 50),
            self._make_result(0.0, 0.0, 0, error="boom"),
        ]
        assert mr.avg_ttft == pytest.approx(1.0)
        assert mr.avg_total == pytest.approx(5.0)

    def test_all_errors_returns_zero_averages(self):
        mr = ModelResult(model_name="test")
        mr.prompt_results = [
            self._make_result(0.0, 0.0, 0, error="e1"),
            self._make_result(0.0, 0.0, 0, error="e2"),
        ]
        assert mr.avg_ttft == 0.0
        assert mr.avg_total == 0.0
        assert mr.avg_tps == 0.0

    def test_empty_prompt_results(self):
        mr = ModelResult(model_name="test")
        assert mr.avg_ttft == 0.0
        assert mr.avg_total == 0.0
        assert mr.avg_tps == 0.0
        assert mr.error_count == 0


# ──────────────────────────────────────────────────────────────────────────────
# save_results() — JSON output validation
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveResults:
    """save_results() writes valid, well-structured JSON."""

    def _build_model_result(self, model_name: str) -> ModelResult:
        mr = ModelResult(model_name=model_name)
        mr.prompt_results = [
            PromptResult(
                prompt="What is 2+2?",
                ttft_seconds=0.12,
                total_seconds=1.5,
                response="The answer is 4.",
                estimated_tokens=4,
            )
        ]
        return mr

    def test_output_file_is_valid_json(self, tmp_path):
        out = tmp_path / "results.json"
        results = [self._build_model_result("qwen3:8b")]
        save_results(results, ["What is 2+2?"], out)
        data = json.loads(out.read_text())
        assert isinstance(data, dict)

    def test_top_level_keys(self, tmp_path):
        out = tmp_path / "results.json"
        results = [self._build_model_result("qwen3:8b")]
        save_results(results, ["What is 2+2?"], out)
        data = json.loads(out.read_text())
        assert "prompts" in data
        assert "models" in data

    def test_prompts_list_preserved(self, tmp_path):
        out = tmp_path / "results.json"
        prompts = ["prompt one", "prompt two"]
        results = []
        save_results(results, prompts, out)
        data = json.loads(out.read_text())
        assert data["prompts"] == prompts

    def test_model_entry_has_required_fields(self, tmp_path):
        out = tmp_path / "results.json"
        results = [self._build_model_result("qwen3:8b")]
        save_results(results, ["What is 2+2?"], out)
        data = json.loads(out.read_text())
        m = data["models"][0]
        for field in ("model", "avg_ttft_seconds", "avg_total_seconds",
                      "avg_tokens_per_second", "error_count", "prompts"):
            assert field in m, f"Missing field: {field}"

    def test_per_prompt_entry_has_required_fields(self, tmp_path):
        out = tmp_path / "results.json"
        results = [self._build_model_result("qwen3:8b")]
        save_results(results, ["What is 2+2?"], out)
        data = json.loads(out.read_text())
        pr = data["models"][0]["prompts"][0]
        for field in ("prompt", "ttft_seconds", "total_seconds",
                      "estimated_tokens", "tokens_per_second", "response", "error"):
            assert field in pr, f"Missing per-prompt field: {field}"

    def test_multiple_models_saved(self, tmp_path):
        out = tmp_path / "results.json"
        results = [
            self._build_model_result("qwen3:8b"),
            self._build_model_result("mistral:7b"),
        ]
        save_results(results, ["What is 2+2?"], out)
        data = json.loads(out.read_text())
        assert len(data["models"]) == 2
        model_names = {m["model"] for m in data["models"]}
        assert model_names == {"qwen3:8b", "mistral:7b"}

    def test_error_field_null_when_no_error(self, tmp_path):
        out = tmp_path / "results.json"
        results = [self._build_model_result("qwen3:8b")]
        save_results(results, ["What is 2+2?"], out)
        data = json.loads(out.read_text())
        pr = data["models"][0]["prompts"][0]
        assert pr["error"] is None

    def test_numeric_metrics_are_floats(self, tmp_path):
        out = tmp_path / "results.json"
        results = [self._build_model_result("qwen3:8b")]
        save_results(results, ["What is 2+2?"], out)
        data = json.loads(out.read_text())
        m = data["models"][0]
        assert isinstance(m["avg_ttft_seconds"], float)
        assert isinstance(m["avg_total_seconds"], float)
        assert isinstance(m["avg_tokens_per_second"], float)


# ──────────────────────────────────────────────────────────────────────────────
# benchmark_model() — async runner with mocked ChatOllama
# ──────────────────────────────────────────────────────────────────────────────

class TestBenchmarkModel:
    """benchmark_model() collects timing and response data from a mocked model."""

    def _make_streaming_model(self, chunks: list[str]):
        """Return a mock model whose astream() yields the given string chunks."""
        async def _astream(prompt):
            for c in chunks:
                msg = MagicMock()
                msg.content = c
                yield msg

        mock_model = MagicMock()
        mock_model.astream = _astream
        return mock_model

    def test_successful_prompt_has_no_error(self):
        mock_model = self._make_streaming_model(["Hello", " world"])

        with patch("scripts.benchmark.get_model", return_value=mock_model):
            result = asyncio.run(benchmark_model("qwen3:8b", ["Hi"]))

        assert result.prompt_results[0].error is None

    def test_response_is_concatenated_chunks(self):
        mock_model = self._make_streaming_model(["Paris", " is", " the", " capital"])

        with patch("scripts.benchmark.get_model", return_value=mock_model):
            result = asyncio.run(benchmark_model("qwen3:8b", ["Capital of France?"]))

        assert result.prompt_results[0].response == "Paris is the capital"

    def test_multiple_prompts_produce_multiple_results(self):
        mock_model = self._make_streaming_model(["ok"])

        with patch("scripts.benchmark.get_model", return_value=mock_model):
            result = asyncio.run(benchmark_model("qwen3:8b", ["p1", "p2", "p3"]))

        assert len(result.prompt_results) == 3

    def test_timing_is_non_negative(self):
        mock_model = self._make_streaming_model(["response"])

        with patch("scripts.benchmark.get_model", return_value=mock_model):
            result = asyncio.run(benchmark_model("qwen3:8b", ["test"]))

        pr = result.prompt_results[0]
        assert pr.ttft_seconds >= 0
        assert pr.total_seconds >= 0
        assert pr.total_seconds >= pr.ttft_seconds

    def test_model_init_failure_fills_error_results(self):
        with patch("scripts.benchmark.get_model", side_effect=RuntimeError("no such model")):
            result = asyncio.run(benchmark_model("missing:model", ["p1", "p2"]))

        assert len(result.prompt_results) == 2
        for pr in result.prompt_results:
            assert pr.error is not None
            assert "Model init failed" in pr.error

    def test_stream_exception_recorded_as_error(self):
        async def _failing_astream(prompt):
            raise ConnectionError("server down")
            yield  # make it a generator

        mock_model = MagicMock()
        mock_model.astream = _failing_astream

        with patch("scripts.benchmark.get_model", return_value=mock_model):
            result = asyncio.run(benchmark_model("qwen3:8b", ["p1"]))

        assert result.prompt_results[0].error is not None

    def test_estimated_tokens_non_zero_for_non_empty_response(self):
        mock_model = self._make_streaming_model(["a" * 40])  # 10 tokens

        with patch("scripts.benchmark.get_model", return_value=mock_model):
            result = asyncio.run(benchmark_model("qwen3:8b", ["test"]))

        assert result.prompt_results[0].estimated_tokens >= 1

    def test_model_name_stored(self):
        mock_model = self._make_streaming_model(["ok"])

        with patch("scripts.benchmark.get_model", return_value=mock_model):
            result = asyncio.run(benchmark_model("qwen3:8b", ["test"]))

        assert result.model_name == "qwen3:8b"


# ──────────────────────────────────────────────────────────────────────────────
# DEFAULT_PROMPTS sanity checks
# ──────────────────────────────────────────────────────────────────────────────

class TestDefaultPrompts:
    """The built-in prompt set must be non-trivial and well-formed."""

    def test_at_least_three_prompts(self):
        assert len(DEFAULT_PROMPTS) >= 3

    def test_all_non_empty_strings(self):
        for p in DEFAULT_PROMPTS:
            assert isinstance(p, str)
            assert p.strip()

    def test_no_duplicate_prompts(self):
        assert len(DEFAULT_PROMPTS) == len(set(DEFAULT_PROMPTS))
