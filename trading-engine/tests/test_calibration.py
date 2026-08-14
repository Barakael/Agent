"""Barriers must fire where the chart asked, not where plain arithmetic lands them.

The numbers here are the ones Deriv quoted for frxEURUSD at x100 on a $1 stake:
a $0.42 stop fires at 1.15396, a $0.84 stop at 1.14895, and full stop-out at
1.14704, all from a spot of 1.15793.
"""

from __future__ import annotations

import pytest

from execution.multiplier import ContractCalibration, fit_calibration, usd_from_pct
from execution.orders import barriers_from_risk
from risk.gate import RiskCheckResult, RiskDecision

SPOT = 1.15793
QUOTED = [(0.42, 1.15396), (0.84, 1.14895)]


def _fit() -> ContractCalibration:
    calibration = fit_calibration(
        SPOT, QUOTED, symbol="frxEURUSD", stake=1.0, multiplier=100.0
    )
    assert calibration is not None
    return calibration


def test_fit_recovers_the_venues_notional_and_cost():
    calibration = _fit()
    # A $100 gross position behaves like ~$97 of exposure plus a fixed cost.
    assert calibration.notional == pytest.approx(97.0, abs=0.5)
    assert calibration.cost == pytest.approx(0.087, abs=0.005)
    assert calibration.gross_notional == 100.0


def test_fit_predicts_the_stop_out_it_was_not_given():
    calibration = _fit()
    stop_out_pct = (SPOT - 1.14704) / SPOT
    assert calibration.usd_for_stop(stop_out_pct) == pytest.approx(1.0, abs=0.01)


def test_fit_predicts_a_target_in_the_opposite_direction():
    """Measured live: a $0.64 target fired at 1.16647 from an entry of 1.15778."""
    calibration = _fit()
    target_pct = (1.16647 - 1.15778) / 1.15778
    assert calibration.usd_for_target(target_pct) == pytest.approx(0.64, abs=0.01)


def test_plain_arithmetic_puts_the_stop_inside_the_chart_level():
    """The bug this calibration exists to fix, stated as a measurement."""
    calibration = _fit()
    chart_pct = 0.00424
    naive = usd_from_pct(1.0, 100.0, chart_pct)
    corrected = calibration.usd_for_stop(chart_pct)
    # The naive limit is short by the contract's cost, so it fires early.
    assert corrected > naive
    where_naive_fires = calibration.stop_pct_for_usd(naive)
    shortfall = (chart_pct - where_naive_fires) / chart_pct
    assert shortfall > 0.15  # ~18% of the intended distance


def test_round_trip_between_usd_and_price_is_consistent():
    calibration = _fit()
    for pct in (0.002, 0.004, 0.008):
        assert calibration.stop_pct_for_usd(
            calibration.usd_for_stop(pct)
        ) == pytest.approx(pct)
        assert calibration.target_pct_for_usd(
            calibration.usd_for_target(pct)
        ) == pytest.approx(pct)


def test_degenerate_or_implausible_fits_are_refused():
    # Both probes at the same distance cannot define a line.
    assert fit_calibration(SPOT, [(0.42, 1.15396), (0.42, 1.15396)]) is None
    assert fit_calibration(SPOT, [(0.42, 1.15396)]) is None
    # Triggers above spot are not stop-side observations.
    assert fit_calibration(SPOT, [(0.42, 1.16), (0.84, 1.17)]) is None
    # A notional nowhere near stake x multiplier means the venue changed shape.
    assert (
        fit_calibration(SPOT, QUOTED, symbol="x", stake=1.0, multiplier=1000.0) is None
    )


def _risk(stake: float, stop: float, target: float) -> RiskCheckResult:
    return RiskCheckResult(
        decision=RiskDecision.APPROVED,
        reason="test",
        stake=stake,
        stop_loss_price=stop,
        take_profit_price=target,
    )


def test_barriers_use_the_calibration_when_given():
    entry = 1.15789
    risk = _risk(1.0, entry * (1 - 0.00424), entry * (1 + 0.00636))
    calibration = _fit()

    naive = barriers_from_risk(risk, entry, multiplier=100.0)
    corrected = barriers_from_risk(risk, entry, multiplier=100.0, calibration=calibration)

    assert naive.calibrated is False
    assert corrected.calibrated is True
    # Cost is added to the stop and taken off the target, so both move outward.
    assert corrected.usd_sl > naive.usd_sl
    assert corrected.usd_tp < naive.usd_tp
    # The planned chart distances are unchanged; only the encoding differs.
    assert corrected.sl_pct == pytest.approx(naive.sl_pct)
    assert corrected.tp_pct == pytest.approx(naive.tp_pct)


def test_calibrated_stop_is_what_the_trade_actually_risks():
    """The dollar limit is the loss, so sizing must use the calibrated amount."""
    entry = 1.15789
    risk = _risk(1.0, entry * (1 - 0.00424), entry * (1 + 0.00636))
    corrected = barriers_from_risk(
        risk, entry, multiplier=100.0, calibration=_fit()
    )
    assert corrected.usd_sl == pytest.approx(0.50, abs=0.01)
