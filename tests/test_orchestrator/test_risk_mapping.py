"""Tests for orchestrator risk mapping module."""

import pytest

from orchestrator.modules.risk_mapping import (
    clamp_loan_amount,
    loan_amount_to_tier,
    pd_to_risk_tier,
)
from shared.constants import LoanTier, RiskTier


class TestPdToRiskTier:
    def test_very_low(self):
        assert pd_to_risk_tier(0.00) == RiskTier.VERY_LOW
        assert pd_to_risk_tier(0.03) == RiskTier.VERY_LOW
        assert pd_to_risk_tier(0.049) == RiskTier.VERY_LOW

    def test_low(self):
        assert pd_to_risk_tier(0.05) == RiskTier.LOW
        assert pd_to_risk_tier(0.07) == RiskTier.LOW
        assert pd_to_risk_tier(0.099) == RiskTier.LOW

    def test_medium(self):
        assert pd_to_risk_tier(0.10) == RiskTier.MEDIUM
        assert pd_to_risk_tier(0.15) == RiskTier.MEDIUM
        assert pd_to_risk_tier(0.199) == RiskTier.MEDIUM

    def test_high(self):
        assert pd_to_risk_tier(0.20) == RiskTier.HIGH
        assert pd_to_risk_tier(0.30) == RiskTier.HIGH
        assert pd_to_risk_tier(0.349) == RiskTier.HIGH

    def test_very_high(self):
        assert pd_to_risk_tier(0.35) == RiskTier.VERY_HIGH
        assert pd_to_risk_tier(0.50) == RiskTier.VERY_HIGH
        assert pd_to_risk_tier(1.00) == RiskTier.VERY_HIGH

    def test_boundary_at_exactly_0_05(self):
        assert pd_to_risk_tier(0.05) == RiskTier.LOW

    def test_invalid_pd_raises(self):
        with pytest.raises(ValueError):
            pd_to_risk_tier(-0.01)
        with pytest.raises(ValueError):
            pd_to_risk_tier(1.01)


class TestLoanAmountToTier:
    def test_micro(self):
        assert loan_amount_to_tier(500) == LoanTier.MICRO
        assert loan_amount_to_tier(1000) == LoanTier.MICRO
        assert loan_amount_to_tier(2499) == LoanTier.MICRO

    def test_small(self):
        assert loan_amount_to_tier(2500) == LoanTier.SMALL
        assert loan_amount_to_tier(5000) == LoanTier.SMALL
        assert loan_amount_to_tier(10000) == LoanTier.SMALL


class TestClampLoanAmount:
    def test_within_range(self):
        assert clamp_loan_amount(5000) == 5000

    def test_below_min(self):
        assert clamp_loan_amount(100) == 500

    def test_above_max(self):
        assert clamp_loan_amount(15000) == 10000

    def test_at_boundaries(self):
        assert clamp_loan_amount(500) == 500
        assert clamp_loan_amount(10000) == 10000
