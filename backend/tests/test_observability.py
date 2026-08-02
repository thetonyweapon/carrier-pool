from app.observability import increment, observe_seconds, render_metrics, reset_metrics


def test_metrics_escape_labels_and_render_timer_samples() -> None:
    reset_metrics()
    increment("carrier_pool_requests_total", {"route": '/loads/"quoted"'})
    observe_seconds("carrier_pool_request_duration_seconds", 0.25)

    output = render_metrics({"source-a": 12.5})

    assert 'route="/loads/\\"quoted\\""' in output
    assert "carrier_pool_request_duration_seconds_count 1" in output
    assert "carrier_pool_request_duration_seconds_sum 0.250000" in output
    assert 'carrier_pool_source_lag_seconds{source_id="source-a"} 12.500' in output
    reset_metrics()
