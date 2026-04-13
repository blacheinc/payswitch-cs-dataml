"""Tests for customer service agent handlers."""

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Load customer-service modules by file path (avoid collision with other agents)
_agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "customer-service-agent"))


def _load_module(name: str, relative_path: str):
    """Load a module from the customer-service-agent directory by absolute path."""
    module_path = os.path.join(_agent_dir, relative_path)
    spec = importlib.util.spec_from_file_location(
        name,
        module_path,
        submodule_search_locations=[os.path.dirname(module_path)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load in dependency order: prompts → retriever → llm_client → handlers
_prompts = _load_module("cs_prompts", "modules/prompts.py")
_retriever = _load_module("cs_retriever", "modules/retriever.py")
_llm_client = _load_module("cs_llm_client", "modules/llm_client.py")

# Build a fake 'modules' package so handlers' relative imports resolve
import types
_modules_pkg = types.ModuleType("cs_modules_pkg")
_modules_pkg.prompts = _prompts
_modules_pkg.retriever = _retriever
_modules_pkg.llm_client = _llm_client
sys.modules["cs_modules_pkg"] = _modules_pkg

# Patch handlers' relative imports via monkey-loading
_handlers_path = os.path.join(_agent_dir, "modules", "handlers.py")
with open(_handlers_path, "r", encoding="utf-8") as f:
    _handlers_src = f.read()

# Rewrite relative imports to use our loaded modules
_handlers_src_patched = (
    _handlers_src
    .replace("from .llm_client import", "from cs_llm_client import")
    .replace("from .prompts import", "from cs_prompts import")
    .replace("from .retriever import", "from cs_retriever import")
)
_handlers_mod = types.ModuleType("cs_handlers")
exec(compile(_handlers_src_patched, _handlers_path, "exec"), _handlers_mod.__dict__)
sys.modules["cs_handlers"] = _handlers_mod

handle_explain_request = _handlers_mod.handle_explain_request
LLMError = _llm_client.LLMError


# ── Validation ─────────────────────────────────────────────────────────────

class TestValidation:
    def test_non_dict_payload_raises(self):
        with pytest.raises(ValueError, match="JSON object"):
            handle_explain_request(MagicMock(), "not a dict")

    def test_missing_question_raises(self):
        with pytest.raises(ValueError, match="'question' is required"):
            handle_explain_request(MagicMock(), {})

    def test_empty_question_raises(self):
        with pytest.raises(ValueError, match="'question' is required"):
            handle_explain_request(MagicMock(), {"question": ""})

    def test_non_string_question_raises(self):
        with pytest.raises(ValueError, match="'question'"):
            handle_explain_request(MagicMock(), {"question": 123})

    def test_question_too_long_raises(self):
        with pytest.raises(ValueError, match="2000 characters"):
            handle_explain_request(MagicMock(), {"question": "x" * 2001})

    def test_invalid_max_tokens_raises(self):
        with pytest.raises(ValueError, match="max_tokens"):
            handle_explain_request(MagicMock(), {"question": "hi", "max_tokens": "lots"})


# ── Happy path ─────────────────────────────────────────────────────────────

class TestHandleExplain:
    def _make_blob_client_with_decision(self):
        """Returns a mock blob client that returns a fake decision blob."""
        mock = MagicMock()
        mock_container = MagicMock()
        mock.get_container_client.return_value = mock_container

        import json as _json
        def get_blob(path):
            mock_blob = MagicMock()
            if "champions/current.json" in path:
                mock_blob.download_blob.return_value.readall.return_value = (
                    _json.dumps({"updated_at": "2026-04-11", "models": []}).encode("utf-8")
                )
            elif "REQ-test/" not in path and "/REQ-test.json" in path:
                mock_blob.download_blob.return_value.readall.return_value = (
                    _json.dumps({"request_id": "REQ-test", "decision": "DECLINE"}).encode("utf-8")
                )
            else:
                mock_blob.download_blob.side_effect = Exception("BlobNotFound")
            return mock_blob
        mock_container.get_blob_client.side_effect = get_blob
        return mock

    @patch("cs_handlers.call_llm")
    def test_happy_path_returns_answer(self, mock_call_llm):
        mock_call_llm.return_value = {
            "answer": "The decision was declined due to X.",
            "tokens_used": 150,
            "model": "gpt-4o-mini",
            "provider": "azure_openai",
        }

        result = handle_explain_request(
            self._make_blob_client_with_decision(),
            {"question": "Why was REQ-test declined?", "decision_id": "REQ-test"},
        )

        assert result["answer"] == "The decision was declined due to X."
        assert result["model"] == "gpt-4o-mini"
        assert result["tokens_used"] == 150
        assert "champion_snapshot" in result["context_used"]

    @patch("cs_handlers.call_llm")
    def test_max_tokens_capped(self, mock_call_llm):
        mock_call_llm.return_value = {
            "answer": "x", "tokens_used": 10, "model": "m", "provider": "p",
        }

        handle_explain_request(
            MagicMock(),
            {"question": "hi", "max_tokens": 99999},
        )

        # max_tokens should have been capped at 2000
        _, kwargs = mock_call_llm.call_args
        assert kwargs["max_tokens"] == 2000

    @patch("cs_handlers.call_llm")
    def test_max_tokens_minimum(self, mock_call_llm):
        mock_call_llm.return_value = {
            "answer": "x", "tokens_used": 10, "model": "m", "provider": "p",
        }

        handle_explain_request(
            MagicMock(),
            {"question": "hi", "max_tokens": 10},
        )

        _, kwargs = mock_call_llm.call_args
        assert kwargs["max_tokens"] == 50  # floor

    @patch("cs_handlers.call_llm")
    def test_llm_error_propagates(self, mock_call_llm):
        mock_call_llm.side_effect = LLMError("No provider configured")

        with pytest.raises(LLMError):
            handle_explain_request(MagicMock(), {"question": "hi"})
