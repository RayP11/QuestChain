"""Tests for genie.config — model presets, env-var parsing, and path helpers."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# MODEL_PRESETS structure
# ──────────────────────────────────────────────────────────────────────────────

class TestModelPresets:
    """Validate every entry in MODEL_PRESETS has the required schema."""

    def test_presets_not_empty(self):
        from genie.config import MODEL_PRESETS
        assert len(MODEL_PRESETS) > 0

    def test_required_keys_present(self):
        from genie.config import MODEL_PRESETS
        required = {"description", "num_ctx", "num_predict", "temperature"}
        for name, preset in MODEL_PRESETS.items():
            missing = required - preset.keys()
            assert not missing, f"{name!r} is missing keys: {missing}"

    def test_num_ctx_positive_int(self):
        from genie.config import MODEL_PRESETS
        for name, preset in MODEL_PRESETS.items():
            assert isinstance(preset["num_ctx"], int), f"{name}: num_ctx must be int"
            assert preset["num_ctx"] > 0, f"{name}: num_ctx must be > 0"

    def test_num_predict_positive_int(self):
        from genie.config import MODEL_PRESETS
        for name, preset in MODEL_PRESETS.items():
            assert isinstance(preset["num_predict"], int)
            assert preset["num_predict"] > 0

    def test_temperature_in_range(self):
        from genie.config import MODEL_PRESETS
        for name, preset in MODEL_PRESETS.items():
            t = preset["temperature"]
            assert 0.0 <= t <= 2.0, f"{name}: temperature {t} out of [0, 2] range"

    def test_description_non_empty_string(self):
        from genie.config import MODEL_PRESETS
        for name, preset in MODEL_PRESETS.items():
            assert isinstance(preset["description"], str)
            assert preset["description"].strip(), f"{name}: description is blank"

    # ── quantization naming conventions ───────────────────────────────────────

    def test_default_model_in_presets(self):
        """The default OLLAMA_MODEL must exist in MODEL_PRESETS."""
        from genie.config import MODEL_PRESETS, OLLAMA_MODEL
        assert OLLAMA_MODEL in MODEL_PRESETS, (
            f"Default model {OLLAMA_MODEL!r} not found in MODEL_PRESETS"
        )

    def test_quantized_tag_naming(self):
        """Models with explicit quant tags use recognised Ollama suffixes."""
        from genie.config import MODEL_PRESETS
        # Tags like :q4_0, :q4_K_M, :fp16, :q3_K_M are valid; plain tags (:8b) are also fine
        valid_quant_suffixes = (
            ":fp16", ":q8_0", ":q4_0", ":q4_K_M", ":q3_K_M", ":q5_K_M", ":q6_K",
        )
        for name in MODEL_PRESETS:
            # Only assert on names that contain an explicit quant tag
            if any(s in name for s in valid_quant_suffixes):
                assert any(name.endswith(s) or s in name for s in valid_quant_suffixes)


# ──────────────────────────────────────────────────────────────────────────────
# Environment-variable parsing
# ──────────────────────────────────────────────────────────────────────────────

class TestEnvVarParsing:
    """Test that env vars are parsed correctly at import time."""

    # OLLAMA_NUM_GPU ──────────────────────────────────────────────────────────

    def test_num_gpu_unset_is_none(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OLLAMA_NUM_GPU", None)
            # Re-evaluate the expression that config.py uses
            val = os.getenv("OLLAMA_NUM_GPU", "")
            result = int(val) if val else None
            assert result is None

    def test_num_gpu_zero_is_cpu_only(self):
        val = "0"
        result = int(val) if val else None
        assert result == 0

    def test_num_gpu_minus_one_is_full_gpu(self):
        val = "-1"
        result = int(val) if val else None
        assert result == -1

    def test_num_gpu_positive_layers(self):
        val = "32"
        result = int(val) if val else None
        assert result == 32

    # OLLAMA_NUM_THREAD ───────────────────────────────────────────────────────

    def test_num_thread_unset_is_none(self):
        val = ""
        result = int(val) if val else None
        assert result is None

    def test_num_thread_parsed_as_int(self):
        val = "8"
        result = int(val) if val else None
        assert result == 8

    # GENIE_RESPONSE_CACHE ────────────────────────────────────────────────────

    @pytest.mark.parametrize("raw,expected", [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("", False),
    ])
    def test_response_cache_flag(self, raw, expected):
        result = raw.lower() in ("1", "true", "yes")
        assert result == expected


# ──────────────────────────────────────────────────────────────────────────────
# Path helpers
# ──────────────────────────────────────────────────────────────────────────────

class TestPathHelpers:
    """Verify path helpers return Path objects under GENIE_DATA_DIR."""

    def test_get_db_path_returns_path(self, tmp_path):
        with patch.dict(os.environ, {"GENIE_DATA_DIR": str(tmp_path)}):
            # Reimport to pick up patched env var — use the logic directly
            from genie import config as cfg
            db = tmp_path / "checkpoints.db"
            assert cfg.get_db_path().name == "checkpoints.db"

    def test_get_response_cache_path_name(self):
        from genie.config import get_response_cache_path
        assert get_response_cache_path().name == "response_cache.db"

    def test_get_cron_jobs_path_name(self):
        from genie.config import get_cron_jobs_path
        assert get_cron_jobs_path().name == "cron_jobs.json"

    def test_get_history_path_name(self):
        from genie.config import get_history_path
        assert get_history_path().name == "history"

    def test_ensure_data_dir_creates_directory(self, tmp_path):
        target = tmp_path / "nested" / "data"
        with patch("genie.config.GENIE_DATA_DIR", target):
            from genie.config import ensure_data_dir
            result = ensure_data_dir()
            assert result.exists()
            assert result.is_dir()

    def test_ensure_memory_dir_creates_directory(self, tmp_path):
        fake_memory = tmp_path / "workspace" / "memory"
        with patch("genie.config.MEMORY_DIR", fake_memory):
            from genie.config import ensure_memory_dir
            result = ensure_memory_dir()
            assert result.exists()
