"""Tests for fraud detection agent validator module."""

import importlib.util
import os
import sys

import pytest

_agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "training-agents", "fraud-detection-agent"))
_spec = importlib.util.spec_from_file_location("fd_validator", os.path.join(_agent_dir, "modules", "validator.py"),
                                                submodule_search_locations=[_agent_dir])
_validator = importlib.util.module_from_spec(_spec)
sys.modules["fd_validator"] = _validator
_spec.loader.exec_module(_validator)

validate_distribution = _validator.validate_distribution


# ── Tests: validate_distribution ──────────────────────────────────────────


class TestValidateDistribution:
    def test_valid_distribution_no_warnings(self):
        training_info = {
            "low_pct": 0.93,
            "medium_pct": 0.06,
            "high_pct": 0.01,
        }
        warnings = validate_distribution(training_info)
        assert warnings == []

    def test_low_pct_too_low(self):
        training_info = {
            "low_pct": 0.85,  # below 0.90
            "medium_pct": 0.06,
            "high_pct": 0.01,
        }
        warnings = validate_distribution(training_info)
        assert len(warnings) >= 1
        assert any("LOW" in w for w in warnings)

    def test_low_pct_too_high(self):
        training_info = {
            "low_pct": 0.98,  # above 0.95
            "medium_pct": 0.01,
            "high_pct": 0.001,
        }
        warnings = validate_distribution(training_info)
        assert any("LOW" in w for w in warnings)

    def test_medium_pct_out_of_range(self):
        training_info = {
            "low_pct": 0.93,
            "medium_pct": 0.10,  # above 0.08
            "high_pct": 0.01,
        }
        warnings = validate_distribution(training_info)
        assert any("MEDIUM" in w for w in warnings)

    def test_high_pct_out_of_range(self):
        training_info = {
            "low_pct": 0.93,
            "medium_pct": 0.06,
            "high_pct": 0.05,  # above 0.02
        }
        warnings = validate_distribution(training_info)
        assert any("HIGH" in w for w in warnings)

    def test_boundary_values_pass(self):
        """Exact boundary values should pass."""
        training_info = {
            "low_pct": 0.90,
            "medium_pct": 0.04,
            "high_pct": 0.005,
        }
        warnings = validate_distribution(training_info)
        assert warnings == []

    def test_all_out_of_range(self):
        training_info = {
            "low_pct": 0.50,
            "medium_pct": 0.30,
            "high_pct": 0.20,
        }
        warnings = validate_distribution(training_info)
        assert len(warnings) == 3
