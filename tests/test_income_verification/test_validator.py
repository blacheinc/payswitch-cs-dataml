"""Tests for income verification agent validator module."""

import importlib.util
import os
import sys

import pytest

_agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "training-agents", "income-verification-agent"))
_spec = importlib.util.spec_from_file_location("iv_validator", os.path.join(_agent_dir, "modules", "validator.py"),
                                                submodule_search_locations=[_agent_dir])
_validator = importlib.util.module_from_spec(_spec)
sys.modules["iv_validator"] = _validator
_spec.loader.exec_module(_validator)

check_thresholds = _validator.check_thresholds
METRIC_THRESHOLDS = _validator.METRIC_THRESHOLDS


# ── Tests: check_thresholds ──────────────────────────────────────────────


class TestCheckThresholds:
    def test_all_passing_returns_empty(self):
        metrics = {
            "auc_ovr": 0.85,
            "weighted_f1": 0.80,
            "per_class_recall": {"LOW": 0.70, "MID": 0.75, "UPPER_MID": 0.72, "HIGH": 0.68},
            "per_class_precision": {"LOW": 0.65, "MID": 0.70, "UPPER_MID": 0.68, "HIGH": 0.60},
        }
        warnings = check_thresholds(metrics)
        assert warnings == []

    def test_auc_below_threshold(self):
        metrics = {
            "auc_ovr": 0.60,  # below 0.75
            "weighted_f1": 0.80,
            "per_class_recall": {"LOW": 0.70, "MID": 0.75, "UPPER_MID": 0.72, "HIGH": 0.68},
            "per_class_precision": {"LOW": 0.65, "MID": 0.70, "UPPER_MID": 0.68, "HIGH": 0.60},
        }
        warnings = check_thresholds(metrics)
        assert any("AUC" in w for w in warnings)

    def test_f1_below_threshold(self):
        metrics = {
            "auc_ovr": 0.85,
            "weighted_f1": 0.50,  # below 0.70
            "per_class_recall": {"LOW": 0.70, "MID": 0.75, "UPPER_MID": 0.72, "HIGH": 0.68},
            "per_class_precision": {"LOW": 0.65, "MID": 0.70, "UPPER_MID": 0.68, "HIGH": 0.60},
        }
        warnings = check_thresholds(metrics)
        assert any("F1" in w for w in warnings)

    def test_per_class_recall_below_threshold(self):
        metrics = {
            "auc_ovr": 0.85,
            "weighted_f1": 0.80,
            "per_class_recall": {"LOW": 0.70, "MID": 0.40, "UPPER_MID": 0.72, "HIGH": 0.68},
            "per_class_precision": {"LOW": 0.65, "MID": 0.70, "UPPER_MID": 0.68, "HIGH": 0.60},
        }
        warnings = check_thresholds(metrics)
        assert any("Recall" in w and "MID" in w for w in warnings)

    def test_per_class_precision_below_threshold(self):
        metrics = {
            "auc_ovr": 0.85,
            "weighted_f1": 0.80,
            "per_class_recall": {"LOW": 0.70, "MID": 0.75, "UPPER_MID": 0.72, "HIGH": 0.68},
            "per_class_precision": {"LOW": 0.30, "MID": 0.70, "UPPER_MID": 0.68, "HIGH": 0.60},
        }
        warnings = check_thresholds(metrics)
        assert any("Precision" in w and "LOW" in w for w in warnings)

    def test_multiple_failures(self):
        metrics = {
            "auc_ovr": 0.50,
            "weighted_f1": 0.40,
            "per_class_recall": {"LOW": 0.30, "MID": 0.30, "UPPER_MID": 0.30, "HIGH": 0.30},
            "per_class_precision": {"LOW": 0.20, "MID": 0.20, "UPPER_MID": 0.20, "HIGH": 0.20},
        }
        warnings = check_thresholds(metrics)
        # 2 top-level + 4 recall + 4 precision = 10
        assert len(warnings) == 10

    def test_boundary_values_pass(self):
        metrics = {
            "auc_ovr": 0.75,
            "weighted_f1": 0.70,
            "per_class_recall": {"LOW": 0.60, "MID": 0.60, "UPPER_MID": 0.60, "HIGH": 0.60},
            "per_class_precision": {"LOW": 0.55, "MID": 0.55, "UPPER_MID": 0.55, "HIGH": 0.55},
        }
        warnings = check_thresholds(metrics)
        assert warnings == []
