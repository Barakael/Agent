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


def test_rolling_buffer_maxlen():
    agg = CandleAggregator(timeframe_minutes=5, buffer_size=3)
    base = 1700000000
    for i in range(5):
        bucket = (base // 300 + i) * 300
        agg.on_tick("frxEURUSD", 1.1 + i * 0.001, bucket)
        agg.on_tick("frxEURUSD", 1.1 + i * 0.001, bucket + 299)
        agg.on_tick("frxEURUSD", 1.1 + i * 0.001, bucket + 300)
    df = agg.get_dataframe("frxEURUSD")
    assert len(df) <= 4  # buffer 3 + current
