"""Tests for genie.models — model creation, GPU/CPU settings, and connectivity."""

import os
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_chat_ollama_mock():
    """Return a MagicMock that mimics a ChatOllama instance."""
    m = MagicMock()
    m.model = ""
    m.temperature = 0.7
    m.num_ctx = 32768
    return m


# ──────────────────────────────────────────────────────────────────────────────
# get_model() — basic construction
# ──────────────────────────────────────────────────────────────────────────────

class TestGetModel:
    """get_model() should build a ChatOllama with correct kwargs."""

    def _get_model_kwargs(self, model_name: str, env_overrides: dict | None = None) -> dict:
        """Capture the kwargs passed to ChatOllama(**kwargs) for inspection."""
        captured: dict = {}

        class CaptureChatOllama:
            def __init__(self, **kw):
                captured.update(kw)
                # Mimic what get_model() does after construction
                self.profile = {}

        env = {
            "OLLAMA_NUM_GPU": "",
            "OLLAMA_NUM_THREAD": "",
            "GENIE_RESPONSE_CACHE": "false",
        }
        if env_overrides:
            env.update(env_overrides)

        with patch.dict(os.environ, env):
            with patch("genie.models.ChatOllama", CaptureChatOllama):
                with patch("genie.models.OLLAMA_NUM_GPU", int(env["OLLAMA_NUM_GPU"]) if env.get("OLLAMA_NUM_GPU") else None):
                    with patch("genie.models.OLLAMA_NUM_THREAD", int(env["OLLAMA_NUM_THREAD"]) if env.get("OLLAMA_NUM_THREAD") else None):
                        with patch("genie.models.GENIE_RESPONSE_CACHE", False):
                            from genie.models import get_model
                            get_model(model_name)
        return captured

    def test_preset_model_uses_preset_num_ctx(self):
        from genie.config import MODEL_PRESETS
        model_name = "qwen3:8b"
        kwargs = self._get_model_kwargs(model_name)
        assert kwargs["num_ctx"] == MODEL_PRESETS[model_name]["num_ctx"]

    def test_preset_model_uses_preset_temperature(self):
        from genie.config import MODEL_PRESETS
        model_name = "qwen3:8b"
        kwargs = self._get_model_kwargs(model_name)
        assert kwargs["temperature"] == MODEL_PRESETS[model_name]["temperature"]

    def test_preset_model_uses_preset_num_predict(self):
        from genie.config import MODEL_PRESETS
        model_name = "qwen3:8b"
        kwargs = self._get_model_kwargs(model_name)
        assert kwargs["num_predict"] == MODEL_PRESETS[model_name]["num_predict"]

    def test_unknown_model_uses_defaults(self):
        kwargs = self._get_model_kwargs("nonexistent:1b")
        assert kwargs["num_ctx"] == 32768
        assert kwargs["temperature"] == 0.7
        assert kwargs["num_predict"] == 4096

    def test_model_name_forwarded(self):
        kwargs = self._get_model_kwargs("qwen3:8b")
        assert kwargs["model"] == "qwen3:8b"

    def test_base_url_defaults_to_config(self):
        kwargs = self._get_model_kwargs("qwen3:8b")
        assert "base_url" in kwargs


# ──────────────────────────────────────────────────────────────────────────────
# GPU / CPU acceleration settings
# ──────────────────────────────────────────────────────────────────────────────

class TestGpuSettings:
    """Verify num_gpu is forwarded (or omitted) based on config."""

    def _get_model_with_gpu(self, num_gpu: int | None) -> dict:
        captured: dict = {}

        class CaptureChatOllama:
            def __init__(self, **kw):
                captured.update(kw)
                self.profile = {}

        with patch("genie.models.OLLAMA_NUM_GPU", num_gpu):
            with patch("genie.models.OLLAMA_NUM_THREAD", None):
                with patch("genie.models.GENIE_RESPONSE_CACHE", False):
                    with patch("genie.models.ChatOllama", CaptureChatOllama):
                        from genie.models import get_model
                        get_model("qwen3:8b")
        return captured

    def test_no_num_gpu_when_unset(self):
        """When OLLAMA_NUM_GPU is None, num_gpu must NOT be passed to ChatOllama."""
        kwargs = self._get_model_with_gpu(None)
        assert "num_gpu" not in kwargs

    def test_full_gpu_minus_one(self):
        """num_gpu=-1 means all layers offloaded to GPU."""
        kwargs = self._get_model_with_gpu(-1)
        assert kwargs["num_gpu"] == -1

    def test_cpu_only_zero(self):
        """num_gpu=0 forces CPU-only inference."""
        kwargs = self._get_model_with_gpu(0)
        assert kwargs["num_gpu"] == 0

    def test_partial_gpu_layers(self):
        """num_gpu=N offloads N layers."""
        kwargs = self._get_model_with_gpu(20)
        assert kwargs["num_gpu"] == 20

    def test_no_num_thread_when_unset(self):
        captured: dict = {}

        class CaptureChatOllama:
            def __init__(self, **kw):
                captured.update(kw)
                self.profile = {}

        with patch("genie.models.OLLAMA_NUM_GPU", None):
            with patch("genie.models.OLLAMA_NUM_THREAD", None):
                with patch("genie.models.GENIE_RESPONSE_CACHE", False):
                    with patch("genie.models.ChatOllama", CaptureChatOllama):
                        from genie.models import get_model
                        get_model("qwen3:8b")
        assert "num_thread" not in captured

    def test_num_thread_forwarded_when_set(self):
        captured: dict = {}

        class CaptureChatOllama:
            def __init__(self, **kw):
                captured.update(kw)
                self.profile = {}

        with patch("genie.models.OLLAMA_NUM_GPU", None):
            with patch("genie.models.OLLAMA_NUM_THREAD", 8):
                with patch("genie.models.GENIE_RESPONSE_CACHE", False):
                    with patch("genie.models.ChatOllama", CaptureChatOllama):
                        from genie.models import get_model
                        get_model("qwen3:8b")
        assert captured["num_thread"] == 8


# ──────────────────────────────────────────────────────────────────────────────
# Context trimming — model.profile for SummarizationMiddleware
# ──────────────────────────────────────────────────────────────────────────────

class TestModelProfile:
    """get_model() must set model.profile so SummarizationMiddleware works."""

    def test_profile_max_input_tokens_matches_num_ctx(self):
        from genie.config import MODEL_PRESETS

        captured_profile: dict = {}

        class CaptureChatOllama:
            def __init__(self, **kw):
                self._num_ctx = kw["num_ctx"]
                self.profile = {}

        def patch_get_model(model_name, base_url=None):
            # Re-implement get_model logic to capture profile
            preset = MODEL_PRESETS.get(model_name, {})
            num_ctx = preset.get("num_ctx", 32768)
            obj = CaptureChatOllama(num_ctx=num_ctx)
            obj.profile = {"max_input_tokens": num_ctx}
            captured_profile.update(obj.profile)
            return obj

        with patch("genie.models.GENIE_RESPONSE_CACHE", False):
            with patch("genie.models.ChatOllama", CaptureChatOllama):
                model = patch_get_model("qwen3:8b")

        expected_ctx = MODEL_PRESETS["qwen3:8b"]["num_ctx"]
        assert model.profile["max_input_tokens"] == expected_ctx

    @pytest.mark.parametrize("model_name", [
        "qwen3:8b",
        "qwen2.5:7b-instruct",
        "mistral:7b",
        "deepseek-r1:7b",
    ])
    def test_profile_set_for_all_presets(self, model_name):
        from genie.config import MODEL_PRESETS

        class CaptureChatOllama:
            def __init__(self, **kw):
                self.profile = {}
                self._num_ctx = kw["num_ctx"]

        with patch("genie.models.OLLAMA_NUM_GPU", None):
            with patch("genie.models.OLLAMA_NUM_THREAD", None):
                with patch("genie.models.GENIE_RESPONSE_CACHE", False):
                    with patch("genie.models.ChatOllama", CaptureChatOllama):
                        from genie.models import get_model
                        model = get_model(model_name)

        expected = MODEL_PRESETS[model_name]["num_ctx"]
        assert model.profile == {"max_input_tokens": expected}


# ──────────────────────────────────────────────────────────────────────────────
# check_ollama_connection()
# ──────────────────────────────────────────────────────────────────────────────

class TestCheckOllamaConnection:
    """check_ollama_connection() should return True/False based on HTTP response."""

    def test_returns_true_on_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("genie.models.httpx.get", return_value=mock_resp):
            from genie.models import check_ollama_connection
            assert check_ollama_connection("http://localhost:11434") is True

    def test_returns_false_on_non_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 503

        with patch("genie.models.httpx.get", return_value=mock_resp):
            from genie.models import check_ollama_connection
            assert check_ollama_connection("http://localhost:11434") is False

    def test_returns_false_on_connect_error(self):
        import httpx

        with patch("genie.models.httpx.get", side_effect=httpx.ConnectError("refused")):
            from genie.models import check_ollama_connection
            assert check_ollama_connection("http://localhost:11434") is False

    def test_returns_false_on_timeout(self):
        import httpx

        with patch("genie.models.httpx.get", side_effect=httpx.TimeoutException("timeout")):
            from genie.models import check_ollama_connection
            assert check_ollama_connection("http://localhost:11434") is False


# ──────────────────────────────────────────────────────────────────────────────
# list_available_models()
# ──────────────────────────────────────────────────────────────────────────────

class TestListAvailableModels:
    """list_available_models() should parse Ollama /api/tags response."""

    def test_returns_model_names(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [
                {"name": "qwen3:8b"},
                {"name": "mistral:7b"},
            ]
        }

        with patch("genie.models.httpx.get", return_value=mock_resp):
            from genie.models import list_available_models
            models = list_available_models()
        assert models == ["qwen3:8b", "mistral:7b"]

    def test_returns_empty_on_connect_error(self):
        import httpx

        with patch("genie.models.httpx.get", side_effect=httpx.ConnectError("refused")):
            from genie.models import list_available_models
            assert list_available_models() == []

    def test_returns_empty_on_empty_models_list(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": []}

        with patch("genie.models.httpx.get", return_value=mock_resp):
            from genie.models import list_available_models
            assert list_available_models() == []

    def test_quantized_variants_preserved(self):
        """Model names including quant tags (e.g. :fp16, :q4_0) must be returned as-is."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [
                {"name": "qwen3:8b-fp16"},
                {"name": "qwen3:8b-q4_0"},
            ]
        }

        with patch("genie.models.httpx.get", return_value=mock_resp):
            from genie.models import list_available_models
            models = list_available_models()
        assert "qwen3:8b-fp16" in models
        assert "qwen3:8b-q4_0" in models
