"""Tests for loan amount agent validator module."""

import importlib.util
import os
import sys

import pytest

_agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "training-agents", "loan-amount-agent"))
_spec = importlib.util.spec_from_file_location("la_validator", os.path.join(_agent_dir, "modules", "validator.py"),
                                                submodule_search_locations=[_agent_dir])
_validator = importlib.util.module_from_spec(_spec)
sys.modules["la_validator"] = _validator
_spec.loader.exec_module(_validator)

check_thresholds = _validator.check_thresholds
METRIC_THRESHOLDS = _validator.METRIC_THRESHOLDS


# ── Tests: check_thresholds ──────────────────────────────────────────────


class TestCheckThresholds:
    def test_all_passing_returns_empty(self):
        metrics = {
            "ensemble_rmse": 1500.0,
            "ensemble_mae": 1000.0,
            "ensemble_r2": 0.70,
        }
        warnings = check_thresholds(metrics)
        assert warnings == []

    def test_rmse_above_max(self):
        metrics = {
            "ensemble_rmse": 3000.0,  # above 2500
            "ensemble_mae": 1000.0,
            "ensemble_r2": 0.70,
        }
        warnings = check_thresholds(metrics)
        assert len(warnings) == 1
        assert "RMSE" in warnings[0]

    def test_mae_above_max(self):
        metrics = {
            "ensemble_rmse": 1500.0,
            "ensemble_mae": 2000.0,  # above 1500
            "ensemble_r2": 0.70,
        }
        warnings = check_thresholds(metrics)
        assert len(warnings) == 1
        assert "MAE" in warnings[0]

    def test_r2_below_min(self):
        metrics = {
            "ensemble_rmse": 1500.0,
            "ensemble_mae": 1000.0,
            "ensemble_r2": 0.40,  # below 0.55
        }
        warnings = check_thresholds(metrics)
        assert len(warnings) == 1
        assert "R" in warnings[0]

    def test_all_failing(self):
        metrics = {
            "ensemble_rmse": 5000.0,
            "ensemble_mae": 3000.0,
            "ensemble_r2": 0.10,
        }
        warnings = check_thresholds(metrics)
        assert len(warnings) == 3

    def test_boundary_values_pass(self):
        """Metrics exactly at threshold should pass."""
        metrics = {
            "ensemble_rmse": 2500.0,
            "ensemble_mae": 1500.0,
            "ensemble_r2": 0.55,
        }
        warnings = check_thresholds(metrics)
        assert warnings == []
