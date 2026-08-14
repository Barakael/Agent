"""Tests for multiplier contract geometry and selection."""

from __future__ import annotations

from execution.multiplier import (
    contract_room_pct,
    parse_allowed_from_error,
    pct_from_usd,
    price_distance_pct,
    select_multiplier,
    stop_fits,
    usd_from_pct,
    usd_from_price_distance,
    validate_multiplier,
)


def test_contract_room_is_inverse_of_multiplier():
    assert contract_room_pct(80) == 0.0125
    assert round(contract_room_pct(30), 6) == 0.033333


def test_usd_and_pct_round_trip():
    usd = usd_from_pct(stake=100, multiplier=30, pct=0.02)
    assert usd == 60.0
    assert round(pct_from_usd(100, 30, usd), 6) == 0.02


def test_usd_from_price_distance_matches_chart_stop():
    # A 2-point stop on R_50 near 100 is a 2% move.
    assert price_distance_pct(100.0, 98.0) == 0.02
    assert usd_from_price_distance(100, 30, 100.0, 98.0) == 60.0
    assert usd_from_price_distance(100, 80, 100.0, 98.0) == 160.0


def test_stop_fits_rejects_a_stop_beyond_liquidation():
    # 2% stop needs 2.5% of room at the default safety factor.
    assert stop_fits(80, 0.02) is False
    assert stop_fits(30, 0.02) is True
    assert stop_fits(40, 0.02) is True
    assert stop_fits(50, 0.02) is False


def test_select_multiplier_prefers_the_highest_that_still_holds_the_stop():
    allowed = [10, 20, 30, 40, 60, 80, 100]
    assert select_multiplier(allowed, required_stop_pct=0.02) == 40
    assert select_multiplier(allowed, required_stop_pct=0.01) == 80
    # A very wide stop leaves nothing viable.
    assert select_multiplier(allowed, required_stop_pct=0.5) is None


def test_validate_multiplier_reports_the_allowed_set():
    ok, detail = validate_multiplier(30, [10, 20, 30])
    assert ok is True
    assert "accepted" in detail

    ok, detail = validate_multiplier(30, [50, 100])
    assert ok is False
    assert "50" in detail and "100" in detail

    ok, detail = validate_multiplier(30, [])
    assert ok is True


def test_parse_allowed_from_error_reads_deriv_code_args():
    error = {"subcode": "MultiplierOutOfRange", "code_args": ["10,20,30,40"]}
    assert parse_allowed_from_error(error) == [10.0, 20.0, 30.0, 40.0]
    assert parse_allowed_from_error({}) == []
    assert parse_allowed_from_error({"code_args": ["bad, 15"]}) == [15.0]
