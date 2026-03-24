"""
Risk mapping module for the PaySwitch Credit Scoring Orchestrator.

Maps probability of default → risk tier, and loan amount → loan tier.
"""

from __future__ import annotations

from shared.constants import (
    LOAN_AMOUNT_MAX_GHS,
    LOAN_AMOUNT_MIN_GHS,
    LOAN_TIER_BOUNDARIES,
    PD_RISK_TIER_BOUNDARIES,
    LoanTier,
    RiskTier,
)
from shared.utils import clamp


def pd_to_risk_tier(probability_of_default: float) -> RiskTier:
    """
    Map a probability of default to a risk tier.

    Args:
        probability_of_default: Float in [0, 1].

    Returns:
        RiskTier enum value.

    Raises:
        ValueError: If PD is outside [0, 1].
    """
    if not 0.0 <= probability_of_default <= 1.0:
        raise ValueError(
            f"probability_of_default must be in [0, 1], got {probability_of_default}"
        )

    for lower, upper, tier in PD_RISK_TIER_BOUNDARIES:
        if lower <= probability_of_default < upper:
            return tier

    # Should not reach here given boundaries end at inf, but safety fallback
    return RiskTier.VERY_HIGH


def loan_amount_to_tier(amount_ghs: float) -> LoanTier:
    """
    Map a recommended loan amount (GHS) to a loan tier.

    Args:
        amount_ghs: Loan amount in GHS (already capped to [500, 10000]).

    Returns:
        LoanTier enum value.
    """
    for lower, upper, tier in LOAN_TIER_BOUNDARIES:
        if lower <= amount_ghs < upper:
            return tier

    # At exactly 10000, falls into SMALL
    if amount_ghs >= LOAN_TIER_BOUNDARIES[-1][0]:
        return LOAN_TIER_BOUNDARIES[-1][2]

    return LoanTier.MICRO


def clamp_loan_amount(amount_ghs: float) -> float:
    """Clamp loan amount to valid GHS range [500, 10000]."""
    return clamp(amount_ghs, LOAN_AMOUNT_MIN_GHS, LOAN_AMOUNT_MAX_GHS)
