from datetime import datetime, timezone
from data.candle_aggregator import CandleAggregator


def test_candle_closes_on_bucket_change():
    agg = CandleAggregator(timeframe_minutes=5, buffer_size=10)
    base_epoch = 1700000000
    bucket = (base_epoch // 300) * 300
    agg.on_tick("frxEURUSD", 1.1000, bucket)
    agg.on_tick("frxEURUSD", 1.1005, bucket + 60)
    closed = agg.on_tick("frxEURUSD", 1.1010, bucket + 300)
    assert closed is not None
    assert closed.open == 1.1000
    assert closed.close == 1.1005


def test_historical_seed_forms_current_and_closes_next_bucket():
    agg = CandleAggregator(timeframe_minutes=5, buffer_size=10)
    base = (1700000000 // 300) * 300
    agg.load_historical_candles(
        "R_100",
        [
            {"epoch": base, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1},
            {"epoch": base + 300, "open": 100.5, "high": 102, "low": 100, "close": 101, "volume": 1},
        ],
    )
    # Same bucket ticks update forming candle
    assert agg.on_tick("R_100", 101.2, base + 300 + 60) is None
    # Next bucket closes forming candle
    closed = agg.on_tick("R_100", 101.5, base + 600)
    assert closed is not None
    assert closed.close == 101.2
    agg = CandleAggregator(timeframe_minutes=5, buffer_size=3)
    base = 1700000000
    for i in range(5):
        bucket = (base // 300 + i) * 300
        agg.on_tick("frxEURUSD", 1.1 + i * 0.001, bucket)
        agg.on_tick("frxEURUSD", 1.1 + i * 0.001, bucket + 299)
        agg.on_tick("frxEURUSD", 1.1 + i * 0.001, bucket + 300)
    df = agg.get_dataframe("frxEURUSD")
    assert len(df) <= 4  # buffer 3 + current


def test_weekend_gap_does_not_fabricate_bars():
    """Forex is shut for ~65h. The buffer should skip it, not fill it."""
    agg = CandleAggregator(timeframe_minutes=5, buffer_size=500)
    friday_close = int(
        datetime(2026, 8, 14, 20, 50, tzinfo=timezone.utc).timestamp() // 300 * 300
    )
    sunday_open = int(
        datetime(2026, 8, 16, 21, 5, tzinfo=timezone.utc).timestamp() // 300 * 300
    )

    agg.on_tick("frxEURUSD", 1.1600, friday_close)
    closed = agg.on_tick("frxEURUSD", 1.1650, sunday_open)

    assert closed is not None
    assert closed.epoch == friday_close
    df = agg.get_dataframe("frxEURUSD")
    # Two bars either side of the break, not the ~780 buckets it spans.
    assert len(df) == 2
    assert list(df["epoch"]) == [friday_close, sunday_open]


def test_elapsed_time_across_a_gap_comes_from_timestamps_not_bar_count():
    """Two adjacent bars can be 65 hours apart; bar counting would say 5 minutes."""
    agg = CandleAggregator(timeframe_minutes=5, buffer_size=500)
    friday = int(datetime(2026, 8, 14, 20, 50, tzinfo=timezone.utc).timestamp() // 300 * 300)
    sunday = int(datetime(2026, 8, 16, 21, 5, tzinfo=timezone.utc).timestamp() // 300 * 300)
    agg.on_tick("frxEURUSD", 1.16, friday)
    agg.on_tick("frxEURUSD", 1.165, sunday)

    df = agg.get_dataframe("frxEURUSD")
    gap_hours = (int(df["epoch"].iloc[1]) - int(df["epoch"].iloc[0])) / 3600
    assert gap_hours > 48
