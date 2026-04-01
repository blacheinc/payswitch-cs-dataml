"""Tests for loan amount agent trainer module."""

import importlib.util
import os
import sys

import numpy as np
import pandas as pd
import pytest

from shared.schemas.feature_schema import ALL_FEATURE_NAMES

_agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "training-agents", "loan-amount-agent"))
_spec = importlib.util.spec_from_file_location("la_trainer", os.path.join(_agent_dir, "modules", "trainer.py"),
                                                submodule_search_locations=[_agent_dir])
_trainer = importlib.util.module_from_spec(_spec)
sys.modules["la_trainer"] = _trainer
_spec.loader.exec_module(_trainer)

ensemble_predict = _trainer.ensemble_predict
prepare_data = _trainer.prepare_data


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_dummy_df(n=500):
    rng = np.random.RandomState(42)
    data = {name: rng.uniform(0, 1, n) for name in ALL_FEATURE_NAMES}
    data["default_flag"] = rng.choice([0, 1], n, p=[0.75, 0.25])
    data["max_successful_loan_ghs"] = rng.uniform(500, 10000, n)
    data["income_tier"] = rng.choice([0, 1, 2, 3], n)
    data["request_id"] = [f"REQ-{i}" for i in range(n)]
    data["credit_score"] = rng.randint(300, 850, n)
    data["score_grade"] = rng.choice(["A", "B", "C", "D", "E"], n)
    data["decision_label"] = rng.choice(["APPROVE", "DECLINE", "REFER"], n)
    data["data_quality_score"] = rng.uniform(0.6, 1.0, n)
    data["product_source"] = rng.choice(["45", "49", "45+49"], n)
    data["bureau_hit_status"] = rng.choice(["HIT", "THIN_FILE"], n)
    data["applicant_age_at_application"] = rng.randint(18, 65, n)
    data["credit_age_months_at_application"] = rng.randint(1, 200, n)
    return pd.DataFrame(data)


# ── Tests: prepare_data ───────────────────────────────────────────────────


class TestPrepareData:
    def test_returns_six_splits(self):
        df = _make_dummy_df()
        result = prepare_data(df)
        assert len(result) == 6

    def test_split_proportions_approximate(self):
        df = _make_dummy_df(1000)
        X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)
        total = len(X_train) + len(X_val) + len(X_holdout)
        assert total == 1000
        assert abs(len(X_train) / total - 0.70) < 0.05
        assert abs(len(X_val) / total - 0.15) < 0.05
        assert abs(len(X_holdout) / total - 0.15) < 0.05

    def test_drops_null_target_rows(self):
        df = _make_dummy_df(500)
        df.loc[0:49, "max_successful_loan_ghs"] = np.nan
        X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)
        total = len(X_train) + len(X_val) + len(X_holdout)
        assert total == 450

    def test_target_clipped_to_range(self):
        df = _make_dummy_df(500)
        df.loc[0, "max_successful_loan_ghs"] = 100.0   # below min 500
        df.loc[1, "max_successful_loan_ghs"] = 50000.0  # above max 10000
        _, _, _, y_train, y_val, y_holdout = prepare_data(df)
        all_y = pd.concat([y_train, y_val, y_holdout])
        assert all_y.min() >= 500.0
        assert all_y.max() <= 10000.0

    def test_only_feature_columns_in_X(self):
        df = _make_dummy_df()
        X_train, *_ = prepare_data(df)
        assert set(X_train.columns) == set(ALL_FEATURE_NAMES)


# ── Tests: ensemble_predict ───────────────────────────────────────────────


class TestEnsemblePredict:
    def _train_models(self):
        """Train quick sub-models for ensemble testing."""
        import lightgbm as lgb
        import xgboost as xgb
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import StandardScaler

        df = _make_dummy_df(500)
        X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)

        lgbm_model = lgb.LGBMRegressor(n_estimators=10, random_state=42, verbosity=-1)
        lgbm_model.fit(X_train, y_train)

        xgb_model = xgb.XGBRegressor(n_estimators=10, random_state=42, verbosity=0)
        xgb_model.fit(X_train, y_train, verbose=False)

        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        ridge_model = Ridge(alpha=1.0)
        ridge_model.fit(X_train_scaled, y_train)

        return lgbm_model, ridge_model, xgb_model, scaler, X_holdout

    def test_output_shape_matches_input(self):
        lgbm, ridge, xgb_m, scaler, X = self._train_models()
        result = ensemble_predict(lgbm, ridge, xgb_m, scaler, X)
        assert len(result) == len(X)

    def test_predictions_within_range(self):
        lgbm, ridge, xgb_m, scaler, X = self._train_models()
        result = ensemble_predict(lgbm, ridge, xgb_m, scaler, X)
        assert result.min() >= 500.0
        assert result.max() <= 10000.0

    def test_returns_numpy_array(self):
        lgbm, ridge, xgb_m, scaler, X = self._train_models()
        result = ensemble_predict(lgbm, ridge, xgb_m, scaler, X)
        assert isinstance(result, np.ndarray)

    def test_clamping_works(self):
        """Verify extreme predictions get clamped."""
        from unittest.mock import MagicMock

        import lightgbm as lgb
        import xgboost as xgb
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import StandardScaler

        df = _make_dummy_df(100)
        X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)

        # Create models that predict extreme values
        lgbm_model = MagicMock(spec=lgb.LGBMRegressor)
        lgbm_model.predict.return_value = np.full(len(X_holdout), 50000.0)

        ridge_model = MagicMock(spec=Ridge)
        ridge_model.predict.return_value = np.full(len(X_holdout), 50000.0)

        xgb_model = MagicMock(spec=xgb.XGBRegressor)
        xgb_model.predict.return_value = np.full(len(X_holdout), 50000.0)

        scaler = MagicMock(spec=StandardScaler)
        scaler.transform.return_value = X_holdout.values

        result = ensemble_predict(lgbm_model, ridge_model, xgb_model, scaler, X_holdout)
        assert result.max() == pytest.approx(10000.0)
