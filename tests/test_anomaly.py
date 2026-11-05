import numpy as np

from rdp import anomaly

NS = 1_000_000_000


def _series(hz=10, n=100):
    return (np.arange(n) * NS // hz).astype(np.int64)


def test_clean_series_has_no_findings():
    assert anomaly.detect_gaps(_series()) == []


def test_message_drop_detected_and_counted():
    s = np.delete(_series(), [40, 41])          # 2 missing messages
    findings = anomaly.detect_gaps(s)
    assert len(findings) == 1 and findings[0].kind == "message_drop"
    assert "2 message" in findings[0].detail


def test_sensor_dropout_is_critical():
    s = np.delete(_series(n=200), np.arange(50, 80))   # 3 s gap at 10 Hz
    findings = anomaly.detect_gaps(s)
    assert [f.kind for f in findings] == ["sensor_dropout"]
    assert findings[0].severity == "critical"


def test_too_few_messages_is_ignored():
    assert anomaly.detect_gaps(_series(n=3)) == []


def test_timestamp_regression_and_duplicate():
    h = np.array([1, 2, 3, 2, 4, 4, 5], dtype=np.int64) * NS
    kinds = sorted(f.kind for f in anomaly.detect_timestamp_issues(h))
    assert kinds == ["timestamp_duplicate", "timestamp_regression"]


def test_invalid_values_summary():
    s = _series(n=10)
    mask = np.ones(10, dtype=bool)
    mask[[2, 6]] = False
    f = anomaly.detect_invalid(s, mask)
    assert len(f) == 1 and "2 message" in f[0].detail
