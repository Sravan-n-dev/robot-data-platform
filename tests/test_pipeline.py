import pytest
from fastapi.testclient import TestClient

from generate_sample_bag import generate_bag
from rdp.api import create_app
from rdp.config import Settings


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("rdp")
    bags = root / "bags"
    bags.mkdir()
    generate_bag(bags / "faulty", duration_s=30, faults=True)
    generate_bag(bags / "clean", duration_s=30, faults=False)
    settings = Settings(database_url=f"sqlite:///{root / 'test.db'}",
                        data_dir=root / "data", ingest_root=bags)
    return TestClient(create_app(settings)), root


def _ingest(client, name):
    r = client.post("/runs/ingest", json={"path": name})
    assert r.status_code == 201, r.text
    return r.json()


def test_faulty_bag_reports_all_injected_faults(env):
    client, root = env
    run = _ingest(client, "faulty")
    kinds = {(a["topic"], a["kind"]) for a in client.get(f"/runs/{run['id']}/anomalies").json()}
    assert ("/odom", "message_drop") in kinds
    assert ("/scan", "sensor_dropout") in kinds
    assert ("/imu", "timestamp_regression") in kinds
    assert ("/odom", "invalid_values") in kinds
    assert (root / "data" / "runs" / run["id"] / "odom.parquet").exists()


def test_clean_bag_has_no_anomalies(env):
    client, _ = env
    run = _ingest(client, "clean")
    assert run["anomaly_count"] == 0


def test_topic_stats_rates(env):
    client, _ = env
    run = _ingest(client, "clean")
    rates = {t["topic"]: t["rate_hz"] for t in client.get(f"/runs/{run['id']}/topics").json()}
    assert rates["/odom"] == pytest.approx(20, rel=0.02)
    assert rates["/scan"] == pytest.approx(10, rel=0.02)
    assert rates["/imu"] == pytest.approx(50, rel=0.02)


def test_message_time_range_query(env):
    client, _ = env
    run = _ingest(client, "clean")
    start = run["start_ns"] + 5_000_000_000
    end = start + 1_000_000_000
    rows = client.get(f"/runs/{run['id']}/messages",
                      params={"topic": "/odom", "start_ns": start, "end_ns": end, "limit": 1000}).json()
    assert 20 <= len(rows) <= 21
    assert all(start <= r["stamp_ns"] <= end for r in rows)
    assert {"x", "y", "yaw", "v", "w"} <= set(rows[0]["values"])


def test_path_traversal_blocked_and_missing_bag(env):
    client, _ = env
    assert client.post("/runs/ingest", json={"path": "../etc"}).status_code == 400
    assert client.post("/runs/ingest", json={"path": "nope"}).status_code == 422
    assert client.get("/runs/does-not-exist").status_code == 404


def test_metrics_endpoint(env):
    client, _ = env
    _ingest(client, "faulty")
    body = client.get("/metrics").text
    assert "rdp_runs_ingested_total" in body and "rdp_anomalies_detected_total" in body
